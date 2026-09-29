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

"""Outbound WhatsApp Notification Composer Node."""

import asyncio

from apps.temperature_marker.graph.state import TemperatureMarkerState


async def reply_node(state: TemperatureMarkerState) -> TemperatureMarkerState:
    """Compose user-friendly WhatsApp response message."""
    # If a previous node already prepared an error or warning message
    if state.get("reply_message"):
        return state

    emp_name = state.get("operator_name", "Operator")
    emp_code = state.get("operator_emp_code", "")
    kiosk_id = state.get("kiosk_id", "CaneBot")
    temp_c = state.get("chiller_temp_c")
    dist_m = state.get("distance_meters", 0.0)
    seq_num = state.get("audit_sequence_number", 1)
    rec_hash = state.get("audit_record_hash", "")
    hash_short = f"{rec_hash[:8]}..." if rec_hash else "LOGGED"
    haccp_status = state.get("haccp_status", "SAFE_RANGE")
    ocr_conf = float(state.get("ocr_confidence") or 0.0)
    layer_2_disp = state.get("layer_2_disposition", "")
    haccp_comp = state.get("haccp_compliant", False)

    from apps.temperature_marker.services.alert_dispatcher import dispatch_critical_hazard_alert

    if haccp_status == "CRITICAL_HAZARD" and temp_c is not None:
        asyncio.create_task(
            dispatch_critical_hazard_alert(
                kiosk_id=kiosk_id,
                operator_name=emp_name,
                alert_type="HACCP Critical Spoilage",
                details=f"Chiller reading {temp_c:.1f}°C exceeds safe 7.0°C limit!",
            )
        )
        state["reply_message"] = (
            f"🚨 CRITICAL CHILLER WARNING! 🚨\n"
            f"Machine: {kiosk_id}\n"
            f"Chiller Temperature: {temp_c:.1f}°C (Exceeds critical limit 7.0°C!)\n"
            f"Fresh sugarcane juice spoilage hazard. Kiosk Supervisor has been notified immediately.\n"
            f"🔒 Audit Trail: #{seq_num} ({hash_short})"
        )
    elif haccp_status == "FREEZING_HAZARD" and temp_c is not None:
        asyncio.create_task(
            dispatch_critical_hazard_alert(
                kiosk_id=kiosk_id,
                operator_name=emp_name,
                alert_type="HACCP Freezing Hazard",
                details=f"Chiller reading {temp_c:.1f}°C is at or below freezing!",
            )
        )
        state["reply_message"] = (
            f"❄️ CRITICAL FREEZING WARNING! ❄️\n"
            f"Machine: {kiosk_id}\n"
            f"Chiller Temperature: {temp_c:.1f}°C (Freezing hazard at/below 0.0°C!)\n"
            f"Juice line freezing and pump damage risk. Please inspect dispenser thermostat.\n"
            f"🔒 Audit Trail: #{seq_num} ({hash_short})"
        )
    elif haccp_status == "BORDERLINE_ELEVATED" and temp_c is not None:
        state["reply_message"] = (
            f"⚠️ CHILLER TEMPERATURE ALERT ⚠️\n"
            f"Machine: {kiosk_id}\n"
            f"Reading: {temp_c:.1f}°C (Outside safe window 2.0°C – 4.0°C)\n"
            f"Please adjust chiller thermostat and monitor temperature.\n"
            f"🔒 Audit Trail: #{seq_num} ({hash_short})"
        )
    elif state.get("is_duty_checkin") and temp_c is None:
        state["reply_message"] = (
            f"✅ Shift Attendance Marked!\n"
            f"👤 Operator: {emp_name} ({emp_code})\n"
            f"📍 Kiosk: {kiosk_id} ({dist_m:.1f}m away)\n\n"
            f"📸 Next: Chiller temperature reading pending.\n"
            f"👉 Please take a clear close-up photo of the chiller digital LED/LCD display and send it to log today's temperature.\n\n"
            f"🔒 Audit Trail: #{seq_num} ({hash_short})"
        )
    elif temp_c is None or ocr_conf < 0.85 or layer_2_disp == "diverted_to_review":
        state["reply_message"] = (
            f"⚠️ Chiller Display Unreadable\n"
            f"👤 Operator: {emp_name} ({emp_code})\n"
            f"📍 Kiosk: {kiosk_id} ({dist_m:.1f}m away)\n\n"
            f"📸 The digital temperature readout could not be clearly detected in your photo.\n"
            f"👉 Please take a clear, close-up photo of the chiller digital LED/LCD display (avoid glare on digits) and send it.\n\n"
            f"🔒 Record Routed to Supervisor Review: #{seq_num} ({hash_short})"
        )
    elif haccp_comp and temp_c is not None:
        is_duty = state.get("is_duty_checkin", True)
        header = "✅ Duty Marked & Chiller Verified!" if is_duty else "✅ Chiller Verified (Periodic Log)"
        state["reply_message"] = (
            f"{header}\n"
            f"👤 Operator: {emp_name} ({emp_code})\n"
            f"📍 Kiosk: {kiosk_id} ({dist_m:.1f}m away)\n"
            f"🧊 Chiller Temp: {temp_c:.1f}°C [Safe: 2.0°C-4.0°C]\n"
            f"🔒 Non-Repudiation Audit: #{seq_num} ({hash_short})"
        )
    else:
        state["reply_message"] = (
            f"ℹ️ Attendance Logged\n"
            f"👤 Operator: {emp_name} ({emp_code})\n"
            f"📍 Kiosk: {kiosk_id} ({dist_m:.1f}m away)\n"
            f"🔒 Non-Repudiation Audit: #{seq_num} ({hash_short})"
        )

    return state
