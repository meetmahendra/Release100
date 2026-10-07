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
        assigned_kiosk_id="NODE-PUNE-04",
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
        kiosk_id="NODE-PUNE-04",
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


def test_employee_role_and_manager_hierarchy(db_service: DatabaseService) -> None:
    """Register manager and operator with hierarchy linkage."""
    mgr = db_service.register_employee(
        emp_code="MGR-001",
        full_name="Rajesh Sharma",
        phone_number="+919822000001",
        assigned_kiosk_id="HQ-PUNE-OFFICE",
        role="MANAGER",
    )
    assert mgr.role == "MANAGER"

    op = db_service.register_employee(
        emp_code="OP-005",
        full_name="Mahendra Gurav",
        phone_number="+918087545430",
        assigned_kiosk_id="NODE-PUNE-05",
        role="OPERATOR",
        reporting_manager_emp_code="MGR-001",
    )
    assert op.role == "OPERATOR"
    assert op.reporting_manager_emp_code == "MGR-001"


def test_internal_message_queue_priority_and_lifecycle(db_service: DatabaseService) -> None:
    """Enqueue operational messages with different priorities and verify sorting and resolution."""
    mgr_phone = "+919822000001"

    # Enqueue standard query (Priority 25)
    db_service.enqueue_internal_message(
        correlation_id="corr-q1",
        sender_phone="+918087545430",
        sender_emp_code="OP-005",
        sender_name="Mahendra Gurav",
        kiosk_id="NODE-PUNE-05",
        recipient_emp_code="MGR-001",
        recipient_phone=mgr_phone,
        message_text="Shift timing query",
        priority=25,
    )

    # Enqueue critical hazard (Priority 100)
    crit_msg = db_service.enqueue_internal_message(
        correlation_id="corr-q2",
        sender_phone="+918087545430",
        sender_emp_code="OP-005",
        sender_name="Mahendra Gurav",
        kiosk_id="NODE-PUNE-05",
        recipient_emp_code="MGR-001",
        recipient_phone=mgr_phone,
        message_text="Juice motor vibrating loudly",
        priority=100,
    )

    # Enqueue urgent operational note (Priority 75)
    db_service.enqueue_internal_message(
        correlation_id="corr-q3",
        sender_phone="+919800011122",
        sender_emp_code="OP-004",
        sender_name="Rahul Patil",
        kiosk_id="NODE-PUNE-04",
        recipient_emp_code="MGR-001",
        recipient_phone=mgr_phone,
        message_text="Out of 250ml cups",
        priority=75,
    )

    # Verify pending count
    assert db_service.count_pending_messages_for_recipient(mgr_phone) == 3

    # Verify priority sorting: Critical (100) -> Urgent (75) -> Query (25)
    pending = db_service.get_pending_messages_for_recipient(mgr_phone)
    assert len(pending) == 3
    assert pending[0].priority == 100
    assert pending[0].message_text == "Juice motor vibrating loudly"
    assert pending[1].priority == 75
    assert pending[2].priority == 25

    # Bind outbound WhatsApp message ID to critical message
    db_service.bind_outbound_wamid(crit_msg.id, "wamid.HBgM12345")
    found_by_wamid = db_service.get_message_by_wamid("wamid.HBgM12345")
    assert found_by_wamid is not None
    assert found_by_wamid.id == crit_msg.id
    assert found_by_wamid.status == "DELIVERED"

    # Manager resolves the message
    resolved = db_service.resolve_internal_message(
        message_id=crit_msg.id,
        reply_context="Shut down motor and use manual bypass",
        resolved_by_phone=mgr_phone,
    )
    assert resolved is not None
    assert resolved.status == "RESOLVED"
    assert resolved.reply_context == "Shut down motor and use manual bypass"

    # Pending count decreases
    assert db_service.count_pending_messages_for_recipient(mgr_phone) == 2

