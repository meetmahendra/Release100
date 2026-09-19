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

"""Layer 2 Post-Execution Confidence Gate Node."""

from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.errors import PlatformErrorCode
from core_platform.app.safety.layer2_post_gate import (
    Layer2PostExecutionGate,
    PostGateDisposition,
)


async def layer2_confidence_node(state: TemperatureMarkerState) -> TemperatureMarkerState:
    """Evaluate biometric face match and OCR display confidence against Layer 2 quality thresholds.

    Adheres strictly to GEES v1.0 (Pillar 1 & Layer 2):
    - Face confidence must meet threshold (default: 0.82)
    - OCR confidence must meet threshold (default: 0.85)
    If either fails, or if a previous node flagged diversion, state is diverted to review.
    """
    # Check if prior step already diverted (e.g. unreadable image or missing photo)
    prior_disposition = state.get("layer_2_disposition")
    if prior_disposition == PostGateDisposition.DIVERTED_TO_REVIEW.value:
        return state

    face_conf = state.get("face_confidence", 0.0)
    ocr_conf = state.get("ocr_confidence")

    # 1. Evaluate face match confidence
    face_pass, face_disp, face_reason = Layer2PostExecutionGate.evaluate_confidence(face_conf, threshold=0.82)
    if not face_pass:
        state["layer_2_disposition"] = face_disp.value
        state["error_code"] = PlatformErrorCode.CONFIDENCE_BELOW_THRESHOLD.value
        state["error_message"] = face_reason
        if not state.get("reply_message"):
            state["reply_message"] = (
                f"⚠️ Biometric Face Match Low ({face_conf * 100:.1f}%). "
                "Your attendance has been forwarded to Kiosk Supervisor for 1-click manual approval."
            )
        return state

    # 2. Evaluate OCR confidence if OCR reading is present
    if ocr_conf is not None:
        ocr_pass, ocr_disp, ocr_reason = Layer2PostExecutionGate.evaluate_confidence(float(ocr_conf), threshold=0.85)
        if not ocr_pass:
            state["layer_2_disposition"] = ocr_disp.value
            state["error_code"] = PlatformErrorCode.CONFIDENCE_BELOW_THRESHOLD.value
            state["error_message"] = ocr_reason
            if not state.get("reply_message"):
                state["reply_message"] = (
                    f"⚠️ Temperature Display Reading Low Confidence ({float(ocr_conf) * 100:.1f}%). "
                    "Forwarded to Kiosk Supervisor for review."
                )
            return state

    state["layer_2_disposition"] = PostGateDisposition.APPROVED_AUTONOMOUS.value
    return state
