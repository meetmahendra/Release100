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

import time
from typing import Any, Dict, List, Optional, cast
from apps.mail_organizer.graph.state import MailOrganizerState


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

    # Synthesize context-aware draft
    if category == "@Meeting" and calendar_slots:
        draft = (
            f"Hi {sender_name},\n\n"
            f"Thank you for reaching out regarding '{subject}'.\n\n"
            f"{calendar_slots}\n\n"
            "Looking forward to connecting.\n\n"
            "Best regards,\nMahendra Gurav"
        )
    elif category == "@Urgent":
        draft = (
            f"Hi {sender_name},\n\n"
            f"Acknowledging receipt of this urgent escalation regarding '{subject}'.\n\n"
            "I have prioritized this with the on-duty fleet operations team and will provide an updated status within the hour.\n\n"
            "Best regards,\nMahendra Gurav"
        )
    elif category == "@Financial":
        draft = (
            f"Hi {sender_name},\n\n"
            f"Thank you for transmitting the documentation regarding '{subject}'.\n\n"
            "I have forwarded this to our finance desk for verification and remittance processing.\n\n"
            "Best regards,\nMahendra Gurav"
        )
    else:
        draft = (
            f"Hi {sender_name},\n\n"
            f"Thank you for your note regarding '{subject}'.\n\n"
            "I am reviewing the deliverables requested and will follow up shortly with details.\n\n"
            "Best regards,\nMahendra Gurav"
        )

    body = state.get("body") or ""
    # If live Gemini API key is configured, enhance draft with LLM generation
    from core_platform.app.config import settings
    if settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("your_"):
        try:
            import json
            import urllib.request
            from apps.mail_organizer.services.history_context_service import format_history_for_prompt
            from apps.mail_organizer.services.org_context_service import build_org_context_block

            thread_hist = cast(List[Dict[str, Any]], state.get("thread_history") or [])
            topic_hist = cast(List[Dict[str, Any]], state.get("topic_history") or [])
            history_block = format_history_for_prompt(thread_hist, topic_hist) if (thread_hist or topic_hist) else ""
            org_block = build_org_context_block(sender, subject, body)

            history_sec = f"{history_block}\n\n" if history_block else ""
            org_sec = f"{org_block}\n\n" if org_block else ""
            cal_ctx = f"Availability to include: {calendar_slots}\n" if calendar_slots else ""

            prompt = (
                "You are drafting an email reply on behalf of Mahendra Gurav (VP Operations & Executive Lead).\n"
                "Synthesize a polite, concise, fact-grounded, professional response addressing the sender's points.\n\n"
                f"{org_sec}"
                f"{history_sec}"
                f"Sender: {sender}\n"
                f"Subject: {subject}\n"
                f"Category: {category}\n"
                f"Email Body:\n{body[:2000]}\n\n"
                f"{cal_ctx}"
                "Return ONLY the plain-text draft body without markdown formatting or subject lines."
            )
            model_name = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 400, "temperature": 0.2},
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                if resp.status == 200:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    gen_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if gen_text:
                        draft = gen_text
        except Exception:
            pass

    state["suggested_reply"] = draft

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "generate_draft",
        "duration_ms": duration_ms,
        "draft_generated": True,
        "category": category,
    })
    state["pipeline_trace"] = trace

    return state
