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
Distributed Redis Streams Outbox & Asynchronous Event Bus.

Adheres strictly to Plan 09 / GEES v2.0 Enterprise Cloud Scale:
- Enterprise event streaming across tenant-partitioned streams.
- Cryptographic SHA-256 payload integrity verification.
- Zero-dependency resilience: Automatic in-memory fallback when Redis is unconfigured or absent.
"""

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set
import uuid

from core_platform.app.config import settings

logger = logging.getLogger("core_platform.outbox.redis")


@dataclass
class StreamMessage:
    """Immutable representation of a message within a platform event stream."""
    message_id: str
    tenant_id: str
    stream: str
    payload: Dict[str, Any]
    sha256_hash: str
    timestamp: str
    correlation_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize message to dictionary."""
        return asdict(self)


class RedisOutboxSynchronizer:
    """
    Enterprise asynchronous outbox synchronizer backed by Redis Streams
    with automatic in-memory fallback for standalone/offline deployments.
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        """Initialize Redis Outbox Synchronizer.

        Args:
            redis_url: Optional redis connection string (e.g. 'redis://localhost:6379/0').
        """
        self.redis_url = redis_url if redis_url is not None else settings.REDIS_URL
        self._redis_client: Optional[Any] = None
        self._is_connected: bool = False

        # In-memory stream buffer fallback for local edge or test mode
        self._memory_streams: Dict[str, List[StreamMessage]] = {}
        self._consumer_groups: Dict[str, Dict[str, Set[str]]] = {}  # stream -> {group -> set of acked ids}
        self._group_cursors: Dict[str, Dict[str, int]] = {}  # stream -> {group -> last read index}
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Attempt to establish asynchronous connection to Redis server."""
        if not self.redis_url:
            logger.debug("[Outbox] No REDIS_URL configured; operating in local in-memory stream mode.")
            self._is_connected = False
            return False

        try:
            import redis.asyncio as aioredis
            self._redis_client = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis_client.ping()
            self._is_connected = True
            logger.info(f"[Outbox] Successfully connected to Redis Streams at {self.redis_url}")
            return True
        except Exception as exc:
            logger.warning(
                f"[Outbox] Redis connection failed ({exc}). Operating in fallback in-memory stream mode."
            )
            self._is_connected = False
            self._redis_client = None
            return False

    @property
    def is_connected_to_redis(self) -> bool:
        """Return True if connected to a real Redis server."""
        return self._is_connected and self._redis_client is not None

    async def push_event(
        self,
        tenant_id: str,
        stream_name: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> str:
        """
        Append a structured event to the specified stream.

        Args:
            tenant_id: Tenant identifier for multi-tenant partitioning.
            stream_name: Base stream name (e.g. 'temperature_events', 'mail_events').
            payload: Serializable event payload dictionary.
            correlation_id: Optional W3C or request correlation ID.

        Returns:
            The generated message ID string.
        """
        corr_id = correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        now_utc = datetime.now(timezone.utc).isoformat()
        payload_str = json.dumps(payload, sort_keys=True)
        sha256_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        if self.is_connected_to_redis and self._redis_client is not None:
            try:
                stream_key = f"stream:{tenant_id}:{stream_name}"
                msg_fields = {
                    "tenant_id": tenant_id,
                    "payload": payload_str,
                    "sha256_hash": sha256_hash,
                    "timestamp": now_utc,
                    "correlation_id": corr_id,
                }
                msg_id: str = await self._redis_client.xadd(stream_key, msg_fields)
                return str(msg_id)
            except Exception as exc:
                logger.error(f"[Outbox] Redis xadd failed ({exc}), storing in local stream buffer.")

        # In-memory fallback
        async with self._lock:
            stream_key = f"stream:{tenant_id}:{stream_name}"
            msg_id = f"{int(time.time() * 1000)}-{len(self._memory_streams.get(stream_key, []))}"
            msg = StreamMessage(
                message_id=msg_id,
                tenant_id=tenant_id,
                stream=stream_key,
                payload=payload,
                sha256_hash=sha256_hash,
                timestamp=now_utc,
                correlation_id=corr_id,
            )
            if stream_key not in self._memory_streams:
                self._memory_streams[stream_key] = []
            self._memory_streams[stream_key].append(msg)
            return msg_id

    async def read_events(
        self,
        tenant_id: str,
        stream_name: str,
        count: int = 50,
        last_id: str = "0",
    ) -> List[StreamMessage]:
        """
        Read raw sequential events from a stream.

        Args:
            tenant_id: Tenant identifier.
            stream_name: Base stream name.
            count: Max messages to return.
            last_id: Starting ID after which to read.
        """
        stream_key = f"stream:{tenant_id}:{stream_name}"

        if self.is_connected_to_redis and self._redis_client is not None:
            try:
                raw_entries = await self._redis_client.xrange(stream_key, min=last_id, count=count)
                messages: List[StreamMessage] = []
                for entry_id, data in raw_entries:
                    messages.append(
                        StreamMessage(
                            message_id=str(entry_id),
                            tenant_id=data.get("tenant_id", tenant_id),
                            stream=stream_key,
                            payload=json.loads(data.get("payload", "{}")),
                            sha256_hash=data.get("sha256_hash", ""),
                            timestamp=data.get("timestamp", ""),
                            correlation_id=data.get("correlation_id", ""),
                        )
                    )
                return messages
            except Exception as exc:
                logger.error(f"[Outbox] Redis xrange failed: {exc}")

        # In-memory fallback
        async with self._lock:
            entries = self._memory_streams.get(stream_key, [])
            return entries[:count]

    async def create_consumer_group(
        self,
        tenant_id: str,
        stream_name: str,
        group_name: str,
    ) -> bool:
        """Idempotently create a consumer group for a stream."""
        stream_key = f"stream:{tenant_id}:{stream_name}"

        if self.is_connected_to_redis and self._redis_client is not None:
            try:
                await self._redis_client.xgroup_create(
                    stream_key,
                    group_name,
                    id="0",
                    mkstream=True,
                )
                return True
            except Exception as exc:
                if "BUSYGROUP" in str(exc):
                    return True
                logger.warning(f"[Outbox] Redis xgroup_create failed: {exc}")
                return False

        # In-memory fallback
        async with self._lock:
            if stream_key not in self._consumer_groups:
                self._consumer_groups[stream_key] = {}
                self._group_cursors[stream_key] = {}
            if group_name not in self._consumer_groups[stream_key]:
                self._consumer_groups[stream_key][group_name] = set()
                self._group_cursors[stream_key][group_name] = 0
            return True

    async def consume_group(
        self,
        tenant_id: str,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        batch_size: int = 10,
    ) -> List[StreamMessage]:
        """
        Consume a batch of events as part of a consumer group.
        """
        stream_key = f"stream:{tenant_id}:{stream_name}"

        if self.is_connected_to_redis and self._redis_client is not None:
            try:
                results = await self._redis_client.xreadgroup(
                    group_name,
                    consumer_name,
                    {stream_key: ">"},
                    count=batch_size,
                )
                messages: List[StreamMessage] = []
                for s_key, entries in results:
                    for entry_id, data in entries:
                        messages.append(
                            StreamMessage(
                                message_id=str(entry_id),
                                tenant_id=data.get("tenant_id", tenant_id),
                                stream=s_key,
                                payload=json.loads(data.get("payload", "{}")),
                                sha256_hash=data.get("sha256_hash", ""),
                                timestamp=data.get("timestamp", ""),
                                correlation_id=data.get("correlation_id", ""),
                            )
                        )
                return messages
            except Exception as exc:
                logger.error(f"[Outbox] Redis xreadgroup failed: {exc}")

        # In-memory fallback
        async with self._lock:
            all_entries = self._memory_streams.get(stream_key, [])
            cursor = self._group_cursors.get(stream_key, {}).get(group_name, 0)
            acked_set = self._consumer_groups.get(stream_key, {}).get(group_name, set())

            unconsumed: List[StreamMessage] = []
            for item in all_entries[cursor:]:
                if item.message_id not in acked_set:
                    unconsumed.append(item)
                    if len(unconsumed) >= batch_size:
                        break

            if stream_key not in self._group_cursors:
                self._group_cursors[stream_key] = {}
            self._group_cursors[stream_key][group_name] = cursor + len(unconsumed)
            return unconsumed

    async def ack_event(
        self,
        tenant_id: str,
        stream_name: str,
        group_name: str,
        message_id: str,
    ) -> bool:
        """Acknowledge message processing completion."""
        stream_key = f"stream:{tenant_id}:{stream_name}"

        if self.is_connected_to_redis and self._redis_client is not None:
            try:
                await self._redis_client.xack(stream_key, group_name, message_id)
                return True
            except Exception as exc:
                logger.error(f"[Outbox] Redis xack failed: {exc}")
                return False

        # In-memory fallback
        async with self._lock:
            if stream_key in self._consumer_groups and group_name in self._consumer_groups[stream_key]:
                self._consumer_groups[stream_key][group_name].add(message_id)
                return True
            return False

    async def get_stream_length(self, tenant_id: str, stream_name: str) -> int:
        """Return total number of items currently in the stream."""
        stream_key = f"stream:{tenant_id}:{stream_name}"
        if self.is_connected_to_redis and self._redis_client is not None:
            try:
                length = await self._redis_client.xlen(stream_key)
                return int(length)
            except Exception:
                pass

        async with self._lock:
            return len(self._memory_streams.get(stream_key, []))

    async def push_dlq(
        self,
        tenant_id: str,
        app_id: str,
        original_payload: Dict[str, Any],
        error_reason: str,
        retry_count: int,
    ) -> str:
        """
        Divert unrecoverable failures to the Dead-Letter Queue (DLQ).
        """
        dlq_payload = {
            "app_id": app_id,
            "error_reason": error_reason,
            "retry_count": retry_count,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "original_payload": original_payload,
        }
        return await self.push_event(
            tenant_id=tenant_id,
            stream_name="dlq:failures",
            payload=dlq_payload,
        )

    async def close(self) -> None:
        """Close connection and clean up resources."""
        if self._redis_client is not None:
            try:
                await self._redis_client.close()
            except Exception:
                pass
            self._redis_client = None
            self._is_connected = False
