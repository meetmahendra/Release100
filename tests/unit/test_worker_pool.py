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
Unit Tests for OutboxWorkerPool and DLQ retry logic.

Adheres strictly to GEES v2.0 Dual-Engine Verification Regime (Engine A).
"""

import asyncio
from typing import List
import pytest

from core_platform.app.outbox.redis_outbox import RedisOutboxSynchronizer, StreamMessage
from core_platform.app.outbox.worker_pool import OutboxWorkerPool


@pytest.mark.asyncio
async def test_worker_pool_successful_processing() -> None:
    """Verify worker pool consumes, executes handler, and updates metrics."""
    sync = RedisOutboxSynchronizer(redis_url="")
    await sync.connect()

    tenant = "test_tenant"
    stream = "temperature_events"

    # Push 2 events
    await sync.push_event(tenant, stream, {"kiosk": "K-01", "temp": 3.4})
    await sync.push_event(tenant, stream, {"kiosk": "K-02", "temp": 3.7})

    received_msgs: List[StreamMessage] = []

    async def mock_handler(msg: StreamMessage) -> bool:
        received_msgs.append(msg)
        return True

    worker_pool = OutboxWorkerPool(
        synchronizer=sync,
        consumer_group="test_group",
        consumer_name="test_worker",
        poll_interval_seconds=0.05,
        max_retries=2,
        base_backoff_seconds=0.01,
    )
    worker_pool.register_handler(stream, mock_handler)

    await worker_pool.start([(tenant, stream)])
    # Wait briefly for worker loop to process messages
    await asyncio.sleep(0.2)
    worker_pool.stop()

    assert len(received_msgs) == 2
    assert worker_pool.processed_count == 2
    assert worker_pool.failed_count == 0
    assert worker_pool.dlq_count == 0

    await sync.close()


@pytest.mark.asyncio
async def test_worker_pool_failure_and_dlq_routing() -> None:
    """Verify worker pool retries failing handler and diverts payload to DLQ."""
    sync = RedisOutboxSynchronizer(redis_url="")
    await sync.connect()

    tenant = "test_tenant_dlq"
    stream = "failing_events"

    await sync.push_event(tenant, stream, {"critical_key": "will_fail"})

    attempts = 0

    async def failing_handler(msg: StreamMessage) -> bool:
        nonlocal attempts
        attempts += 1
        raise ValueError(f"Simulated connector crash attempt {attempts}")

    worker_pool = OutboxWorkerPool(
        synchronizer=sync,
        consumer_group="fail_group",
        consumer_name="fail_worker",
        poll_interval_seconds=0.05,
        max_retries=2,
        base_backoff_seconds=0.01,
    )
    worker_pool.register_handler(stream, failing_handler)

    await worker_pool.start([(tenant, stream)])
    await asyncio.sleep(0.3)
    worker_pool.stop()

    assert attempts >= 2
    assert worker_pool.failed_count == 1
    assert worker_pool.dlq_count == 1

    # Verify message landed in DLQ
    dlq_messages = await sync.read_events(tenant, "dlq:failures", count=10)
    assert len(dlq_messages) == 1
    assert dlq_messages[0].payload["original_payload"]["critical_key"] == "will_fail"

    await sync.close()
