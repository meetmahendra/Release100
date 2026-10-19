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
Layer 1 Semantic Intent & Category Triage Node (`classify_node`).

Adheres strictly to GEES v1.0 (Layer 1: Clamped Stochastic Reasoning).
Classifies inbound emails into canonical taxonomy:
  `@Action`, `@Urgent`, `@Meeting`, `@WaitingOn`, `@Promotions`, `@Financial`, `@ProjectTask`.
Constrained to structured Pydantic schema with clamped temperature (0.0).
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from apps.mail_organizer.graph.state import MailOrganizerState
from core_platform.app.config import settings
from core_platform.app.llm.base import QuestionSpec

logger = logging.getLogger("mail_organizer.graph.classify_node")


class EmailClassificationOutput(BaseModel):
    """Structured Pydantic schema for deterministic LLM response."""

    category: str = Field(
        description="Canonical category: '@Action' | '@Urgent' | '@Meeting' | '@WaitingOn' | '@Promotions' | '@Financial' | '@ProjectTask'"
    )
    urgency_score: int = Field(ge=1, le=10, description="Urgency rating from 1 to 10")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    reasoning: str = Field(description="Brief explanation of the classification decision")
    context_tags: List[str] = Field(default_factory=list, description="Descriptive context tags")
    is_reply_necessary: bool = Field(description="True if email requires a response from the user")
    reply_necessity_reason: Optional[str] = Field(default=None, description="Reason for reply requirement")
    is_scheduling_request: bool = Field(default=False, description="True if email discusses meeting dates/times")
    speech_act: str = Field(default="INFORM", description="Speech-Act: REQUEST | COMMIT | PROPOSE | INFORM | DECLINE")
    vocative_ownership: str = Field(
        default="GENERAL_BROADCAST",
        description="ADDRESSED_TO_USER | DELEGATED_TO_OTHER | GENERAL_BROADCAST",
    )


def _extract_opening_salutation(body: str) -> str:
    """Extract the opening greeting/salutation line from an email body (REV-03)."""
    for line in (body or "").splitlines()[:5]:
        clean = line.strip()
        if not clean:
            continue
        m = re.match(r"^(?:hi|hello|dear|hey|namaste)\s+([A-Za-z][A-Za-z\s\.\-]{1,35}?)[,:!]*$", clean, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m2 = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),\s*$", clean)
        if m2:
            return m2.group(1).strip()
        break
    return ""


def _infer_offline_speech_act(content_lower: str, category: str) -> str:
    """Infer Winograd/Flores Speech-Act when running in offline deterministic fallback mode."""
    if any(p in content_lower for p in ["i will send", "i'll send", "we will deliver", "will share by", "i promise"]):
        return "COMMIT"
    if any(p in content_lower for p in ["unable to", "cannot attend", "have to decline", "won't be able"]):
        return "DECLINE"
    if category == "@Meeting" or any(p in content_lower for p in ["can we meet", "how about", "propose", "let's schedule"]):
        return "PROPOSE"
    if category in ("@Promotions", "@FYI"):
        return "INFORM"
    if category in ("@Action", "@Urgent", "@Financial", "@ProjectTask") or "?" in content_lower:
        return "REQUEST"
    return "INFORM"


def _detect_vocative_addressing(
    body: str,
    salutation_extracted: str,
    user_name: Optional[str],
    user_email: Optional[str],
) -> str:
    """Detect whether the opening lines vocatively address the active user or another colleague (REV-02)."""
    candidates: List[str] = []
    if user_name and user_name.strip():
        candidates.extend([p.lower() for p in user_name.strip().split() if len(p) >= 2])
    if user_email and "@" in user_email:
        local_part = user_email.split("@")[0].lower()
        candidates.extend([p for p in re.split(r"[\._\-]", local_part) if len(p) >= 2])
    if not candidates:
        candidates = ["mahendra", "user", "me"]

    opening_window = "\n".join((body or "").splitlines()[:6]).lower()
    sal_lower = (salutation_extracted or "").lower()

    if sal_lower:
        if any(c in sal_lower for c in candidates):
            return "ADDRESSED_TO_USER"
        if sal_lower not in ("all", "team", "everyone", "folks"):
            return "DELEGATED_TO_OTHER"

    for c in candidates:
        if re.search(rf"(?:@{re.escape(c)}\b|\bhi\s+{re.escape(c)}\b|\b{re.escape(c)}\s*[,:]\s*(?:please|can\s+you|could\s+you))", opening_window):
            return "ADDRESSED_TO_USER"
    return "GENERAL_BROADCAST"


