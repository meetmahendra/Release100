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

"""HACCP Food Cold-Chain Safety Evaluation Node."""

from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService


async def haccp_node(
    state: TemperatureMarkerState,
    kg_service: KnowledgeGraphService,
) -> TemperatureMarkerState:
    """Evaluate KioskNode juice chiller temperature against HACCP safety thresholds."""
    temp_c = state.get("chiller_temp_c")
    kiosk_id = state.get("kiosk_id")
    haccp_rule = kg_service.get_haccp_limits(kiosk_id)

    if temp_c is None:
        state["haccp_status"] = "PENDING_CHILLER_PHOTO" if state.get("is_duty_checkin") else "READING_UNAVAILABLE"
        state["haccp_compliant"] = False
        if not (state.get("is_duty_checkin") and state.get("face_confidence", 0.0) >= 0.82):
            state["layer_2_disposition"] = "diverted_to_review"
    elif haccp_rule.min_safe_temp <= temp_c <= haccp_rule.max_safe_temp:
        state["haccp_status"] = "SAFE_RANGE"
        state["haccp_compliant"] = True
    elif temp_c > haccp_rule.critical_alert_temp:
        state["haccp_status"] = "CRITICAL_HAZARD"
        state["haccp_compliant"] = False
    elif temp_c <= 0.0:
        state["haccp_status"] = "FREEZING_HAZARD"
        state["haccp_compliant"] = False
    else:
        # Acceptable operating range before reaching critical threshold (4.1°C to 7.0°C)
        state["haccp_status"] = "ACCEPTABLE_RANGE"
        state["haccp_compliant"] = True

    return state
