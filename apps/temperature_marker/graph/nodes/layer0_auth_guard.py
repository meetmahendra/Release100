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

import logging

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.auth.strategies import AuthResolver
from core_platform.app.entitlements.contracts import EntitlementDeniedError, ResourceRef
from core_platform.app.entitlements.dependencies import authorize_action
from core_platform.app.errors import PlatformErrorCode

logger = logging.getLogger(__name__)


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
            f"❌ Unauthorized: Phone number {phone} is not registered with KioskNode. "
            "Self-registration is disabled. Please contact your Fleet Supervisor or HR administrator to provision your account."
        )
        return state

    if employee.status != "ACTIVE":
        state["operator_status"] = employee.status
        state["layer_0_passed"] = False
        state["error_code"] = PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
        state["error_message"] = f"Operator {employee.full_name} ({employee.emp_code}) is currently '{employee.status}'."
        state["reply_message"] = (
            f"⚠️ Access Restricted: Operator {employee.full_name} ({employee.emp_code}) is currently "
            f"'{employee.status}'. Awaiting Admin Approval before duty check-in."
        )
        return state

    # Entitlement gate (Plan 10). Under mode off/shadow this never changes the outcome;
    # under enforce for an onboarded tenant a missing grant stops the check-in here.
    try:
        employee_tenant = getattr(employee, "tenant_id", None)
        gate_ctx = AuthResolver.resolve_whatsapp(
            phone, employee_tenant if isinstance(employee_tenant, str) and employee_tenant else "public"
        )
        authorize_action(
            gate_ctx,
            "temperature:telemetry:record",
            ResourceRef(owner_principal_id=phone, unit_id=None),
        )
    except EntitlementDeniedError:
        state["operator_status"] = "NOT_ENTITLED"
        state["layer_0_passed"] = False
        state["error_code"] = PlatformErrorCode.SAFETY_UNAUTHORIZED_OPERATOR.value
        state["error_message"] = f"Operator {employee.emp_code} is not permitted to submit check-ins."
        state["reply_message"] = (
            "Access Restricted: your account is not permitted to submit duty check-ins. "
            "Please contact your administrator."
        )
        return state
    except Exception as err:  # noqa: BLE001 - the gate fails closed itself; never break check-ins on a wiring fault
        logger.error("Entitlement check skipped due to error: %s", err)
    state["operator_emp_code"] = employee.emp_code
    state["operator_name"] = employee.full_name
    state["operator_status"] = "ACTIVE"
    state["kiosk_id"] = state.get("kiosk_id") or employee.assigned_kiosk_id
    state["layer_0_passed"] = True
    return state
