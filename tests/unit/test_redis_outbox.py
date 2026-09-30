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
Unit Tests for Redis Streams Outbox Synchronizer.

Adheres strictly to GEES v2.0 Dual-Engine Verification Regime (Engine A).
"""

import pytest

from core_platform.app.outbox.redis_outbox import RedisOutboxSynchronizer, StreamMessage


@pytest.mark.asyncio
async def test_redis_outbox_push_and_read() -> None:
    """Verify push_event and read_events in standalone fallback mode."""
    sync = RedisOutboxSynchronizer(redis_url="")
    await sync.connect()
    assert not sync.is_connected_to_redis

    payload = {"kiosk_id": "KIOSK-01", "temperature": 3.8, "status": "OK"}
    msg_id = await sync.push_event(
        tenant_id="canectar_test",
        stream_name="temperature_events",
        payload=payload,
        correlation_id="corr-test-123",
    )

    assert msg_id is not None
    assert len(msg_id) > 0

    messages = await sync.read_events(
        tenant_id="canectar_test",
        stream_name="temperature_events",
        count=10,
    )
    assert len(messages) == 1
    msg = messages[0]
    assert msg.tenant_id == "canectar_test"
    assert msg.payload["temperature"] == 3.8
    assert msg.correlation_id == "corr-test-123"
    assert len(msg.sha256_hash) == 64

    length = await sync.get_stream_length("canectar_test", "temperature_events")
    assert length == 1

    await sync.close()


@pytest.mark.asyncio
async def test_redis_outbox_consumer_group_and_ack() -> None:
    """Verify consumer group creation, batch consumption, and message ACK."""
    sync = RedisOutboxSynchronizer(redis_url="")
    await sync.connect()

    tenant = "tenant_stream_test"
    stream = "orders"
    group = "order_processors"

    # Push 3 items
    for i in range(3):
        await sync.push_event(
            tenant_id=tenant,
            stream_name=stream,
            payload={"order_id": f"ord-{i}", "amount": 100 * (i + 1)},
        )

    # Create consumer group
    created = await sync.create_consumer_group(tenant_id=tenant, stream_name=stream, group_name=group)
    assert created is True

    # Consume batch
    batch1 = await sync.consume_group(
        tenant_id=tenant,
        stream_name=stream,
        group_name=group,
        consumer_name="worker_a",
        batch_size=2,
    )
    assert len(batch1) == 2
    assert batch1[0].payload["order_id"] == "ord-0"
    assert batch1[1].payload["order_id"] == "ord-1"

    # Ack first message
    acked = await sync.ack_event(
        tenant_id=tenant,
        stream_name=stream,
        group_name=group,
        message_id=batch1[0].message_id,
    )
    assert acked is True

    # Consume remaining
    batch2 = await sync.consume_group(
        tenant_id=tenant,
        stream_name=stream,
        group_name=group,
        consumer_name="worker_a",
        batch_size=5,
    )
    assert len(batch2) == 1
    assert batch2[0].payload["order_id"] == "ord-2"

    await sync.close()


@pytest.mark.asyncio
async def test_redis_outbox_dlq_diversion() -> None:
    """Verify DLQ routing stores failed payload with error metadata."""
    sync = RedisOutboxSynchronizer(redis_url="")
    await sync.connect()

    dlq_id = await sync.push_dlq(
        tenant_id="tenant_err",
        app_id="mail_organizer",
        original_payload={"email_id": "em_failed_99"},
        error_reason="ConnectionRefusedError to downstream ERP",
        retry_count=3,
    )
    assert dlq_id is not None

    dlq_messages = await sync.read_events(
        tenant_id="tenant_err",
        stream_name="dlq:failures",
        count=10,
    )
    assert len(dlq_messages) == 1
    msg = dlq_messages[0]
    assert msg.payload["app_id"] == "mail_organizer"
    assert msg.payload["error_reason"] == "ConnectionRefusedError to downstream ERP"
    assert msg.payload["retry_count"] == 3

    await sync.close()
