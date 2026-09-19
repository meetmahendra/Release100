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
Action Planning Node (`action_planner_node`).

Adheres strictly to Plan 04 v1.0 and the Zero-Deletion Policy.
Formulates the concrete action manifest (labels, draft creation, PM tasks)
without executing destructive operations.
"""

import time
from typing import Any, Dict, List
from apps.mail_organizer.graph.state import MailOrganizerState


async def action_planner_node(state: MailOrganizerState) -> MailOrganizerState:
    """Plan Gmail labels, draft creations, and PM queue items."""
    t0 = time.perf_counter()

    category = state.get("category") or "@Action"
    is_vip = bool(state.get("is_vip", False))
    safety_override = bool(state.get("safety_override", False))
    suggested_reply = state.get("suggested_reply")
    pm_tasks = list(state.get("pending_pm_tasks") or [])
    sender = state.get("sender") or ""

    actions: List[Dict[str, Any]] = list(state.get("gmail_actions") or [])

    # 1. Zero-Deletion Category Labeling
    if category == "@Promotions":
        # Strip from INBOX and assign promotions label so it remains searchable
        actions.append({"action": "remove_label", "label": "INBOX"})
        actions.append({"action": "apply_label", "label": "_LLM/Promotions"})
    elif category:
        actions.append({"action": "apply_label", "label": category})

    # 2. VIP Labeling
    if is_vip:
        actions.append({"action": "apply_label", "label": "VIP"})

    # 3. Draft reply staging
    if suggested_reply and not safety_override:
        actions.append({
            "action": "create_draft",
            "recipient": sender,
            "body": suggested_reply,
        })

    # 4. PM Deliverables queueing
    if pm_tasks:
        actions.append({
            "action": "queue_pm_tasks",
            "count": len(pm_tasks),
        })

    state["gmail_actions"] = actions

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "action_planner",
        "duration_ms": duration_ms,
        "actions_planned_count": len(actions),
    })
    state["pipeline_trace"] = trace

    return state
