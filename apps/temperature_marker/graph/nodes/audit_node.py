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

"""Cryptographic Audit Logging Node (GEES v1.0 Pillar 3)."""

from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.telemetry.audit_engine import AuditEngine


async def audit_node(
    state: TemperatureMarkerState,
    audit_engine: AuditEngine,
) -> TemperatureMarkerState:
    """Commit verified operational payload to cryptographic SHA-256 audit ledger."""
    payload_summary = {
        "chiller_temp_c": state.get("chiller_temp_c"),
        "haccp_compliant": state.get("haccp_compliant"),
        "haccp_status": state.get("haccp_status"),
        "geofence_verified": state.get("geofence_verified"),
        "distance_meters": state.get("distance_meters"),
        "face_confidence": state.get("face_confidence"),
        "ocr_engine_used": state.get("ocr_engine_used"),
    }

    record = audit_engine.record_event(
        action_type="TEMPERATURE_AND_ATTENDANCE_COMMIT",
        payload_summary=payload_summary,
        operator_id=state.get("operator_emp_code", "UNKNOWN"),
        kiosk_id=state.get("kiosk_id"),
        layer_0_status="PASSED" if state.get("layer_0_passed", True) else "VIOLATION",
        layer_1_model=state.get("ocr_engine_used", "local_onnx"),
        layer_1_confidence=state.get("ocr_confidence", 1.0),
        layer_2_gate_status=state.get("layer_2_disposition", "APPROVED"),
        correlation_id=state.get("correlation_id"),
    )

    state["audit_record_hash"] = record.record_hash
    state["audit_sequence_number"] = record.sequence_number
    return state