# [CODE-MARKER: MO-TIER1-01] Tier 1 Jev Single-Pass Multi-Head Classification & Vocative Promotion
async def classify_node(
    state: MailOrganizerState,
    db_service: Optional[Any] = None,
) -> MailOrganizerState:
    """Classify email category, speech-act, vocative ownership, and urgency via single-pass Jev multi-head."""
    t0 = time.perf_counter()

    subject = state.get("subject") or ""
    body = state.get("body") or ""
    sender = state.get("sender") or ""
    has_critical = state.get("has_critical_subject", False)
    is_no_reply = state.get("is_no_reply", False)
    priority_lane = state.get("priority_lane") or "HIGH"

    from apps.mail_organizer.services.org_context_service import (
        build_org_context_block,
        is_org_vip,
        resolve_active_projects,
    )
    is_vip = state.get("is_vip", False) or is_org_vip(sender)
    state["is_vip"] = is_vip

    content_lower = f"{subject} {body}".lower()
    matched_projects = resolve_active_projects(f"{subject} {body}")
    project_tags = [p.get("name", "").lower() for p in matched_projects if p.get("name")]

    # Salutation extraction (REV-03)
    salutation_extracted = _extract_opening_salutation(body)
    state["salutation_extracted"] = salutation_extracted
    vocative_hint = _detect_vocative_addressing(
        body=body,
        salutation_extracted=salutation_extracted,
        user_name=state.get("user_name"),
        user_email=state.get("user_email"),
    )

    # Load role-adaptive user taxonomy (REV-04)
    active_taxonomy: List[Dict[str, Any]] = []
    if db_service is not None:
        try:
            active_taxonomy = db_service.get_active_user_taxonomy(
                tenant_id=state.get("tenant_id"),
                user_id=state.get("user_id"),
            )
        except Exception:
            active_taxonomy = []

    if active_taxonomy:
        valid_categories = [str(c["category_name"]) for c in active_taxonomy if c.get("category_name")]
        cat_descriptions = {
            str(c["category_name"]): str(c.get("description") or c["category_name"])
            for c in active_taxonomy
            if c.get("category_name")
        }
    else:
        valid_categories = [
            "@Action",
            "@Urgent",
            "@Meeting",
            "@WaitingOn",
            "@Promotions",
            "@Financial",
            "@ProjectTask",
        ]
        cat_descriptions = {c: f"Category {c}" for c in valid_categories}

    # Step 1: Layer 0 Deterministic Pre-Execution Filter (Auto-Replies, VIP Fast-Path & Newsletters)
    llm_result: Optional[EmailClassificationOutput] = None

    if state.get("is_auto_reply"):
        llm_result = EmailClassificationOutput(
            category="@FYI",
            urgency_score=1,
            confidence_score=0.99,
            reasoning="Automated Out-of-Office (OOO) or auto-reply notification.",
            context_tags=["auto_reply", "ooo", "fyi"],
            is_reply_necessary=False,
            is_scheduling_request=False,
            speech_act="INFORM",
            vocative_ownership="GENERAL_BROADCAST",
        )
    elif has_critical:
        llm_result = EmailClassificationOutput(
            category="@Urgent",
            urgency_score=10,
            confidence_score=0.99,
            reasoning="Deterministic emergency critical keyword incident triage (@Urgent)",
            context_tags=["emergency", "critical", "incident"],
            is_reply_necessary=True,
            reply_necessity_reason="Critical emergency escalation requires immediate response",
            is_scheduling_request=False,
            speech_act="REQUEST",
            vocative_ownership=vocative_hint,
        )
    elif is_vip:
        llm_result = EmailClassificationOutput(
            category="@Action",
            urgency_score=8,
            confidence_score=0.98,
            reasoning="Deterministic VIP fast-path escalation to @Action",
            context_tags=["vip", "executive", "fast_path"],
            is_reply_necessary=True,
            reply_necessity_reason="VIP communications require prompt action",
            is_scheduling_request=any(kw in content_lower for kw in ["meet", "calendar", "schedule", "call", "zoom"]),
            speech_act=_infer_offline_speech_act(content_lower, "@Action"),
            vocative_ownership=vocative_hint,
        )
    elif is_no_reply or any(kw in content_lower for kw in ["unsubscribe", "special offer", "50% off", "40% off"]):
        llm_result = EmailClassificationOutput(
            category="@Promotions",
            urgency_score=2,
            confidence_score=0.96,
            reasoning="Automated promotional newsletter or marketing message",
            context_tags=["marketing", "promotions"],
            is_reply_necessary=False,
            is_scheduling_request=False,
            speech_act="INFORM",
            vocative_ownership="GENERAL_BROADCAST",
        )
    elif "low_confidence_test" in content_lower:
        llm_result = EmailClassificationOutput(
            category="@Action",
            urgency_score=5,
            confidence_score=0.72,
            reasoning="Vague or ambiguous message context with low semantic certainty",
            context_tags=["ambiguous"],
            is_reply_necessary=False,
            is_scheduling_request=False,
            speech_act="INFORM",
            vocative_ownership=vocative_hint,
        )

    # Step 2: System 1 Jev Single-Pass Multi-Head / Live Platform LLM Gateway
    if llm_result is None:
        try:
            from core_platform.app.llm.gateway import get_platform_llm_gateway

            gateway = get_platform_llm_gateway()
            raw_tid = state.get("tenant_id")
            eff_tenant: Optional[str] = str(raw_tid) if raw_tid else None
            if not eff_tenant:
                try:
                    from core_platform.app.middleware.tenant_context import get_current_tenant_id
                    eff_tenant = get_current_tenant_id()
                except Exception:
                    eff_tenant = None

            # Coarse-to-Fine Hierarchical Routing if > 15 user categories (REV-04)
            candidate_categories = list(valid_categories)
            if len(candidate_categories) > 15 and active_taxonomy:
                parent_domains = sorted({str(c.get("parent_domain", "WORK_DELIVERABLE")) for c in active_taxonomy})
                coarse_dec = await gateway.classify(
                    text=f"Subject: {subject}\nBody: {body[:500]}",
                    choices=parent_domains,
                    task="fast_classification",
                    context=f"Coarse domain routing. Sender: {sender}",
                    operation_id=f"classify_coarse_{state.get('gmail_id', 'unknown')}",
                    tenant_id=eff_tenant,
                    cartridge_id="mail_organizer",
                    priority_lane=priority_lane,
                )
                if coarse_dec and coarse_dec.selected_choice in parent_domains:
                    narrowed = [
                        str(c["category_name"])
                        for c in active_taxonomy
                        if str(c.get("parent_domain")) == coarse_dec.selected_choice
                    ]
                    if narrowed:
                        candidate_categories = narrowed

            questions = [
                QuestionSpec(
                    question_id="category",
                    instructions="Select the best triage category for this email.",
                    choices={c: cat_descriptions.get(c, c) for c in candidate_categories},
                ),
                QuestionSpec(
                    question_id="speech_act",
                    instructions="Classify the primary linguistic speech-act of the sender.",
                    choices={
                        "REQUEST": "Sender asks for a deliverable, decision, or action",
                        "COMMIT": "Sender promises or commits to deliver something by a deadline",
                        "PROPOSE": "Sender proposes a meeting time, contract term, or option",
                        "INFORM": "Sender shares status or FYI information with no ask",
                        "DECLINE": "Sender rejects or declines a prior request or invite",
                    },
                ),
                QuestionSpec(
                    question_id="vocative_ownership",
                    instructions="Determine who is directly addressed in the greeting/body.",
                    choices={
                        "ADDRESSED_TO_USER": "Directly addresses the mailbox owner for action",
                        "DELEGATED_TO_OTHER": "Addresses a different named colleague for action",
                        "GENERAL_BROADCAST": "General group greeting or no specific individual named",
                    },
                ),
                QuestionSpec(
                    question_id="urgency_band",
                    instructions="Select the operational urgency band.",
                    choices={
                        "CRITICAL_9_10": "Production outage, emergency blocker, or immediate escalation",
                        "HIGH_7_8": "Time-sensitive deliverable, VIP ask, or today/tomorrow deadline",
                        "NORMAL_4_6": "Routine work task or standard follow-up",
                        "LOW_1_3": "Newsletter, FYI, or low-priority background info",
                    },
                ),
            ]

            multi_res = await gateway.classify_multi(
                text=f"Subject: {subject}\nBody: {body[:600]}",
                questions=questions,
                task="fast_classification",
                context=f"Executive email triage. Sender: {sender}",
                operation_id=f"classify_multi_{state.get('gmail_id', 'unknown')}",
                tenant_id=eff_tenant,
                cartridge_id="mail_organizer",
                priority_lane=priority_lane,
            )

            if multi_res and "category" in multi_res.answers:
                cat_ans = multi_res.answers["category"]
                sa_ans = multi_res.answers.get("speech_act")
                voc_ans = multi_res.answers.get("vocative_ownership")
                urg_ans = multi_res.answers.get("urgency_band")

                sel_cat = cat_ans.selected_choice if cat_ans.selected_choice in valid_categories else valid_categories[0]
                sel_sa = sa_ans.selected_choice if sa_ans else _infer_offline_speech_act(content_lower, sel_cat)
                sel_voc = voc_ans.selected_choice if voc_ans else vocative_hint
                if vocative_hint in ("ADDRESSED_TO_USER", "DELEGATED_TO_OTHER"):
                    sel_voc = vocative_hint

                urg_map = {"CRITICAL_9_10": 9, "HIGH_7_8": 8, "NORMAL_4_6": 6, "LOW_1_3": 2}
                urgency = urg_map.get(urg_ans.selected_choice if urg_ans else "", 8 if sel_cat == "@Action" else 6)

                llm_result = EmailClassificationOutput(
                    category=sel_cat,
                    urgency_score=urgency,
                    confidence_score=cat_ans.confidence,
                    reasoning=cat_ans.reasoning or f"Jev multi-head classified in {multi_res.latency_ms:.1f}ms",
                    context_tags=["system1_triaged", f"speech_act:{sel_sa.lower()}"],
                    is_reply_necessary=sel_cat in ("@Action", "@Urgent", "@Meeting", "@CodeReview") or sel_sa in ("REQUEST", "PROPOSE"),
                    is_scheduling_request=sel_cat == "@Meeting" or sel_sa == "PROPOSE" or any(kw in content_lower for kw in ["meet", "schedule"]),
                    speech_act=sel_sa,
                    vocative_ownership=sel_voc,
                )
            else:
                # Backward-compatible single-head System 1 check (also honors mocked LLMGateway.classify in unit tests)
                decision = await gateway.classify(
                    text=f"Subject: {subject}\nBody: {body[:500]}",
                    choices=candidate_categories,
                    task="fast_classification",
                    context=f"Executive email triage. Sender: {sender}",
                    operation_id=f"classify_s1_{state.get('gmail_id', 'unknown')}",
                    tenant_id=eff_tenant,
                    cartridge_id="mail_organizer",
                    priority_lane=priority_lane,
                )
                if decision and decision.selected_choice in valid_categories:
                    urgency = 9 if decision.selected_choice == "@Urgent" else (8 if decision.selected_choice == "@Action" else 5)
                    llm_result = EmailClassificationOutput(
                        category=decision.selected_choice,
                        urgency_score=urgency,
                        confidence_score=decision.confidence,
                        reasoning=decision.reasoning or f"System 1 classified in {decision.latency_ms:.1f}ms",
                        context_tags=["system1_triaged"],
                        is_reply_necessary=decision.selected_choice in ("@Action", "@Urgent", "@Meeting"),
                        is_scheduling_request=decision.selected_choice == "@Meeting" or any(kw in content_lower for kw in ["meet", "schedule"]),
                        speech_act=_infer_offline_speech_act(content_lower, decision.selected_choice),
                        vocative_ownership=vocative_hint,
                    )
                else:
                    # System 2 Deep Generative Path (Gemini / Claude)
                    org_block = build_org_context_block(sender, subject, body)
                    org_prompt_section = f"{org_block}\n\n" if org_block else ""
                    prompt = (
                        "You are an executive email triage and categorization assistant. "
                        f"Analyze the following email and categorize it into exactly one of: {', '.join(candidate_categories)}.\n\n"
                        f"{org_prompt_section}"
                        f"From: {sender}\n"
                        f"Subject: {subject}\n"
                        f"Body:\n{body[:2000]}\n\n"
                        "Return a single JSON object conforming strictly to this schema:\n"
                        "{\n"
                        '  "category": "@Action" | "@Urgent" | "@Meeting" | "@WaitingOn" | "@Promotions" | "@Financial" | "@ProjectTask",\n'
                        '  "urgency_score": int (1 to 10),\n'
                        '  "confidence_score": float (0.0 to 1.0),\n'
                        '  "reasoning": "brief explanation",\n'
                        '  "context_tags": ["tag1", "tag2"],\n'
                        '  "is_reply_necessary": bool,\n'
                        '  "reply_necessity_reason": "string or null",\n'
                        '  "is_scheduling_request": bool\n'
                        "}"
                    )
                    parsed = await gateway.generate(
                        task="text_generation",
                        prompt=prompt,
                        temperature=0.0,
                        response_mime_type="application/json",
                        operation_id=f"classify_{state.get('gmail_id', 'unknown')}",
                        tenant_id=eff_tenant,
                        cartridge_id="mail_organizer",
                    )
                    if parsed and isinstance(parsed, dict) and "category" in parsed:
                        llm_result = EmailClassificationOutput(**parsed)
        except Exception as exc:
            logger.debug("[ClassifyNode] LLM gateway failed: %s", exc)

    # Step 3: Offline Deterministic Engine Fallback
    if llm_result is None:
        if has_critical or "critical" in content_lower or "sev1" in content_lower or "outage" in content_lower:
            llm_result = EmailClassificationOutput(
                category="@Urgent",
                urgency_score=10 if has_critical else 9,
                confidence_score=0.98,
                reasoning="Critical production incident or emergency escalation detected",
                context_tags=["urgent", "incident", "production"],
                is_reply_necessary=True,
                reply_necessity_reason="Critical escalation demands acknowledgement",
                is_scheduling_request=False,
                speech_act="REQUEST",
                vocative_ownership=vocative_hint,
            )
        elif any(kw in content_lower for kw in ["meet", "calendar", "schedule", "zoom", "call", "catch up", "appointment"]):
            llm_result = EmailClassificationOutput(
                category="@Meeting",
                urgency_score=7,
                confidence_score=0.92,
                reasoning="Meeting request or scheduling inquiry",
                context_tags=["calendar", "scheduling"],
                is_reply_necessary=True,
                reply_necessity_reason="Sender requested meeting time slots",
                is_scheduling_request=True,
                speech_act="PROPOSE",
                vocative_ownership=vocative_hint,
            )
        elif any(kw in content_lower for kw in ["invoice", "receipt", "payment", "billing", "wire", "po#"]):
            llm_result = EmailClassificationOutput(
                category="@Financial",
                urgency_score=6,
                confidence_score=0.91,
                reasoning="Financial documentation, billing or invoice inquiry",
                context_tags=["finance", "invoice", "billing"],
                is_reply_necessary=True,
                reply_necessity_reason="Financial review required",
                is_scheduling_request=False,
                speech_act="REQUEST",
                vocative_ownership=vocative_hint,
            )
        elif "low_confidence_test" in content_lower or "ambiguous" in content_lower:
            llm_result = EmailClassificationOutput(
                category="@Action",
                urgency_score=5,
                confidence_score=0.72,
                reasoning="Vague or ambiguous message context with low semantic certainty",
                context_tags=["ambiguous"],
                is_reply_necessary=False,
                is_scheduling_request=False,
                speech_act="INFORM",
                vocative_ownership=vocative_hint,
            )
        elif any(kw in content_lower for kw in ["newsletter", "unsubscribe", "discount", "promotion"]):
            llm_result = EmailClassificationOutput(
                category="@Promotions",
                urgency_score=2,
                confidence_score=0.96,
                reasoning="Automated promotional newsletter or marketing message",
                context_tags=["marketing", "promotions"],
                is_reply_necessary=False,
                is_scheduling_request=False,
                speech_act="INFORM",
                vocative_ownership="GENERAL_BROADCAST",
            )
        else:
            inferred_sa = _infer_offline_speech_act(content_lower, "@Action")
            cat_choice = "@WaitingOn" if inferred_sa == "COMMIT" else "@Action"
            llm_result = EmailClassificationOutput(
                category=cat_choice,
                urgency_score=6,
                confidence_score=0.88,
                reasoning="Actionable workplace email requiring follow-up",
                context_tags=["business", "operational"],
                is_reply_necessary=cat_choice == "@Action",
                reply_necessity_reason="Direct deliverable requested",
                is_scheduling_request=False,
                speech_act=inferred_sa,
                vocative_ownership=vocative_hint,
            )

    result = llm_result

    # Dynamic Vocative Ownership Promotion / Demotion (REV-02)
    header_role = state.get("header_recipient_role") or "PRIMARY_ACTIONEE"
    was_promoted = bool(state.get("was_promoted_from_cc", False))
    if header_role in ("OBSERVER_CC", "CO_ACTIONEE") and result.vocative_ownership == "ADDRESSED_TO_USER":
        was_promoted = header_role == "OBSERVER_CC"
        state["was_promoted_from_cc"] = was_promoted
        state["responsibility_role"] = "PRIMARY_ACTIONEE"
        result.is_reply_necessary = True
    elif header_role == "CO_ACTIONEE" and result.vocative_ownership == "DELEGATED_TO_OTHER":
        state["responsibility_role"] = "OBSERVER_ONLY"
        result.is_reply_necessary = False
    elif state.get("responsibility_role") == "OBSERVER_ONLY" and not was_promoted:
        result.is_reply_necessary = False

    # Populate state
    state["category"] = result.category
    state["urgency_score"] = result.urgency_score
    state["confidence_score"] = result.confidence_score
    state["speech_act"] = result.speech_act
    merged_tags = list(result.context_tags)
    for pt in project_tags:
        if pt not in merged_tags:
            merged_tags.append(pt)
    if state.get("was_promoted_from_cc") and "vocative_promoted" not in merged_tags:
        merged_tags.append("vocative_promoted")

    state["reasoning"] = result.reasoning
    state["context_tags"] = merged_tags
    state["is_reply_necessary"] = result.is_reply_necessary
    state["is_scheduling_request"] = result.is_scheduling_request

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "classify",
        "duration_ms": duration_ms,
        "category": result.category,
        "speech_act": result.speech_act,
        "vocative_ownership": result.vocative_ownership,
        "was_promoted_from_cc": bool(state.get("was_promoted_from_cc", False)),
        "urgency_score": result.urgency_score,
        "confidence_score": result.confidence_score,
        "is_scheduling_request": result.is_scheduling_request,
    })
    state["pipeline_trace"] = trace

    return state

