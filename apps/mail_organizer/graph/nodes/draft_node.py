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
Context-Aware Draft Reply Generator Node (`draft_node`).

Adheres strictly to Plan 04 v1.0.
Synthesizes professional, fact-grounded draft replies using calendar context
and ownership roles. Suppresses drafts for OBSERVER_ONLY and promotional mail.
"""

import logging
import time
from typing import Any, Dict, List, Optional, cast
from apps.mail_organizer.graph.state import MailOrganizerState

logger = logging.getLogger("mail_organizer.graph.draft_node")


async def draft_node(state: MailOrganizerState) -> MailOrganizerState:
    """Generate professional draft reply if appropriate."""
    t0 = time.perf_counter()

    category = state.get("category") or "@Action"
    role = state.get("responsibility_role") or "PRIMARY_ACTIONEE"
    is_reply_nec = bool(state.get("is_reply_necessary", True))
    safety_override = bool(state.get("safety_override", False))
    calendar_slots = state.get("calendar_availability")
    sender = state.get("sender") or "Colleague"
    subject = state.get("subject") or ""

    # Extract sender display name
    sender_name = sender.split("<")[0].replace('"', '').strip() if "<" in sender else sender

    # Draft suppression conditions
    if safety_override or role == "OBSERVER_ONLY" or not is_reply_nec or category == "@Promotions":
        state["suggested_reply"] = None
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        trace = list(state.get("pipeline_trace") or [])
        trace.append({
            "node": "generate_draft",
            "duration_ms": duration_ms,
            "draft_generated": False,
            "suppression_reason": f"Role={role}, ReplyNecessary={is_reply_nec}, Category={category}, Override={safety_override}",
        })
        state["pipeline_trace"] = trace
        return state

    body = state.get("body") or ""
    account_holder = state.get("user_name") or state.get("user_email") or "Account Lead"
    draft: Optional[str] = None
    suppression_reason: Optional[str] = None

    try:
        from apps.mail_organizer.services.history_context_service import format_history_for_prompt
        from apps.mail_organizer.services.org_context_service import build_org_context_block
        from core_platform.app.llm.gateway import get_platform_llm_gateway

        thread_hist = cast(List[Dict[str, Any]], state.get("thread_history") or [])
        topic_hist = cast(List[Dict[str, Any]], state.get("topic_history") or [])
        history_block = format_history_for_prompt(thread_hist, topic_hist) if (thread_hist or topic_hist) else ""
        org_block = build_org_context_block(sender, subject, body)

        history_sec = f"{history_block}\n\n" if history_block else ""
        org_sec = f"{org_block}\n\n" if org_block else ""
        cal_ctx = f"Availability to include: {calendar_slots}\n" if calendar_slots else ""

        prompt = (
            f"You are drafting an email reply on behalf of {account_holder}.\n"
            "Synthesize a polite, concise, fact-grounded, professional response addressing the sender's points.\n\n"
            f"{org_sec}"
            f"{history_sec}"
            f"Sender: {sender}\n"
            f"Subject: {subject}\n"
            f"Category: {category}\n"
            f"Email Body:\n{body[:2000]}\n\n"
            f"{cal_ctx}"
            f"Sign off with: Best regards,\n{account_holder}\n\n"
            "Return a JSON object conforming strictly to this format:\n"
            "{\n"
            '  "draft": "concise, professional plain-text response body without markdown or subject lines"\n'
            "}"
        )

        gateway = get_platform_llm_gateway()
        raw_tid = state.get("tenant_id")
        eff_tenant: Optional[str] = str(raw_tid) if raw_tid else None
        res = await gateway.generate(
            task="text_generation",
            prompt=prompt,
            temperature=0.2,
            response_mime_type="application/json",
            operation_id=f"draft_{state.get('gmail_id', 'unknown')}",
            tenant_id=eff_tenant,
            cartridge_id="mail_organizer",
        )
        if res and isinstance(res, dict):
            gen_text = res.get("draft")
            if not gen_text and "raw_text" in res:
                gen_text = res["raw_text"].strip()
            if gen_text:
                draft = gen_text
        if not draft:
            suppression_reason = "LLM returned empty draft payload"
    except Exception as exc:
        logger.warning("[DraftNode] LLM draft generation skipped/failed: %s", exc)
        suppression_reason = f"LLM generation unavailable: {exc}"

    state["suggested_reply"] = draft

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "generate_draft",
        "duration_ms": duration_ms,
        "draft_generated": bool(draft),
        "suppression_reason": suppression_reason,
        "category": category,
    })
    state["pipeline_trace"] = trace

    return state

