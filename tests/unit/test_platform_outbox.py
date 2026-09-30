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
Unit tests for platform-level outbox queue and synchronizer.
Adheres strictly to GEES v1.0.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict
import pytest

from core_platform.app.outbox.queue import PlatformOutboxQueue, get_platform_outbox
from core_platform.app.outbox.synchronizer import OutboxSynchronizer


def test_platform_outbox_crud(tmp_path: Path) -> None:
    """Test outbox enqueue, get_pending, mark_synced, mark_failed, stats."""
    db_file = tmp_path / "test_outbox.db"
    queue = PlatformOutboxQueue(db_path=db_file)

    # Initial stats
    stats = queue.get_stats()
    assert stats["pending"] == 0

    # Enqueue items
    id1 = queue.enqueue(
        app_id="temperature_marker",
        target="in_house_rest",
        payload={"temp": 4.5, "status": "SAFE"},
    )
    id2 = queue.enqueue(
        app_id="mail_organizer",
        target="gmail_api",
        payload={"action": "apply_label"},
    )
    assert id1 != id2

    # Verify pending
    pending = queue.get_pending()
    assert len(pending) == 2

    # Verify filter by app
    tm_pending = queue.get_pending(app_id="temperature_marker")
    assert len(tm_pending) == 1
    assert tm_pending[0]["item_id"] == id1

    # Mark synced
    queue.mark_synced(id1)
    pending_after_sync = queue.get_pending()
    assert len(pending_after_sync) == 1
    assert pending_after_sync[0]["item_id"] == id2

    # Mark failed
    queue.mark_failed(id2)
    stats2 = queue.get_stats(app_id="mail_organizer")
    assert stats2["failed"] == 1

    # Requeue failed
    requeued = queue.requeue_failed()
    assert requeued == 1

    # Global accessor
    global_q = get_platform_outbox()
    assert isinstance(global_q, PlatformOutboxQueue)


@pytest.mark.anyio
async def test_outbox_synchronizer() -> None:
    """Test outbox synchronizer _drain_cycle logic."""
    outbox = get_platform_outbox()
    outbox.enqueue(
        app_id="test_app",
        target="in_house_rest",
        payload={"data": "hello"},
    )

    sync = OutboxSynchronizer(drain_interval_seconds=0.1)

    # Custom dispatcher mock
    async def mock_dispatch(app_id: str, target: str, payload: Dict[str, Any]) -> tuple[bool, str]:
        return True, "synced_ok"

    sync._dispatch_item = mock_dispatch  # type: ignore[assignment]

    synced, failed = await sync._drain_cycle()
    assert synced >= 1

    # Test failed dispatch
    outbox.enqueue(
        app_id="test_app",
        target="in_house_rest",
        payload={"data": "fail_test"},
    )

    async def mock_fail_dispatch(app_id: str, target: str, payload: Dict[str, Any]) -> tuple[bool, str]:
        return False, "connection_refused"

    sync._dispatch_item = mock_fail_dispatch  # type: ignore[assignment]
    synced2, failed2 = await sync._drain_cycle()
    assert failed2 >= 1

    # Stop test
    sync.stop()
    assert sync._stop_event.is_set() is True


@pytest.mark.anyio
async def test_outbox_synchronizer_run_and_dispatch() -> None:
    """Test OutboxSynchronizer.run() loop lifecycle and dispatch routing."""
    sync = OutboxSynchronizer(drain_interval_seconds=0.05)

    # Test real _dispatch_item for temperature_marker
    ok, msg = await sync._dispatch_item(
        app_id="temperature_marker",
        target="in_house_rest",
        payload={"kiosk_id": "TEST-01", "temp": 3.4},
    )
    # in_house_rest connector will attempt dispatch or fail gracefully
    assert isinstance(ok, bool)
    assert isinstance(msg, str)

    # Test _dispatch_item for mail_organizer transmitter
    ok_mail, msg_mail = await sync._dispatch_item(
        app_id="mail_organizer",
        target="gmail_api",
        payload={"action": "apply_labels", "gmail_id": "G-100", "add_labels": ["READ"]},
    )
    assert ok_mail is True

    # Test _dispatch_item for unknown / unregistered apps (safe rejection without silent data loss)
    ok_other, msg_other = await sync._dispatch_item(
        app_id="unregistered_app",
        target="custom_api",
        payload={"test": 123},
    )
    assert ok_other is False
    assert "no active outbox transmitter registered" in msg_other

    # Test run() background worker loop
    task = asyncio.create_task(sync.run())
    await asyncio.sleep(0.1)
    sync.stop()
    await task
    assert sync._stop_event.is_set() is True

