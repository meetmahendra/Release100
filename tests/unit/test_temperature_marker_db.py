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

"""Synthetic Unit Tests for DatabaseService."""

from pathlib import Path
import pytest
from apps.temperature_marker.database.db_service import DatabaseService


@pytest.fixture
def db_service(tmp_path: Path) -> DatabaseService:
    """Create isolated SQLite database service instance."""
    db_file = tmp_path / "test_marker.db"
    return DatabaseService(db_url=f"sqlite:///{db_file}")


def test_register_and_lookup_employee(db_service: DatabaseService) -> None:
    """Register employee and query by phone and code."""
    emp = db_service.register_employee(
        emp_code="EMP-1042",
        full_name="Rajesh Pawar",
        phone_number="+919800011122",
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="ACTIVE",
    )
    assert emp.id is not None

    found_by_phone = db_service.get_employee_by_phone("+919800011122")
    assert found_by_phone is not None
    assert found_by_phone.emp_code == "EMP-1042"

    found_by_code = db_service.get_employee_by_code("EMP-1042")
    assert found_by_code is not None
    assert found_by_code.full_name == "Rajesh Pawar"


def test_record_attendance(db_service: DatabaseService) -> None:
    """Record attendance and verify persisted fields."""
    rec = db_service.record_attendance(
        correlation_id="corr-12345",
        emp_code="EMP-1042",
        kiosk_id="CANEBOT-PUNE-04",
        face_confidence=0.94,
        gps_distance_meters=18.4,
        geofence_verified=True,
        chiller_temp_c=3.2,
        haccp_compliant=True,
        haccp_status="SAFE_RANGE",
    )
    assert rec.id is not None
    assert rec.chiller_temp_c == 3.2
    assert rec.haccp_compliant is True


def test_outbox_queue_operations(db_service: DatabaseService) -> None:
    """Enqueue outbox items and mark synced."""
    item = db_service.enqueue_outbox(
        correlation_id="corr-999",
        target_gateway="in_house_rest",
        payload={"temp": 3.2},
    )
    assert item.status == "PENDING"

    pending = db_service.get_pending_outbox_items()
    assert len(pending) == 1
    assert pending[0].id == item.id

    db_service.mark_outbox_synced(item.id)
    pending_after = db_service.get_pending_outbox_items()
    assert len(pending_after) == 0
