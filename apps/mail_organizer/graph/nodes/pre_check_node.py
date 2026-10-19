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
Layer 0 Deterministic Pre-Execution Gate (`pre_check_node`).

Adheres strictly to GEES v1.0 (Layer 0) and Plan 04 v1.0 Section 3.
Executes hardcoded boundary and whitelist checks before any model invocation:
1. No-reply header & sender pattern detection.
2. VIP sender whitelist matching.
3. Emergency keyword scanning in subject lines.
"""

import time
from typing import Any, Dict, List, Optional
from apps.mail_organizer.graph.state import MailOrganizerState


# [CODE-MARKER: MO-TIER0-01] Tier 0 Deterministic RFC Header & ContactEntity Gate
async def pre_check_node(
    state: MailOrganizerState,
    vip_senders: Optional[List[str]] = None,
    critical_keywords: Optional[List[str]] = None,
    db_service: Optional[Any] = None,
) -> MailOrganizerState:
    """Evaluate deterministic RFC 5322/3834 headers and ContactEntity VIP status (< 2ms)."""
    t0 = time.perf_counter()

    sender = (state.get("sender") or "").strip()
    sender_lower = sender.lower()
    subject_lower = (state.get("subject") or "").lower()
    raw_headers = {
        str(k).lower(): str(v).lower()
        for k, v in {**(state.get("auto_reply_headers") or {}), **(state.get("rfc_headers") or {})}.items()
    }

    body_lower = (state.get("body") or "").lower()
    has_list_unsub = "list-unsubscribe" in raw_headers or "list-id" in raw_headers
    auto_submitted = raw_headers.get("auto-submitted", "no")
    precedence = raw_headers.get("precedence", "")
    is_auto_reply = (
        (auto_submitted != "no" and bool(auto_submitted))
        or precedence in ("bulk", "junk", "auto_reply")
        or "x-auto-response-suppress" in raw_headers
        or raw_headers.get("return-path") == "<>"
        or subject_lower.startswith(("automatic reply:", "out of office:", "autoreply:", "ooo:", "auto-reply:"))
        or any(
            phrase in body_lower
            for phrase in (
                "i am currently out of the office",
                "i am on annual leave",
                "i am out of office until",
                "i am away from the office",
                "i will have limited access to email",
            )
        )
    )
    is_no_reply = (
        has_list_unsub
        or is_auto_reply
        or any(tok in sender_lower for tok in ("noreply", "no-reply", "mailer-daemon", "notifications@", "donotreply@"))
    )

    state_vips = [v.lower().strip() for v in (vip_senders or state.get("vip_senders") or [])]
    is_vip = any(v in sender_lower for v in state_vips if v)

    if db_service is not None and sender:
        resolved = db_service.resolve_contact_alias_3layer(
            tenant_id=str(state.get("tenant_id") or "public"),
            user_id=state.get("user_id"),
            channel_type="EMAIL",
            raw_identifier=sender,
            is_vip=is_vip,
        )
        state["resolved_contact_id"] = resolved.get("contact_id")
        state["contact_resolution_layer"] = str(resolved.get("resolution_layer", "LAYER_1_EXACT"))
        state["contact_resolution_status"] = str(resolved.get("resolution_status", "VERIFIED"))
        state["learned_salutations"] = list(resolved.get("learned_salutations") or [])
        is_vip = is_vip or bool(resolved.get("is_vip"))

    kw_list = [k.lower().strip() for k in (critical_keywords or ["urgent", "escalation", "critical", "sev1", "outage", "hazard"])]
    state["has_list_unsubscribe"] = has_list_unsub
    state["is_no_reply"] = is_no_reply
    state["is_auto_reply"] = is_auto_reply
    state["is_vip"] = is_vip
    state["has_critical_subject"] = any(kw in subject_lower for kw in kw_list)

    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "pre_check",
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "is_vip": is_vip,
        "is_no_reply": is_no_reply,
        "has_list_unsubscribe": has_list_unsub,
        "has_critical_subject": state["has_critical_subject"],
    })
    state["pipeline_trace"] = trace
    return state

