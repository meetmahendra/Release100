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

"""Layer 0 Operator Authentication Guard Node."""

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.errors import PlatformErrorCode


async def layer0_auth_guard_node(
    state: TemperatureMarkerState,
    db_service: DatabaseService,
) -> TemperatureMarkerState:
    """Verify operator phone is registered and active in local database."""
    phone = state.get("sender_phone", "")
    employee = db_service.get_employee_by_phone(phone)

    if not employee:
        state["operator_status"] = "UNREGISTERED"
        state["layer_0_passed"] = False
        state["error_code"] = PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
        state["error_message"] = f"Phone number {phone} is not registered."
        state["reply_message"] = (
            f"❌ Unauthorized: Phone number {phone} is not registered. "
            "Reply 'register <EMP-CODE> <Full Name>' or contact your supervisor to enroll."
        )
        return state

    if employee.status != "ACTIVE":
        state["operator_status"] = employee.status
        state["layer_0_passed"] = False
        state["error_code"] = PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
        state["error_message"] = f"Operator {employee.full_name} ({employee.emp_code}) is currently '{employee.status}'."
        state["reply_message"] = (
            f"⚠️ Operator {employee.full_name} ({employee.emp_code}) is currently "
            f"'{employee.status}'. Awaiting Admin Approval."
        )
        return state

    state["operator_emp_code"] = employee.emp_code
    state["operator_name"] = employee.full_name
    state["operator_status"] = "ACTIVE"
    state["kiosk_id"] = state.get("kiosk_id") or employee.assigned_kiosk_id
    state["layer_0_passed"] = True
    return state
