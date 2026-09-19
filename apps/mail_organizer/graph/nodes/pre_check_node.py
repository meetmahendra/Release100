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


async def pre_check_node(
    state: MailOrganizerState,
    vip_senders: Optional[List[str]] = None,
    critical_keywords: Optional[List[str]] = None,
) -> MailOrganizerState:
    """Evaluate deterministic pre-execution rules in pure Python (< 2ms)."""
    t0 = time.perf_counter()

    state_vips = state.get("vip_senders") or []
    vips = [v.lower().strip() for v in (vip_senders or state_vips)]
    keywords = [k.lower().strip() for k in (critical_keywords or ["urgent", "escalation", "critical", "sev1", "outage", "hazard"])]

    sender = (state.get("sender") or "").lower()
    subject = (state.get("subject") or "").lower()
    headers = state.get("auto_reply_headers") or {}

    # 1. No-reply detection
    is_no_reply = False
    no_reply_indicators = ["noreply", "no-reply", "mailer-daemon", "notifications@", "donotreply@"]
    if any(ind in sender for ind in no_reply_indicators):
        is_no_reply = True
    elif "auto-submitted" in headers or "list-unsubscribe" in headers:
        is_no_reply = True

    # 2. VIP match
    is_vip = any(vip in sender for vip in vips)

    # 3. Critical subject keyword scan
    has_critical_subject = any(kw in subject for kw in keywords)

    state["is_no_reply"] = is_no_reply
    state["is_vip"] = is_vip
    state["has_critical_subject"] = has_critical_subject

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "pre_check",
        "duration_ms": duration_ms,
        "is_vip": is_vip,
        "is_no_reply": is_no_reply,
        "has_critical_subject": has_critical_subject,
    })
    state["pipeline_trace"] = trace

    return state
