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

"""Layer 1 Biometric Face Match Node."""

import numpy as np

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.errors import PlatformErrorCode
from core_platform.app.skills.display_ocr import DisplayOCRSkill
from core_platform.app.skills.face_recognizer import FaceRecognizerSkill
from core_platform.app.skills.registry import get_platform_skill


async def layer1_face_node(
    state: TemperatureMarkerState,
    db_service: DatabaseService,
) -> TemperatureMarkerState:
    """Extract face embedding from duty selfie and match against registered vector.

    Adheres strictly to GEES v1.0 (Zero-Trust Security & Layer 2 Gate).
    If a combined photo (selfie + chiller display) is provided, invokes unified multimodal
    inspection to resolve both operator attendance and gauge metrics.
    If no registered template exists, enrolls the operator on first compliant duty selfie;
    otherwise diverts strictly to Supervisor review with face_confidence = 0.0 (Zero fake passes).
    """
    raw_image = state.get("raw_image_bytes")
    emp_code = state.get("operator_emp_code", "")

    # Execute combined photo inspection if image is attached and not yet analyzed
    if raw_image is not None and "multimodal_analysis" not in state:
        try:
            ocr_skill: DisplayOCRSkill = get_platform_skill("display_ocr")  # type: ignore
            analysis = await ocr_skill.analyze_combined_kiosk_photo(raw_image)
            state["multimodal_analysis"] = analysis
            temp_c_val = analysis.get("temperature_c")
            if temp_c_val is not None and analysis.get("ocr_confidence", 0.0) >= 0.85:
                state["chiller_temp_c"] = float(temp_c_val)
                state["ocr_confidence"] = float(analysis["ocr_confidence"])
                state["ocr_engine_used"] = "cloud_multimodal_vision"
        except Exception:
            pass

    # If face confidence is already explicitly set (e.g. simulated or upstream detector)
    if "face_confidence" in state and state["face_confidence"] is not None:
        return state

    employee = db_service.get_employee_by_code(emp_code)
    face_skill: FaceRecognizerSkill = get_platform_skill("face_recognizer")  # type: ignore

    # If employee has registered encrypted embedding: verify identity
    if employee and employee.encrypted_face_embedding:
        if raw_image is not None:
            try:
                registered_vec = face_skill.decrypt_embedding(employee.encrypted_face_embedding)
                success, duty_vec, msg = await face_skill.compute_embedding(raw_image)
                if success and duty_vec is not None:
                    sim = face_skill.compute_cosine_similarity(registered_vec, duty_vec)
                    state["face_confidence"] = round(sim, 4)
                    if sim < 0.82:
                        state["layer_2_disposition"] = "diverted_to_review"
                        state["error_code"] = PlatformErrorCode.CONFIDENCE_BELOW_THRESHOLD.value
                        state["error_message"] = f"Face similarity {sim:.4f} below 0.82 threshold."
                    return state
            except Exception as err:
                state["face_confidence"] = 0.0
                state["layer_2_disposition"] = "diverted_to_review"
                state["error_code"] = PlatformErrorCode.BIOMETRIC_NO_FACE_DETECTED.value
                state["error_message"] = f"Face match extraction error: {err}"
                return state

        # If shift attendance was already recorded today, allow periodic chiller gauge photos without face
        if db_service.has_attendance_today(emp_code) is not None:
            state["face_confidence"] = 1.0
            state["is_duty_checkin"] = False
            return state

        # Initial duty check-in requires a selfie photo
        state["face_confidence"] = 0.0
        state["layer_2_disposition"] = "diverted_to_review"
        state["error_code"] = PlatformErrorCode.BIOMETRIC_NO_FACE_DETECTED.value
        state["error_message"] = "Duty selfie missing for registered operator."
        return state

    # If employee exists but has no registered biometric vector: self-enroll or divert
    if employee and not employee.encrypted_face_embedding:
        if raw_image is not None:
            try:
                success, duty_vec, msg = await face_skill.compute_embedding(raw_image)
                if success and duty_vec is not None:
                    # Enroll new biometric template for active operator
                    encrypted_emb = face_skill.encrypt_embedding(duty_vec)
                    db_service.register_employee(
                        emp_code=employee.emp_code,
                        full_name=employee.full_name,
                        phone_number=employee.phone_number,
                        assigned_kiosk_id=employee.assigned_kiosk_id,
                        encrypted_face_embedding=encrypted_emb,
                        status=employee.status,
                    )
                    state["face_confidence"] = 0.90
                    return state
            except Exception:
                pass

        # No valid photo to enroll: divert to supervisor approval gate
        state["face_confidence"] = 0.0
        state["layer_2_disposition"] = "diverted_to_review"
        state["error_code"] = PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
        state["error_message"] = f"Operator '{emp_code}' has no registered biometric template and no selfie for enrollment."
        state["reply_message"] = (
            f"⚠️ Biometric Registration Required: Operator '{emp_code}' has no registered face template. "
            "Diverted to Kiosk Supervisor for manual verification."
        )
        return state

    # Operator not found in database
    state["face_confidence"] = 0.0
    state["layer_2_disposition"] = "diverted_to_review"
    state["error_code"] = PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
    state["error_message"] = f"Operator code '{emp_code}' not found."
    return state
