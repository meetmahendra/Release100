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

"""Synthetic Unit Tests for Downstream Outbox Synchronization."""

from pathlib import Path
import pytest
from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.downstream.in_house_rest import InHouseRESTConnector
from apps.temperature_marker.downstream.outbox_manager import OutboxManager


@pytest.mark.asyncio
async def test_outbox_manager_sync(tmp_path: Path) -> None:
    """OutboxManager must flush pending items and mark them synced."""
    db_file = tmp_path / "outbox_test.db"
    db_service = DatabaseService(db_url=f"sqlite:///{db_file}")
    connector = InHouseRESTConnector()
    manager = OutboxManager(db_service=db_service, connector=connector)

    # Enqueue 2 items
    db_service.enqueue_outbox("corr-1", "in_house_rest", {"temp": 3.2})
    db_service.enqueue_outbox("corr-2", "in_house_rest", {"temp": 3.5})

    assert len(db_service.get_pending_outbox_items()) == 2

    synced, failed = await manager.sync_pending_outbox()
    assert synced == 2
    assert failed == 0
    assert len(db_service.get_pending_outbox_items()) == 0


@pytest.mark.asyncio
async def test_outbox_manager_network_failure_resilience(tmp_path: Path) -> None:
    """Outbox items must remain in PENDING state when downstream is unreachable."""
    db_file = tmp_path / "outbox_fail_test.db"
    db_service = DatabaseService(db_url=f"sqlite:///{db_file}")
    connector = InHouseRESTConnector()
    manager = OutboxManager(db_service=db_service, connector=connector)

    # Enqueue item configured to simulate offline endpoint
    db_service.enqueue_outbox("corr-offline", "in_house_rest", {"temp": 3.2, "mock_offline": True})

    synced, failed = await manager.sync_pending_outbox()
    assert synced == 0
    assert failed == 1
    # Item remains in database! Zero data loss
    assert len(db_service.get_pending_outbox_items()) == 1
