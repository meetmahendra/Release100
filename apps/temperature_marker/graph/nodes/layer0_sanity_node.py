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

"""Layer 0 Physical Temperature Bounds Sanity Node."""

from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.errors import PlatformErrorCode, SafetyGateViolation
from core_platform.app.safety.layer0_pre_gate import Layer0PreExecutionGate


async def layer0_sanity_node(state: TemperatureMarkerState) -> TemperatureMarkerState:
    """Validate that extracted temperature does not violate physical reality."""
    temp_c = state.get("chiller_temp_c")
    if temp_c is None:
        # Temperature display missing/unreadable; downstream HACCP node will flag READING_UNAVAILABLE
        return state

    try:
        Layer0PreExecutionGate.validate_physical_temperature_bounds(
            temperature_c=temp_c,
            min_physical=-20.0,
            max_physical=120.0,
        )
    except SafetyGateViolation as exc:
        state["layer_0_passed"] = False
        state["error_code"] = PlatformErrorCode.SAFETY_PHYSICAL_BOUND_VIOLATION.value
        state["error_message"] = str(exc)
        state["reply_message"] = (
            f"❌ Sensor Reading Corrupted: Extracted temperature {temp_c}°C violates "
            "physical limits. Please retake photo clearly."
        )

    return state
