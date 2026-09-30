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

"""Offline Outbox Persistence Node (Edge Resilience Pattern)."""

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState


async def outbox_node(
    state: TemperatureMarkerState,
    db_service: DatabaseService,
) -> TemperatureMarkerState:
    """Save attendance record to local SQLite and enqueue in Outbox queue."""
    correlation_id = state.get("correlation_id", "")
    emp_code = state.get("operator_emp_code", "EMP-UNKNOWN")
    kiosk_id = state.get("kiosk_id", "CANEBOT-UNKNOWN")
    face_conf = state.get("face_confidence", 0.0)
    dist_m = state.get("distance_meters", 0.0)
    geo_ok = state.get("geofence_verified", False)
    temp_c = state.get("chiller_temp_c", 0.0)
    haccp_ok = state.get("haccp_compliant", False)
    haccp_stat = state.get("haccp_status", "UNKNOWN")
    ocr_eng = state.get("ocr_engine_used", "local_onnx")

    photo_path: str | None = None
    raw_img = state.get("raw_image_bytes")
    if raw_img and len(raw_img) > 100:
        from pathlib import Path
        media_dir = Path("logs/media")
        media_dir.mkdir(parents=True, exist_ok=True)
        disk_photo = media_dir / f"{correlation_id}.jpg"
        try:
            disk_photo.write_bytes(raw_img)
            photo_path = f"logs/media/{correlation_id}.jpg"
        except Exception as err:
            logger.warning("[OutboxNode] Failed to write photo %s to disk: %s", correlation_id, err)

    from apps.temperature_marker.services.session_manager import OperatorSessionManager
    session_mgr = OperatorSessionManager.get_instance()
    is_new_duty, checkin_time = session_mgr.record_or_verify_checkin(
        emp_code=emp_code, kiosk_id=kiosk_id, db_service=db_service
    )

    # 1. Save local attendance record (is_duty_checkin=True only on first check-in today)
    db_service.record_attendance(
        correlation_id=correlation_id,
        emp_code=emp_code,
        kiosk_id=kiosk_id,
        face_confidence=face_conf,
        gps_distance_meters=dist_m,
        geofence_verified=geo_ok,
        chiller_temp_c=temp_c if temp_c is not None else 0.0,
        haccp_compliant=haccp_ok,
        haccp_status=haccp_stat,
        ocr_engine_used=ocr_eng,
        is_duty_checkin=is_new_duty,
        photo_path=photo_path,
    )

    # Mark duty status in state for reply_node
    state["is_duty_checkin"] = is_new_duty

    # 2. Queue for downstream sync (only for verified autonomous commits)
    if state.get("layer_2_disposition") != "diverted_to_review" and state.get("layer_0_passed", True):
        outbox_payload = {
            "correlation_id": correlation_id,
            "emp_code": emp_code,
            "kiosk_id": kiosk_id,
            "chiller_temp_c": temp_c,
            "haccp_status": haccp_stat,
            "distance_meters": dist_m,
        }

        db_service.enqueue_outbox(
            correlation_id=correlation_id,
            target_gateway="in_house_rest",
            payload=outbox_payload,
        )
        state["outbox_queued"] = True
    else:
        state["outbox_queued"] = False
    return state
