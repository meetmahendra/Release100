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

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("apps.temperature_marker.face_node")

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.errors import PlatformErrorCode
from core_platform.app.skills.display_ocr import DisplayOCRSkill
from core_platform.app.skills.face_recognizer import FaceRecognizerSkill
from core_platform.app.skills.registry import get_platform_skill


def _enqueue_mismatch_incident(
    state: TemperatureMarkerState,
    db_service: DatabaseService,
    employee: Any,
    similarity: float,
) -> None:
    """Route biometric mismatch anomaly to reporting supervisor queue as CRITICAL priority."""
    from core_platform.app.config import settings

    mgr_emp = getattr(employee, "reporting_manager_emp_code", None) or ""
    mgr_phone = ""
    if mgr_emp:
        mgr = db_service.get_employee_by_code(mgr_emp)
        if mgr and mgr.phone_number:
            mgr_phone = mgr.phone_number
    if not mgr_phone:
        mgr_phone = getattr(settings, "SUPERVISOR_PHONE", "+919800000000")
        mgr_emp = mgr_emp or "SUPERVISOR"

    corr_id = str(state.get("correlation_id", "inc-face-mismatch"))
    kiosk_str = str(state.get("kiosk_id", employee.assigned_kiosk_id))
    sender_phone = str(state.get("sender_phone", employee.phone_number))

    db_service.enqueue_internal_message(
        correlation_id=corr_id,
        sender_phone=sender_phone,
        sender_emp_code=employee.emp_code,
        sender_name=employee.full_name,
        kiosk_id=kiosk_str,
        recipient_emp_code=mgr_emp,
        recipient_phone=mgr_phone,
        message_text=(
            f"🚨 Biometric Mismatch Alert: Photo submitted for operator {employee.full_name} "
            f"({employee.emp_code}) at kiosk {kiosk_str} did not match registered face template "
            f"(similarity: {similarity:.4f} < 0.82). Verification diverted."
        ),
        priority=100,  # CRITICAL
    )


