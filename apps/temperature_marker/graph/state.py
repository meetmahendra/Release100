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
State Definition for Temperature & Attendance Marker Workflow.

Adheres strictly to Plan 03 v1.3. Strongly typed TypedDict passed
through every node in the LangGraph execution graph.
"""

from typing import Any, Dict, Optional, Tuple, TypedDict


class TemperatureMarkerState(TypedDict, total=False):
    """Execution state carried across LangGraph nodes."""

    # Inbound Event Context
    correlation_id: str
    sender_phone: str
    text_content: Optional[str]
    raw_image_bytes: Optional[bytes]
    user_coords: Optional[Tuple[float, float]]
    kiosk_id: str

    # Operator Verification
    operator_emp_code: str
    operator_name: str
    operator_status: str  # ACTIVE, PENDING_APPROVAL, UNREGISTERED
    face_confidence: float
    is_duty_checkin: bool
    multimodal_analysis: Optional[Dict[str, Any]]

    # Location & Geofencing
    geofence_verified: bool
    distance_meters: float
    gps_accuracy_meters: Optional[float]
    explicit_location_request: bool
    watermark_timestamp: Optional[str]

    # Dual-Engine OCR & Temperature
    chiller_temp_c: Optional[float]
    ocr_engine_used: str  # local_onnx, cloud_gemini_vision
    ocr_confidence: float

    # HACCP Food Safety Evaluation
    haccp_status: str  # SAFE_RANGE, CRITICAL_HAZARD, NORMAL_RANGE
    haccp_compliant: bool

    # 3-Tier Safety Gate Tracking
    layer_0_passed: bool
    layer_2_disposition: str  # approved_autonomous, diverted_to_review, simulated_shadow
    error_code: Optional[str]
    error_message: Optional[str]

    # Telemetry & Downstream
    audit_record_hash: Optional[str]
    audit_sequence_number: Optional[int]
    outbox_queued: bool

    # Outbound WhatsApp Communication
    reply_message: str
