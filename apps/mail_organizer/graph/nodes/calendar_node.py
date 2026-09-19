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

"""
Google Calendar Free/Busy Slot Enrichment Node (`calendar_node`).

Adheres strictly to Plan 04 v1.0 Section 5.2.
Queries Google Calendar to discover open 30-min and 60-min meeting slots
within business hours (09:00-17:00) and injects natural language proposals.
"""

import time
from typing import Any, Dict, Optional

from apps.mail_organizer.connectors.calendar_connector import GoogleCalendarConnector
from apps.mail_organizer.graph.state import MailOrganizerState


async def calendar_node(
    state: MailOrganizerState,
    calendar_connector: Optional[GoogleCalendarConnector] = None,
) -> MailOrganizerState:
    """Enrich meeting requests with real-time schedule availability."""
    t0 = time.perf_counter()
    connector = calendar_connector or GoogleCalendarConnector()

    is_meeting = bool(state.get("is_scheduling_request", False) or state.get("category") == "@Meeting")

    if is_meeting:
        availability = await connector.synthesize_availability_proposal()
        state["calendar_availability"] = availability
    else:
        state["calendar_availability"] = None

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "calendar_enrich",
        "duration_ms": duration_ms,
        "is_meeting": is_meeting,
        "availability_injected": bool(state.get("calendar_availability")),
    })
    state["pipeline_trace"] = trace

    return state
