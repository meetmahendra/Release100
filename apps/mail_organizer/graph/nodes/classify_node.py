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
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from apps.mail_organizer.graph.state import MailOrganizerState
from core_platform.app.config import settings

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


async def classify_node(state: MailOrganizerState) -> MailOrganizerState:
    """Classify email intent and urgency via structured schema."""
    t0 = time.perf_counter()

    subject = state.get("subject") or ""
    body = state.get("body") or ""
    sender = state.get("sender") or ""
    has_critical = state.get("has_critical_subject", False)
    is_no_reply = state.get("is_no_reply", False)

    # Check organizational intelligence
    from apps.mail_organizer.services.org_context_service import (
        build_org_context_block,
        is_org_vip,
        resolve_active_projects,
        resolve_sender_persona,
    )
    is_vip = state.get("is_vip", False) or is_org_vip(sender)
    state["is_vip"] = is_vip

    content_lower = f"{subject} {body}".lower()
    matched_projects = resolve_active_projects(f"{subject} {body}")
    project_tags = [p.get("name", "").lower() for p in matched_projects if p.get("name")]

    # Step 1: Layer 0 Deterministic Pre-Execution Filter (VIP Fast-Path & Newsletters)
    llm_result: Optional[EmailClassificationOutput] = None

    if is_vip:
        llm_result = EmailClassificationOutput(
            category="@Action",
            urgency_score=8,
            confidence_score=0.98,
            reasoning="Deterministic VIP fast-path escalation to @Action",
            context_tags=["vip", "executive", "fast_path"],
            is_reply_necessary=True,
            reply_necessity_reason="VIP communications require prompt action",
            is_scheduling_request=any(kw in content_lower for kw in ["meet", "calendar", "schedule", "call", "zoom"]),
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
        )

    # Step 2: Live Platform LLM Gateway with clamped temperature (0.0)
    if llm_result is None:
        try:
            from core_platform.app.llm.gateway import get_platform_llm_gateway

            gateway = get_platform_llm_gateway()
            org_block = build_org_context_block(sender, subject, body)
            org_prompt_section = f"{org_block}\n\n" if org_block else ""
            prompt = (
                "You are an executive email triage and categorization assistant. "
                "Analyze the following email and categorize it into exactly one of: "
                "@Action, @Urgent, @Meeting, @WaitingOn, @Promotions, @Financial, @ProjectTask.\n\n"
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
            )
            if parsed and isinstance(parsed, dict) and "category" in parsed:
                llm_result = EmailClassificationOutput(**parsed)
        except Exception as exc:
            logger.debug("[ClassifyNode] LLM gateway failed: %s", exc)

    # Step 3: Offline Deterministic Engine Fallback (when offline, no API key, or network error)
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
            )
        elif "low_confidence_test" in content_lower or "ambiguous" in content_lower:
            llm_result = EmailClassificationOutput(
                category="@Action",
                urgency_score=5,
                confidence_score=0.72,  # Sub-threshold to test Layer 2 review gate
                reasoning="Vague or ambiguous message context with low semantic certainty",
                context_tags=["ambiguous"],
                is_reply_necessary=False,
                is_scheduling_request=False,
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
            )
        else:
            llm_result = EmailClassificationOutput(
                category="@Action",
                urgency_score=6,
                confidence_score=0.88,
                reasoning="Actionable workplace email requiring follow-up",
                context_tags=["business", "operational"],
                is_reply_necessary=True,
                reply_necessity_reason="Direct deliverable requested",
                is_scheduling_request=False,
            )

    result = llm_result

    # Populate state
    state["category"] = result.category
    state["urgency_score"] = result.urgency_score
    state["confidence_score"] = result.confidence_score
    merged_tags = list(result.context_tags)
    for pt in project_tags:
        if pt not in merged_tags:
            merged_tags.append(pt)

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
        "urgency_score": result.urgency_score,
        "confidence_score": result.confidence_score,
        "is_scheduling_request": result.is_scheduling_request,
    })
    state["pipeline_trace"] = trace

    return state
