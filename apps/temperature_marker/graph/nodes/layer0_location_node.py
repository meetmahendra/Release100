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

"""Layer 0 Geofencing and Location Verification Node."""

import logging
from typing import Any, Optional

from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.errors import PlatformErrorCode
from core_platform.app.skills.geofencing import GeofencingSkill
from core_platform.app.skills.registry import get_platform_skill

logger = logging.getLogger("apps.temperature_marker.location")


async def layer0_location_node(
    state: TemperatureMarkerState,
    kg_service: KnowledgeGraphService,
    db_service: Optional[Any] = None,
) -> TemperatureMarkerState:
    """Verify user coordinates against kiosk fleet geofence."""
    if kg_service.roster is None:
        kg_service.roster = kg_service._load_roster()
    kiosk_id = state.get("kiosk_id", "NODE-PUNE-05")
    user_coords = state.get("user_coords")

    # Check if operator previously clicked 1-click web location link or sent WhatsApp location
    if user_coords is None:
        from core_platform.app.ingress.location_session import get_session_coordinates
        sender_phone = state.get("sender_phone")
        cached = (
            (get_session_coordinates(str(sender_phone)) if sender_phone else None)
            or (get_session_coordinates(str(state.get("correlation_id", ""))) if state.get("correlation_id") else None)
            or get_session_coordinates(kiosk_id)
        )
        if cached:
            user_coords = cached
            state["user_coords"] = cached

    # If coordinates are not cached, check if operator has ALREADY marked attendance today.
    # On-duty operators submitting periodic/chiller inspection photos inherit verified station location.
    if user_coords is None:
        from apps.temperature_marker.database.db_service import DatabaseService
        db_svc = db_service or DatabaseService.get_instance()
        sender_phone = state.get("sender_phone")
        emp = db_svc.get_employee_by_phone(str(sender_phone)) if sender_phone else None
        emp_code = emp.emp_code if emp else state.get("operator_emp_code", "")
        if emp_code:
            today_att = db_svc.has_attendance_today(emp_code)
            if today_att is not None:
                assigned_kiosk = today_att.kiosk_id or kiosk_id
                kiosk_geo = kg_service.get_kiosk_coordinates(assigned_kiosk)
                if kiosk_geo:
                    user_coords = (kiosk_geo[0], kiosk_geo[1])
                    state["user_coords"] = user_coords
                    state["geofence_verified"] = True
                    state["distance_meters"] = float(getattr(today_att, "gps_distance_meters", 0.0) or 0.0)
                    state["is_duty_checkin"] = False
                    logger.info(
                        "[Geofence] Operator %s (%s) already on duty today at %s — bypassing location prompt for periodic photo.",
                        emp_code, sender_phone, assigned_kiosk,
                    )

    # If Option 4 Web Geolocation link has not yet been clicked
    if user_coords is None:
        state["geofence_verified"] = False
        corr_id = str(state.get("correlation_id", ""))
        sender_phone = state.get("sender_phone")
        if corr_id and sender_phone:
            from core_platform.app.ingress.location_session import bind_session_metadata
            bind_session_metadata(corr_id, {"phone": str(sender_phone), "kiosk_id": kiosk_id})

        from core_platform.app.config import settings
        base_url = settings.ORCHESTRATOR_BASE_URL.rstrip("/") if settings.ORCHESTRATOR_BASE_URL else f"http://localhost:{settings.ORCHESTRATOR_PORT}"
        kiosk_details = kg_service.get_kiosk_details(kiosk_id)
        station_name = kiosk_details.get("name", kiosk_id) if kiosk_details else kiosk_id

        from core_platform.app.ingress.location_session import (
            record_location_prompt,
            should_prompt_location,
        )
        phone_str = str(sender_phone) if sender_phone else ""
        explicit = bool(state.get("explicit_location_request", False))

        if should_prompt_location(phone_str, explicit_request=explicit):
            if phone_str:
                record_location_prompt(phone_str)
            state["reply_message"] = (
                f"📍 Please verify KioskNode location (1-click) for {station_name}: "
                f"{base_url}/loc?session={corr_id}&kiosk_id={kiosk_id}"
            )
        else:
            state["reply_message"] = (
                f"📍 KioskNode location for {station_name} requires verification. "
                "The 'Please verify KioskNode location (1-click)' link was already shared earlier today. "
                "Please tap that link or send 'location' to request a new link."
            )
        return state

    if not kg_service.roster or not kg_service.roster.kiosks:
        # Clean-slate guard (ISSUE-006)
        state["geofence_verified"] = False
        state["layer_0_passed"] = False
        state["error_code"] = PlatformErrorCode.SAFETY_GEOFENCE_VIOLATION.value
        state["error_message"] = "No registered kiosks found in fleet roster."
        state["reply_message"] = "❌ No active kiosks are configured in the system fleet roster. Please contact your administrator."
        return state

    kiosk_geo = kg_service.get_kiosk_coordinates(kiosk_id)
    if not kiosk_geo:
        # Unknown kiosk in registry
        state["geofence_verified"] = False
        state["layer_0_passed"] = False
        state["error_code"] = PlatformErrorCode.SAFETY_GEOFENCE_VIOLATION.value
        state["error_message"] = f"Unknown kiosk identifier: {kiosk_id}"
        state["reply_message"] = f"❌ Unknown kiosk identifier '{kiosk_id}'. Please contact your administrator."
        return state

    kiosk_lat, kiosk_lon, radius_m = kiosk_geo
    geo_skill: GeofencingSkill = get_platform_skill("geofencing")  # type: ignore

    accuracy_val = float(state.get("gps_accuracy_meters") or 0.0)
    is_within, dist = await geo_skill.verify_geofence(
        user_coords=user_coords,
        kiosk_coords=(kiosk_lat, kiosk_lon),
        allowed_radius_meters=radius_m,
        accuracy_meters=accuracy_val,
    )

    state["distance_meters"] = dist
    state["geofence_verified"] = is_within
    logger.info(
        "[Geofence] Kiosk %s: distance=%.1fm, radius=%.0fm, within=%s",
        kiosk_id,
        dist,
        radius_m,
        is_within,
    )

    if not is_within:
        state["layer_0_passed"] = False
        state["error_code"] = PlatformErrorCode.SAFETY_GEOFENCE_VIOLATION.value
        state["error_message"] = (
            f"Location Mismatch: You appear to be {dist:.1f}m away from "
            f"kiosk {kiosk_id}. Permissible limit is {radius_m:.0f}m."
        )
        state["reply_message"] = (
            f"⚠️ Location Mismatch: You appear to be {dist:.1f}m away from "
            f"kiosk {kiosk_id}. Permissible limit is {radius_m:.0f}m."
        )

    return state
