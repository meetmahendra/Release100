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


# [CODE-MARKER: MO-TIER0-01] 4-State Header Recipient Role & Dynamic Vocative Ownership
async def ownership_node(
    state: MailOrganizerState,
    user_email: Optional[str] = None,
) -> MailOrganizerState:
    """Analyze RFC To/Cc/List headers and assign 4-state header_recipient_role."""
    t0 = time.perf_counter()

    to_list = [r.lower().strip() for r in (state.get("to_recipients") or []) if r and r.strip()]
    cc_list = [r.lower().strip() for r in (state.get("cc_recipients") or []) if r and r.strip()]
    has_list_unsub = bool(state.get("has_list_unsubscribe"))

    candidates = [
        str(addr).lower().strip()
        for addr in [
            user_email,
            state.get("user_email"),
            "user@company.com",
            "user@apex.com",
            "me@apex.com",
        ]
        if addr
    ]

    is_to = any(any(c in recip for c in candidates) for recip in to_list)
    is_cc = any(any(c in recip for c in candidates) for recip in cc_list)

    if has_list_unsub:
        header_role = "MAILING_LIST"
    elif is_to:
        header_role = "PRIMARY_ACTIONEE" if len(to_list) == 1 else "CO_ACTIONEE"
    elif is_cc:
        header_role = "OBSERVER_CC"
    elif not to_list and not cc_list:
        header_role = "PRIMARY_ACTIONEE"
    else:
        header_role = "MAILING_LIST"

    state["header_recipient_role"] = header_role
    state["was_promoted_from_cc"] = bool(state.get("was_promoted_from_cc", False))

    # Map to responsibility_role (may be promoted from OBSERVER_CC/CO_ACTIONEE by Jev Vocative Ownership in classify_node)
    if state["was_promoted_from_cc"] or header_role in ("PRIMARY_ACTIONEE", "CO_ACTIONEE"):
        role = "PRIMARY_ACTIONEE"
    else:
        role = "OBSERVER_ONLY"

    # [CODE-MARKER: FIX-ON-DEMAND-DRAFT-19] Self-Sender Guard: suppress self-reply when sender matches user_email
    sender_lower = str(state.get("sender") or "").lower().strip()
    self_emails = [
        str(addr).lower().strip()
        for addr in [user_email, state.get("user_email")]
        if addr and str(addr).strip()
    ]
    is_self_sender = bool(self_emails and any(se in sender_lower for se in self_emails))

    state["responsibility_role"] = role
    if role == "OBSERVER_ONLY" or is_self_sender:
        state["is_reply_necessary"] = False

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "ownership_gate",
        "duration_ms": duration_ms,
        "header_recipient_role": header_role,
        "responsibility_role": role,
        "was_promoted_from_cc": state["was_promoted_from_cc"],
        "self_sender_suppressed": is_self_sender,
    })
    state["pipeline_trace"] = trace

    return state