async def layer1_face_node(
    state: TemperatureMarkerState,
    db_service: DatabaseService,
) -> TemperatureMarkerState:
    """Extract face embedding from duty selfie and match against registered vector.

    Adheres strictly to GEES v1.0 (Zero-Trust Security & Layer 2 Gate).
    Disambiguates between:
    - Own face duplicate attendance (already marked today):
      Informs operator, preserves periodic chiller logs without duplicate duty records.
    - Face mismatch (< 0.82) or unrecognized person:
      Zero false attribution, diverts to review, enqueues CRITICAL alert for supervisor.
    """
    raw_image = state.get("raw_image_bytes")
    emp_code = state.get("operator_emp_code", "")
    employee = db_service.get_employee_by_code(emp_code)

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
            if analysis.get("watermark_timestamp"):
                state["watermark_timestamp"] = str(analysis["watermark_timestamp"])
        except Exception:
            pass

    # Check if operator is already on duty today
    is_on_duty = db_service.has_attendance_today(emp_code) is not None
    multimodal_analysis = state.get("multimodal_analysis") or {}

    # If face confidence is already explicitly set (e.g. simulated or upstream detector)
    if "face_confidence" in state and state["face_confidence"] is not None:
        sim = float(state["face_confidence"])
        if sim < 0.82:
            state["layer_0_passed"] = False
            state["layer_2_disposition"] = "diverted_to_review"
            state["error_code"] = PlatformErrorCode.CONFIDENCE_BELOW_THRESHOLD.value
            state["error_message"] = f"Face similarity {sim:.4f} below 0.82 threshold."
            state["reply_message"] = (
                "⚠️ Biometric Face Match Low: Identity Verification Issue — face does not match registered profile. "
                "Incident routed to Supervisor for review."
            )
            if employee:
                _enqueue_mismatch_incident(state, db_service, employee, sim)
            return state
        else:
            # Own face confirmed
            if is_on_duty:
                state["is_duty_checkin"] = False
                if state.get("chiller_temp_c") is None:
                    state["reply_message"] = "ℹ️ Shift attendance already marked today."
            else:
                state["is_duty_checkin"] = True
            return state

    # If already on duty and submitting a periodic chiller photo where no face is present or chiller temp was read:
    if is_on_duty and (
        multimodal_analysis.get("face_detected") is False
        or (state.get("chiller_temp_c") is not None and not multimodal_analysis.get("face_detected", False))
    ):
        state["face_confidence"] = 1.0
        state["is_duty_checkin"] = False
        return state

    face_skill: FaceRecognizerSkill = get_platform_skill("face_recognizer")  # type: ignore

    # If employee has registered encrypted embedding: verify identity
    if employee and employee.encrypted_face_embedding:
        if raw_image is not None:
            try:
                from pathlib import Path
                ref_path = Path("logs/photos") / f"{employee.emp_code}_profile.jpg"
                matched: bool = False
                match_score: float = 0.0
                reason: str = ""
                no_face: bool = False

                if ref_path.exists():
                    ref_bytes = ref_path.read_bytes()
                    matched, match_score, reason = await face_skill.verify_face_match(ref_bytes, raw_image)
                    if match_score == 0.0 and "no face" in reason.lower():
                        no_face = True
                else:
                    registered_vec = face_skill.decrypt_embedding(employee.encrypted_face_embedding)
                    success, duty_vec, msg = await face_skill.compute_embedding(raw_image)
                    if success and duty_vec is not None:
                        match_score = face_skill.compute_cosine_similarity(registered_vec, duty_vec)
                        matched = (match_score >= 0.82)
                        reason = f"Cosine similarity {match_score:.4f}"
                    else:
                        no_face = True

                if no_face:
                    # Check if operator already marked shift attendance today
                    if is_on_duty:
                        # Periodic chiller check allowed without face during active shift
                        state["face_confidence"] = 1.0
                        state["is_duty_checkin"] = False
                        return state
                    else:
                        state["face_confidence"] = 0.0
                        state["layer_2_disposition"] = "diverted_to_review"
                        state["error_code"] = PlatformErrorCode.BIOMETRIC_NO_FACE_DETECTED.value
                        state["error_message"] = "Duty selfie missing or face not recognized for registered operator."
                        state["reply_message"] = (
                            "⚠️ Face Not Detected: Shift attendance is pending. Please submit a front-facing selfie to check in."
                        )
                        return state

                if not matched:
                    # If operator is on duty and chiller temp was successfully extracted, this is an on-duty periodic reading
                    if is_on_duty and state.get("chiller_temp_c") is not None:
                        state["face_confidence"] = 1.0
                        state["is_duty_checkin"] = False
                        return state

                    # Mismatch / Unrecognized person: Zero false attribution
                    state["face_confidence"] = round(match_score, 4)
                    state["layer_0_passed"] = False
                    state["layer_2_disposition"] = "diverted_to_review"
                    state["error_code"] = PlatformErrorCode.CONFIDENCE_BELOW_THRESHOLD.value
                    state["error_message"] = f"Face similarity {match_score:.4f} below 0.82 threshold: {reason}"
                    state["reply_message"] = (
                        "⚠️ Biometric Face Match Low: Identity Verification Issue — face does not match registered profile. "
                        "Incident routed to Supervisor for review."
                    )
                    _enqueue_mismatch_incident(state, db_service, employee, match_score)
                    return state

                # Own face matched!
                state["face_confidence"] = round(match_score, 4)
                if db_service.has_attendance_today(emp_code) is not None:
                    state["is_duty_checkin"] = False
                    if state.get("chiller_temp_c") is None:
                        state["reply_message"] = "ℹ️ Shift attendance already marked today."
                else:
                    state["is_duty_checkin"] = True
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
        state["reply_message"] = (
            "⚠️ Face Not Detected: Please submit a front-facing selfie to check in for your shift."
        )
        return state

    # If employee is already ACTIVE but has no registered biometric vector yet:
    # Auto-enroll their baseline photo and proceed with shift check-in
    if employee and employee.status == "ACTIVE" and not employee.encrypted_face_embedding:
        if raw_image is not None:
            try:
                success, duty_vec, msg = await face_skill.compute_embedding(raw_image)
                if success and duty_vec is not None:
                    # Persist reference photo to disk for visual admin audit
                    from pathlib import Path
                    photo_dir = Path("logs/photos")
                    photo_dir.mkdir(parents=True, exist_ok=True)
                    photo_path = photo_dir / f"{employee.emp_code}_profile.jpg"
                    try:
                        photo_path.write_bytes(raw_image)
                    except Exception as err:
                        logger.warning("[FaceNode] Failed to write profile photo to disk: %s", err)

                    # Enroll new biometric template for active employee
                    encrypted_emb = face_skill.encrypt_embedding(duty_vec)
                    db_service.register_employee(
                        emp_code=employee.emp_code,
                        full_name=employee.full_name,
                        phone_number=employee.phone_number,
                        assigned_kiosk_id=employee.assigned_kiosk_id,
                        encrypted_face_embedding=encrypted_emb,
                        status="ACTIVE",
                    )
                    state["face_confidence"] = 0.95
                    state["is_duty_checkin"] = True
                    return state
            except Exception as err:
                logger.warning("[FaceNode] Error during initial biometric registration: %s", err)

        state["face_confidence"] = 0.0
        state["layer_2_disposition"] = "diverted_to_review"
        state["error_code"] = PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
        state["error_message"] = f"Operator '{emp_code}' has no registered biometric template."
        state["reply_message"] = (
            f"⚠️ Biometric Registration Required: Operator '{emp_code}' has no registered face template. "
            "Please submit your onboarding selfie to your CaneBot chat for admin approval."
        )
        return state

    # Operator not found in database
    state["face_confidence"] = 0.0
    state["layer_2_disposition"] = "diverted_to_review"
    state["error_code"] = PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
    state["error_message"] = f"Operator code '{emp_code}' not found."
    return state
