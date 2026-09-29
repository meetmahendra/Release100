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

"""Synthetic Unit Tests for Biometric Duplicate vs Mismatch Disambiguation (Phase 4)."""

import pytest
import uuid

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.nodes.layer1_face_node import layer1_face_node
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.errors import PlatformErrorCode
from core_platform.app.telemetry.audit_engine import AuditEngine


@pytest.fixture
def test_db() -> DatabaseService:
    """Provide isolated in-memory or test database instance."""
    db_id = uuid.uuid4().hex[:8]
    return DatabaseService(db_url=f"sqlite:///logs/test_bio_{db_id}.db")


@pytest.mark.asyncio
async def test_own_face_duplicate_attendance_suppressed(test_db: DatabaseService) -> None:
    """Sending own face twice in the same shift informs operator without duplicate attendance."""
    # 1. Register operator and supervisor
    test_db.register_employee(
        emp_code="MGR-1001",
        full_name="Rajesh Sharma",
        phone_number="+919800099999",
        assigned_kiosk_id="CANEBOT-PUNE-05",
        role="SUPERVISOR",
        status="ACTIVE",
    )
    test_db.register_employee(
        emp_code="EMP-1042",
        full_name="Mahendra Gurav",
        phone_number="+919800011122",
        assigned_kiosk_id="CANEBOT-PUNE-05",
        role="OPERATOR",
        reporting_manager_emp_code="MGR-1001",
        status="ACTIVE",
    )

    # Record first duty check-in
    test_db.record_attendance(
        correlation_id="test-corr-init",
        emp_code="EMP-1042",
        kiosk_id="CANEBOT-PUNE-05",
        face_confidence=0.96,
        gps_distance_meters=12.5,
        geofence_verified=True,
        chiller_temp_c=3.2,
        haccp_compliant=True,
        haccp_status="SAFE_RANGE",
        is_duty_checkin=True,
    )

    # 2. Second check-in on same day with own face (similarity = 0.95) and no chiller reading
    state: TemperatureMarkerState = {
        "correlation_id": "test-dup-01",
        "operator_emp_code": "EMP-1042",
        "sender_phone": "+919800011122",
        "kiosk_id": "CANEBOT-PUNE-05",
        "face_confidence": 0.95,
        "chiller_temp_c": None,
    }

    result = await layer1_face_node(state, test_db)
    assert result["is_duty_checkin"] is False
    assert result["reply_message"] == "ℹ️ Shift attendance already marked today."


@pytest.mark.asyncio
async def test_face_mismatch_routes_critical_incident_to_supervisor(test_db: DatabaseService) -> None:
    """Biometric mismatch triggers CRITICAL priority queue item for reporting supervisor."""
    # Register supervisor and operator
    test_db.register_employee(
        emp_code="MGR-1001",
        full_name="Rajesh Sharma",
        phone_number="+919800099999",
        assigned_kiosk_id="CANEBOT-PUNE-05",
        role="SUPERVISOR",
        status="ACTIVE",
    )
    test_db.register_employee(
        emp_code="EMP-1042",
        full_name="Mahendra Gurav",
        phone_number="+919800011122",
        assigned_kiosk_id="CANEBOT-PUNE-05",
        role="OPERATOR",
        reporting_manager_emp_code="MGR-1001",
        status="ACTIVE",
    )

    # Simulate face mismatch (similarity 0.55 < 0.82)
    state: TemperatureMarkerState = {
        "correlation_id": "test-mismatch-01",
        "operator_emp_code": "EMP-1042",
        "sender_phone": "+919800011122",
        "kiosk_id": "CANEBOT-PUNE-05",
        "face_confidence": 0.55,
    }

    result = await layer1_face_node(state, test_db)

    # Verify zero false attribution & diversion to review
    assert result["layer_0_passed"] is False
    assert result["layer_2_disposition"] == "diverted_to_review"
    assert result["error_code"] == PlatformErrorCode.CONFIDENCE_BELOW_THRESHOLD.value
    assert "Identity Verification Issue" in result["reply_message"]

    # Verify CRITICAL message enqueued for reporting supervisor
    pending = test_db.get_pending_messages_for_recipient("+919800099999")
    assert len(pending) == 1
    assert pending[0].priority == 100  # CRITICAL
    assert pending[0].recipient_emp_code == "MGR-1001"
    assert pending[0].sender_emp_code == "EMP-1042"
    assert "Biometric Mismatch Alert" in pending[0].message_text


@pytest.mark.asyncio
async def test_workflow_end_to_end_mismatch_interception(test_db: DatabaseService) -> None:
    """Complete workflow halts before OCR and attributes nothing when mismatch occurs."""
    test_db.register_employee(
        emp_code="MGR-1001",
        full_name="Rajesh Sharma",
        phone_number="+919800099999",
        assigned_kiosk_id="CANEBOT-PUNE-05",
        role="SUPERVISOR",
        status="ACTIVE",
    )
    test_db.register_employee(
        emp_code="EMP-1042",
        full_name="Mahendra Gurav",
        phone_number="+919800011122",
        assigned_kiosk_id="CANEBOT-PUNE-05",
        role="OPERATOR",
        reporting_manager_emp_code="MGR-1001",
        status="ACTIVE",
    )

    kg = KnowledgeGraphService()
    workflow = TemperatureMarkerWorkflow(
        db_service=test_db,
        kg_service=kg,
        audit_engine=AuditEngine.get_instance(),
    )

    kiosk_coords = kg.get_kiosk_coordinates("CANEBOT-PUNE-05")
    assert kiosk_coords is not None
    user_coords = (kiosk_coords[0], kiosk_coords[1])

    state: TemperatureMarkerState = {
        "correlation_id": "test-wf-mismatch",
        "sender_phone": "+919800011122",
        "kiosk_id": "CANEBOT-PUNE-05",
        "user_coords": user_coords,
        "face_confidence": 0.40,  # Deep mismatch
    }

    final_state = await workflow.execute(state)
    assert final_state["layer_0_passed"] is False
    assert final_state["layer_2_disposition"] == "diverted_to_review"
    assert "Identity Verification Issue" in final_state["reply_message"]

    # Ensure no attendance record was created for the operator
    assert test_db.has_attendance_today("EMP-1042") is None
