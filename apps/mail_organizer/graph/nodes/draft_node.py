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
import re
import time
from typing import Any, Dict, List, Optional, cast
from apps.mail_organizer.graph.state import MailOrganizerState

logger = logging.getLogger("mail_organizer.graph.draft_node")


def _format_hybrid_context_section(bundle: Dict[str, Any]) -> str:
    """Format Stage A Hybrid Neuro-Symbolic Context Bundle into an explicit citation prompt block."""
    if not bundle:
        return ""
    lines: List[str] = []
    facts = bundle.get("entity_facts") or []
    if facts:
        lines.append("VERIFIED SYMBOLIC ENTITY FACTS (Latest chronologically supersedes older facts):")
        for f in facts:
            ch = str(f.get("source_channel") or "EMAIL").capitalize()
            mid = str(f.get("source_msg_id") or f.get("id") or "1")
            lines.append(
                f"- [{ch} #{mid}] {f.get('subject_entity')} -> {f.get('predicate')}: {f.get('object_value')}"
            )
    commits = bundle.get("open_commitments") or []
    if commits:
        lines.append("ACTIVE COMMITMENTS LEDGER:")
        for c in commits[:4]:
            lines.append(
                f"- [{c.get('direction')}] {c.get('deliverable_summary')} (Due: {c.get('raw_deadline_text')})"
            )
    fts_list = bundle.get("fts_matches") or []
    for m in fts_list[:3]:
        ch = str(m.get("source_channel") or "EMAIL").capitalize()
        mid = str(m.get("msg_id") or "fts")
        lines.append(f"- [{ch} #{mid}] {m.get('subject')}: {m.get('snippet')}")
    return "\n".join(lines)


def _verify_self_critique(
    draft_text: str,
    source_corpus: str,
    preferred_salutation: Optional[str],
) -> Dict[str, Any]:
    """Stage D Self-Critique: verify zero ungrounded currency figures and enforce learned salutation."""
    critique_notes: List[str] = []
    passed = True
    cleaned_draft = draft_text

    # Check currency figures in draft against source corpus
    draft_amounts = re.findall(r"\$\s?\d[\d,]*(?:\.\d{1,2})?", cleaned_draft)
    for amt in draft_amounts:
        norm_amt = amt.replace(" ", "")
        if norm_amt not in source_corpus.replace(" ", ""):
            passed = False
            critique_notes.append(f"Ungrounded currency figure detected and clamped: {amt}")
            cleaned_draft = cleaned_draft.replace(amt, "[PENDING_VERIFIED_AMOUNT]")

    # Enforce learned salutation if available
    if preferred_salutation:
        lines = cleaned_draft.splitlines()
        if lines and lines[0].strip().lower().startswith(("hi ", "hello ", "dear ")):
            lines[0] = f"Hi {preferred_salutation},"
            cleaned_draft = "\n".join(lines)
            critique_notes.append(f"Applied learned salutation: Hi {preferred_salutation},")

    return {
        "passed": passed,
        "cleaned_draft": cleaned_draft,
        "notes": "; ".join(critique_notes) if critique_notes else "All claims grounded in source/context.",
    }


