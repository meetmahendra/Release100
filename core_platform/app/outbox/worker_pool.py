# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Distributed Outbox Worker Fleet & Dead-Letter Queue (DLQ) Processor.

Adheres strictly to Plan 09 / GEES v2.0 Enterprise Cloud Scale:
- Asynchronous task processing with consumer groups.
- Jittered exponential backoff retry mechanism.
- Automatic DLQ diversion to prevent pipeline deadlocks.
"""

import asyncio
from datetime import datetime, timezone
import logging
import random
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core_platform.app.outbox.redis_outbox import RedisOutboxSynchronizer, StreamMessage

logger = logging.getLogger("core_platform.outbox.worker_pool")

HandlerType = Callable[[StreamMessage], Awaitable[bool]]


class OutboxWorkerPool:
    """
    Manages asynchronous worker loops that consume from event streams,
    execute domain transmitters, and handle retries/DLQs.
    """

    def __init__(
        self,
        synchronizer: RedisOutboxSynchronizer,
        consumer_group: str = "platform_worker_group",
        consumer_name: str = "worker_1",
        poll_interval_seconds: float = 1.0,
        max_retries: int = 3,
        base_backoff_seconds: float = 0.5,
    ) -> None:
        self.synchronizer = synchronizer
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.poll_interval = poll_interval_seconds
        self.max_retries = max_retries
        self.base_backoff = base_backoff_seconds

        self._handlers: Dict[str, HandlerType] = {}  # stream_name -> handler
        self._is_running: bool = False
        self._worker_task: Optional[asyncio.Task[None]] = None

        # Telemetry metrics
        self.processed_count: int = 0
        self.failed_count: int = 0
        self.dlq_count: int = 0

    def register_handler(self, stream_name: str, handler: HandlerType) -> None:
        """Register a message processing callback for a specific stream name."""
        self._handlers[stream_name] = handler
        logger.info(f"[WorkerPool] Registered handler for stream: {stream_name}")

    async def start(self, streams: List[tuple[str, str]]) -> None:
        """
        Start the background worker loop across the given (tenant_id, stream_name) pairs.
        """
        if self._is_running:
            return

        self._is_running = True
        for tenant_id, stream_name in streams:
            await self.synchronizer.create_consumer_group(
                tenant_id=tenant_id,
                stream_name=stream_name,
                group_name=self.consumer_group,
            )

        self._worker_task = asyncio.create_task(self._worker_loop(streams))
        logger.info(f"[WorkerPool] Worker loop started for {len(streams)} streams.")

    def stop(self) -> None:
        """Signal the worker loop to stop gracefully."""
        self._is_running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()

    async def _worker_loop(self, streams: List[tuple[str, str]]) -> None:
        """Continuous polling worker loop."""
        while self._is_running:
            try:
                for tenant_id, stream_name in streams:
                    handler = self._handlers.get(stream_name)
                    if not handler:
                        continue

                    messages = await self.synchronizer.consume_group(
                        tenant_id=tenant_id,
                        stream_name=stream_name,
                        group_name=self.consumer_group,
                        consumer_name=self.consumer_name,
                        batch_size=10,
                    )

                    for msg in messages:
                        await self._process_single_message(tenant_id, stream_name, msg, handler)

                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[WorkerPool] Error in worker loop: {exc}")
                await asyncio.sleep(self.poll_interval)

    async def _process_single_message(
        self,
        tenant_id: str,
        stream_name: str,
        msg: StreamMessage,
        handler: HandlerType,
    ) -> None:
        """Process a message with exponential backoff and DLQ routing."""
        attempt = 0
        success = False
        last_error = ""

        while attempt < self.max_retries and not success:
            attempt += 1
            try:
                result = await handler(msg)
                if result:
                    success = True
                    self.processed_count += 1
                    await self.synchronizer.ack_event(
                        tenant_id=tenant_id,
                        stream_name=stream_name,
                        group_name=self.consumer_group,
                        message_id=msg.message_id,
                    )
                    return
                else:
                    last_error = "Handler returned False"
            except Exception as exc:
                last_error = str(exc)

            if not success and attempt < self.max_retries:
                # Exponential backoff with jitter
                backoff = (self.base_backoff * (2 ** (attempt - 1))) + random.uniform(0.05, 0.15)
                await asyncio.sleep(backoff)

        # If we reach here, all retries failed -> route to DLQ
        self.failed_count += 1
        self.dlq_count += 1
        logger.warning(
            f"[WorkerPool] Message {msg.message_id} on {stream_name} failed after {attempt} attempts: {last_error}. Moving to DLQ."
        )
        await self.synchronizer.push_dlq(
            tenant_id=tenant_id,
            app_id=stream_name,
            original_payload=msg.payload,
            error_reason=last_error,
            retry_count=attempt,
        )
        # Acknowledge from primary stream so consumer doesn't freeze
        await self.synchronizer.ack_event(
            tenant_id=tenant_id,
            stream_name=stream_name,
            group_name=self.consumer_group,
            message_id=msg.message_id,
        )
