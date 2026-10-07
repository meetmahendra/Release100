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
Synthetic Unit Tests for TemperatureMarkerWorkflow (Plan 03 v1.3).

Tests end-to-end execution of the state machine across standard cases,
unauthorized operators, geofence breaches, HACCP alerts, and physical anomalies.
"""

from pathlib import Path
import pytest

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.errors import PlatformErrorCode
from core_platform.app.telemetry.audit_engine import AuditEngine


@pytest.fixture
def workflow(tmp_path: Path) -> TemperatureMarkerWorkflow:
    """Provide a configured TemperatureMarkerWorkflow instance."""
    db_file = tmp_path / "workflow_test.db"
    db_service = DatabaseService(db_url=f"sqlite:///{db_file}")

    from apps.temperature_marker.services.session_manager import OperatorSessionManager
    OperatorSessionManager.get_instance().clear()

    # Register active test employee
    db_service.register_employee(
        emp_code="EMP-1042",
        full_name="Rajesh Pawar",
        phone_number="+919800011122",
        assigned_kiosk_id="NODE-PUNE-04",
        status="ACTIVE",
    )

    kg_service = KnowledgeGraphService()
    audit_engine = AuditEngine(audit_dir=tmp_path / "audit_logs")

    return TemperatureMarkerWorkflow(
        db_service=db_service,
        kg_service=kg_service,
        audit_engine=audit_engine,
    )


@pytest.mark.asyncio
async def test_workflow_happy_path(workflow: TemperatureMarkerWorkflow) -> None:
    """Standard check-in: active employee, within geofence, 3.2°C compliant chiller reading."""
    initial_state: TemperatureMarkerState = {
        "correlation_id": "corr-happy-001",
        "sender_phone": "+919800011122",
        "kiosk_id": "NODE-PUNE-04",
        "user_coords": (18.5622, 73.9169),  # ~15m from kiosk
        "raw_image_bytes": b"TEMP_READOUT_3.2C_SENSOR",
    }

    final_state = await workflow.execute(initial_state)

    assert final_state["operator_status"] == "ACTIVE"
    assert final_state["geofence_verified"] is True
    assert final_state["chiller_temp_c"] == 3.2
    assert final_state["haccp_compliant"] is True
    assert final_state["haccp_status"] == "SAFE_RANGE"
    assert final_state["audit_sequence_number"] is not None
    assert final_state["outbox_queued"] is True
    assert "Duty Marked & Chiller Verified" in final_state["reply_message"]


@pytest.mark.asyncio
async def test_workflow_unauthorized_phone_rejected(workflow: TemperatureMarkerWorkflow) -> None:
    """Unregistered phone number must be rejected at Layer 0 Auth Guard."""
    initial_state: TemperatureMarkerState = {
        "correlation_id": "corr-unauth-002",
        "sender_phone": "+910000000000",
        "kiosk_id": "NODE-PUNE-04",
    }

    final_state = await workflow.execute(initial_state)

    assert final_state["operator_status"] == "UNREGISTERED"
    assert final_state["layer_0_passed"] is False
    assert final_state["error_code"] == PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
    assert "Unauthorized" in final_state["reply_message"]


@pytest.mark.asyncio
async def test_workflow_geofence_breach_rejected(workflow: TemperatureMarkerWorkflow) -> None:
    """User coordinate far outside kiosk radius must be rejected at Layer 0 Location node."""
    initial_state: TemperatureMarkerState = {
        "correlation_id": "corr-geo-003",
        "sender_phone": "+919800011122",
        "kiosk_id": "NODE-PUNE-04",
        "user_coords": (18.6000, 73.9800),  # ~8 km away
        "raw_image_bytes": b"TEMP_3.2C",
    }

    final_state = await workflow.execute(initial_state)

    assert final_state["geofence_verified"] is False
    assert final_state["layer_0_passed"] is False
    assert final_state["error_code"] == PlatformErrorCode.SAFETY_GEOFENCE_VIOLATION.value
    assert "Location Mismatch" in final_state["reply_message"]


@pytest.mark.asyncio
async def test_workflow_critical_haccp_hazard(workflow: TemperatureMarkerWorkflow) -> None:
    """Chiller temperature > 7.0°C must trigger CRITICAL_HAZARD alert."""
    initial_state: TemperatureMarkerState = {
        "correlation_id": "corr-haccp-004",
        "sender_phone": "+919800011122",
        "kiosk_id": "NODE-PUNE-04",
        "user_coords": (18.5622, 73.9169),
        "raw_image_bytes": b"TEMP_8.5C",  # 8.5°C chiller reading
    }

    final_state = await workflow.execute(initial_state)

    assert final_state["chiller_temp_c"] == 8.5
    assert final_state["haccp_compliant"] is False
    assert final_state["haccp_status"] == "CRITICAL_HAZARD"
    assert "CRITICAL CHILLER WARNING" in final_state["reply_message"]
    # Still audited for regulatory non-repudiation
    assert final_state["audit_sequence_number"] is not None


@pytest.mark.asyncio
async def test_workflow_physical_temperature_anomaly(workflow: TemperatureMarkerWorkflow) -> None:
    """Impossible physical temperature (e.g. 145°C) must be caught by Layer 0 Sanity node."""
    initial_state: TemperatureMarkerState = {
        "correlation_id": "corr-anomaly-005",
        "sender_phone": "+919800011122",
        "kiosk_id": "NODE-PUNE-04",
        "user_coords": (18.5622, 73.9169),
        "raw_image_bytes": b"TEMP_145.0C",  # Impossibly high reading
    }

    final_state = await workflow.execute(initial_state)

    assert final_state["layer_0_passed"] is False
    assert final_state["error_code"] == PlatformErrorCode.SAFETY_PHYSICAL_BOUND_VIOLATION.value
    assert "Sensor Reading Corrupted" in final_state["reply_message"]


@pytest.mark.asyncio
async def test_workflow_periodic_chiller_photo_bypasses_location_prompt(workflow: TemperatureMarkerWorkflow) -> None:
    """An operator with active attendance today should NOT be prompted for location when sending subsequent photos."""
    # 1. Initial morning shift punch-in (location verified)
    first_state: TemperatureMarkerState = {
        "correlation_id": "corr-morning-001",
        "sender_phone": "+919800011122",
        "kiosk_id": "NODE-PUNE-04",
        "user_coords": (18.5621, 73.9168),
        "raw_image_bytes": b"DIGIT:3.2",
    }
    res1 = await workflow.execute(first_state)
    assert res1.get("geofence_verified") is True
    assert res1.get("is_duty_checkin") is True

    # 2. Hours later, operator sends a periodic chiller photo WITHOUT coordinates (user_coords = None)
    second_state: TemperatureMarkerState = {
        "correlation_id": "corr-periodic-002",
        "sender_phone": "+919800011122",
        "kiosk_id": "NODE-PUNE-04",
        "user_coords": None,  # GPS cache expired
        "raw_image_bytes": b"DIGIT:3.2",
    }
    res2 = await workflow.execute(second_state)

    # Must inherit station coordinates, bypass location prompt, and verify chiller reading
    assert res2.get("geofence_verified") is True
    assert "Please verify KioskNode location" not in str(res2.get("reply_message"))
    assert res2.get("is_duty_checkin") is False
    assert res2.get("chiller_temp_c") == 3.2
    assert "Chiller Verified" in str(res2.get("reply_message"))


@pytest.mark.asyncio
async def test_workflow_periodic_chiller_photo_no_face_exemption(workflow: TemperatureMarkerWorkflow) -> None:
    """An on-duty operator sending a periodic chiller photo without a face must NOT fail face matching."""
    # 1. First state: Morning punch in
    first_state: TemperatureMarkerState = {
        "correlation_id": "corr-morning-noface-1",
        "sender_phone": "+919800011122",
        "kiosk_id": "NODE-PUNE-04",
        "user_coords": (18.5621, 73.9168),
        "raw_image_bytes": b"DIGIT:3.2",
    }
    res1 = await workflow.execute(first_state)
    assert res1.get("is_duty_checkin") is True

    # 2. Second state: Periodic chiller photo with simulated OCR having face_detected=False
    second_state: TemperatureMarkerState = {
        "correlation_id": "corr-periodic-noface-2",
        "sender_phone": "+919800011122",
        "kiosk_id": "NODE-PUNE-04",
        "user_coords": None,
        "raw_image_bytes": b"DIGIT:3.5",
        "multimodal_analysis": {
            "face_detected": False,
            "face_confidence": 0.0,
            "temperature_c": 3.5,
            "ocr_confidence": 0.95,
        },
    }
    res2 = await workflow.execute(second_state)
    assert res2.get("is_duty_checkin") is False
    assert res2.get("chiller_temp_c") == 3.5
    assert "Biometric Face Match Low" not in str(res2.get("reply_message"))
    assert "Chiller Verified (Periodic Log)" in str(res2.get("reply_message"))