# [CODE-MARKER: MO-TIER2-02] Stage C Citation-Grounded Draft & Stage D Self-Critique
async def draft_node(state: MailOrganizerState) -> MailOrganizerState:
    """Generate citation-grounded draft reply (Stage C) and run self-critique verification (Stage D)."""
    t0 = time.perf_counter()

    category = state.get("category") or "@Action"
    role = state.get("responsibility_role") or "PRIMARY_ACTIONEE"
    is_reply_nec = bool(state.get("is_reply_necessary", True))
    safety_override = bool(state.get("safety_override", False))
    missing_artifact = bool(state.get("missing_artifact_detected", False))
    calendar_slots = state.get("calendar_availability")
    sender = state.get("sender") or "Colleague"
    subject = state.get("subject") or ""
    body = state.get("body") or ""

    # [CODE-MARKER: FIX-ON-DEMAND-DRAFT-19] Self-Sender & FYI/Promotions Draft Suppression Guard
    user_email_val = str(state.get("user_email") or "").lower().strip()
    is_self_sender = bool(user_email_val and user_email_val in sender.lower())
    if is_self_sender or category in ("@Promotions", "@FYI"):
        is_reply_nec = False
        state["is_reply_necessary"] = False

    sender_name = sender.split("<")[0].replace('"', "").strip() if "<" in sender else sender.split("@")[0]
    learned_sals = list(state.get("learned_salutations") or [])
    preferred_sal = learned_sals[0] if learned_sals else sender_name

    # Build infographic card spec for Stage 2 WhatsApp inspection regardless of draft suppression
    bundle = state.get("hybrid_context_bundle") or {}
    facts = bundle.get("entity_facts") or []
    fact_summary = (
        f"{facts[0].get('subject_entity')}: {facts[0].get('predicate')} = {facts[0].get('object_value')}"
        if facts
        else (body.strip().splitlines()[0][:100] if body.strip() else subject)
    )

    # Draft suppression conditions (including Stage B WAITING_FOR_USER_ARTIFACT gate)
    if missing_artifact or safety_override or role == "OBSERVER_ONLY" or not is_reply_nec or category in ("@Promotions", "@FYI"):
        state["suggested_reply"] = None
        state["self_critique_passed"] = not missing_artifact
        state["self_critique_notes"] = (
            "WAITING_FOR_USER_ARTIFACT: Draft paused until missing reference is supplied."
            if missing_artifact
            else ("Self-authored email: draft suppressed." if is_self_sender else "Draft suppressed by role/category guardrail.")
        )
        state["infographic_card_spec"] = {
            "category_badge": category,
            "urgency_score": int(state.get("urgency_score") or 5),
            "sender_title": sender[:48],
            "subject_line": subject[:72],
            "context_synthesis": str(state.get("missing_artifact_description") or fact_summary)[:140],
            "proposed_action": "Awaiting missing artifact/reference from user" if missing_artifact else "No reply required",
            "citation_footer": ", ".join(list(state.get("citation_ids") or [])[:3]) or "Direct Email",
        }
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        trace = list(state.get("pipeline_trace") or [])
        trace.append({
            "node": "generate_draft",
            "duration_ms": duration_ms,
            "draft_generated": False,
            "suppression_reason": (
                "WAITING_FOR_USER_ARTIFACT"
                if missing_artifact
                else f"Role={role}, ReplyNecessary={is_reply_nec}, Category={category}, SelfSender={is_self_sender}, Override={safety_override}"
            ),
        })
        state["pipeline_trace"] = trace
        return state

    account_holder = state.get("user_name") or state.get("user_email") or "Account Lead"
    draft: Optional[str] = None
    suppression_reason: Optional[str] = None
    hybrid_sec = _format_hybrid_context_section(bundle)

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
        hybrid_prompt_sec = f"{hybrid_sec}\n\n" if hybrid_sec else ""
        cal_ctx = f"Availability to include: {calendar_slots}\n" if calendar_slots else ""

        prompt = (
            f"You are drafting an email reply on behalf of {account_holder}.\n"
            f"Open with the salutation: 'Hi {preferred_sal},'\n"
            "Synthesize a polite, concise, fact-grounded, professional response addressing the sender's points.\n"
            "If you use facts from VERIFIED SYMBOLIC ENTITY FACTS, cite the source tag (e.g. [Whatsapp #wa-1]).\n"
            "NEVER invent numbers, dates, or commitments not present in the email or verified facts.\n\n"
            f"{org_sec}"
            f"{history_sec}"
            f"{hybrid_prompt_sec}"
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
            temperature=0.1,
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
                draft = str(gen_text)
    except Exception as exc:
        logger.warning("[DraftNode] LLM draft generation skipped/failed: %s", exc)
        suppression_reason = f"LLM generation unavailable: {exc}"

    # Grounded Deterministic Fallback when offline or without live LLM key
    if not draft:
        cite_clause = ""
        if facts:
            top_f = facts[0]
            ch = str(top_f.get("source_channel") or "EMAIL").capitalize()
            mid = str(top_f.get("source_msg_id") or top_f.get("id") or "1")
            cite_clause = (
                f" Regarding {top_f.get('subject_entity')}, per our latest update [{ch} #{mid}], "
                f"{top_f.get('predicate')} is confirmed as {top_f.get('object_value')}."
            )
        cal_clause = f" For scheduling, my available slots are: {calendar_slots}." if calendar_slots else ""
        draft = (
            f"Hi {preferred_sal},\n\n"
            f"Thank you for your note regarding '{subject}'.{cite_clause}{cal_clause} "
            "I have reviewed the details and will follow up on the action items promptly.\n\n"
            f"Best regards,\n{account_holder}"
        )

    # Stage D: Self-Critique Hallucination & Salutation Verification
    source_corpus = f"{subject}\n{body}\n{hybrid_sec}\n{calendar_slots or ''}"
    critique = _verify_self_critique(
        draft_text=draft,
        source_corpus=source_corpus,
        preferred_salutation=learned_sals[0] if learned_sals else None,
    )
    draft = str(critique["cleaned_draft"])
    state["self_critique_passed"] = bool(critique["passed"])
    state["self_critique_notes"] = str(critique["notes"])
    state["suggested_reply"] = draft

    state["infographic_card_spec"] = {
        "category_badge": category,
        "urgency_score": int(state.get("urgency_score") or 5),
        "sender_title": sender[:48],
        "subject_line": subject[:72],
        "context_synthesis": fact_summary[:140],
        "proposed_action": draft.splitlines()[2][:120] if len(draft.splitlines()) > 2 else draft[:120],
        "citation_footer": ", ".join(list(state.get("citation_ids") or [])[:3]) or "Direct Email",
    }

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "generate_draft",
        "duration_ms": duration_ms,
        "draft_generated": bool(draft),
        "self_critique_passed": state["self_critique_passed"],
        "suppression_reason": suppression_reason,
        "category": category,
    })
    state["pipeline_trace"] = trace

    return state


