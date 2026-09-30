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
Platform-Level Outbox Synchronizer.

Adheres to Plan 01 v1.4 Section 1 and Plan 02 v1.3 Section 11.
Provides an async background drain worker that periodically flushes
the PlatformOutboxQueue to downstream targets when connectivity is available.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple

from core_platform.app.outbox.queue import get_platform_outbox

logger = logging.getLogger("core_platform.outbox.synchronizer")


class OutboxSynchronizer:
    """
    Async background worker that periodically drains the platform outbox queue.

    Each pending item is dispatched to its target downstream connector.
    On success: marked SYNCED. On failure: marked FAILED (retried next cycle).
    """

    def __init__(self, drain_interval_seconds: float = 30.0) -> None:
        """Initialize the OutboxSynchronizer.

        Args:
            drain_interval_seconds: How often to attempt draining (default 30s).
        """
        self.drain_interval = drain_interval_seconds
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        """Start the perpetual drain loop. Call this as an asyncio task."""
        logger.info("[OutboxSynchronizer] Starting platform outbox drain worker (interval=%ss).", self.drain_interval)
        while not self._stop_event.is_set():
            try:
                synced, failed = await self._drain_cycle()
                if synced > 0 or failed > 0:
                    logger.info("[OutboxSynchronizer] Drain cycle: %d synced, %d failed.", synced, failed)
            except Exception as exc:
                logger.debug("[OutboxSynchronizer] Drain cycle error: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.drain_interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        """Signal the drain loop to stop gracefully."""
        self._stop_event.set()

    async def _drain_cycle(self) -> Tuple[int, int]:
        """Execute one drain cycle over all pending outbox items.

        Returns:
            Tuple of (synced_count, failed_count).
        """
        outbox = get_platform_outbox()
        pending = outbox.get_pending(limit=50)
        synced_count = 0
        failed_count = 0

        for item in pending:
            try:
                payload = json.loads(item["payload_json"])
                success, msg = await self._dispatch_item(
                    app_id=item["app_id"],
                    target=item["target"],
                    payload=payload,
                )
                if success:
                    outbox.mark_synced(item["item_id"])
                    synced_count += 1
                else:
                    outbox.mark_failed(item["item_id"])
                    failed_count += 1
                    logger.debug("[OutboxSynchronizer] Item %s failed: %s", item["item_id"], msg)
            except Exception as exc:
                outbox.mark_failed(item["item_id"])
                failed_count += 1
                logger.debug("[OutboxSynchronizer] Item %s exception: %s", item.get("item_id"), exc)

        # Requeue eligible FAILED items for retry
        requeued = outbox.requeue_failed(max_attempts=5)
        if requeued > 0:
            logger.info("[OutboxSynchronizer] Requeued %d failed items for retry.", requeued)

        return synced_count, failed_count

    async def _dispatch_item(
        self,
        app_id: str,
        target: str,
        payload: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Dispatch a single outbox item to its downstream connector.

        Routing is app-aware: temperature_marker items use the downstream
        connector factory; future apps register their own dispatchers.

        Args:
            app_id: Source application cartridge ID.
            target: Target connector type string.
            payload: Structured data payload.

        Returns:
            Tuple of (success: bool, message: str).
        """
        # Ask the cartridge for its registered outbox transmitter callable.
        try:
            from core_platform.main import plugin_loader  # deferred import avoids circular dep
            app_instance = plugin_loader.get_application(app_id)
            if app_instance is not None:
                transmitter = app_instance.get_outbox_transmitter()
                if transmitter is not None:
                    res = await transmitter(target=target, payload=payload)
                    return bool(res[0]), str(res[1])
        except Exception as exc:
            return False, f"Transmitter lookup failed for app_id={app_id}: {exc}"

        # No transmitter registered — do not acknowledge to prevent silent drop
        return False, f"Dispatch failed: no active outbox transmitter registered for app_id={app_id}"

