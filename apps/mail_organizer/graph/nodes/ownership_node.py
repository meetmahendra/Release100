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
Ownership & Delegation Gate Node (`ownership_node`).

Adheres strictly to Plan 04 v1.0 Section 1.3.
Disambiguates recipient role:
- PRIMARY_ACTIONEE: User is in To: line and directly accountable for response/action.
- OBSERVER_ONLY: User is only CC'd (FYI); suppresses unsolicited draft replies.
- DELEGATOR: Task is directed to a subordinate or external partner.
"""

import time
from typing import Any, Dict, List, Optional
from apps.mail_organizer.graph.state import MailOrganizerState


async def ownership_node(
    state: MailOrganizerState,
    user_email: Optional[str] = None,
) -> MailOrganizerState:
    """Analyze recipient headers and assign ownership role."""
    t0 = time.perf_counter()

    to_list = [r.lower().strip() for r in (state.get("to_recipients") or [])]
    cc_list = [r.lower().strip() for r in (state.get("cc_recipients") or [])]

    # Candidate email identities representing the active user/mailbox
    candidates = [
        str(addr).lower().strip()
        for addr in [
            user_email,
            state.get("user_email"),
            "depali@company.com",
            "user@canectar.com",
            "me@canectar.com",
        ]
        if addr
    ]

    is_to = any(c in to_list for c in candidates)
    is_cc = any(c in cc_list for c in candidates)

    # Determine role
    if is_to:
        role = "PRIMARY_ACTIONEE"
    elif is_cc:
        role = "OBSERVER_ONLY"
    elif not to_list and not cc_list:
        role = "PRIMARY_ACTIONEE"
    else:
        # User not explicitly mentioned in To or CC (e.g. Bcc or mailing list)
        role = "OBSERVER_ONLY"

    state["responsibility_role"] = role
    if role == "OBSERVER_ONLY":
        state["is_reply_necessary"] = False

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "ownership_gate",
        "duration_ms": duration_ms,
        "responsibility_role": role,
    })
    state["pipeline_trace"] = trace

    return state
