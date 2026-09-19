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
Multi-Modal Semantic Router.

Adheres strictly to Plan 02 v1.3 Section 5 (Semantic Router).
Routes inbound requests to the correct application cartridge by:

1. Single-app bypass  — if only ONE candidate app is present, dispatch directly
   with zero LLM token cost (100% offline reliable).
2. Gemini LLM routing — structured RoutingDecision for 2+ candidate apps.
3. Disambiguation gate — if confidence < 0.75, generates a clarification reply.
4. Deterministic fallback — returns the first candidate app when LLM is offline.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core_platform.app.llm.gateway import get_platform_llm_gateway

logger = logging.getLogger("core_platform.routing.semantic_router")


class RoutingDecision(BaseModel):
    """Structured output from the semantic router."""

    selected_app: str = Field(description="app_id of the selected application cartridge")
    confidence: float = Field(ge=0.0, le=1.0, description="Router confidence score")
    reasoning: str = Field(description="Brief explanation of routing decision")
    intent_category: str = Field(description="Detected intent category (e.g. 'attendance', 'email_triage')")
    requires_disambiguation: bool = Field(
        default=False,
        description="True when confidence < 0.75 and user clarification is needed",
    )


# App descriptor registry — populated by plugin loader at boot.
_APP_DESCRIPTORS: Dict[str, str] = {}


def register_app_descriptor(app_id: str, description: str) -> None:
    """Register an app's routing descriptor so the router can identify it.

    Called by the plugin loader during cartridge mounting.

    Args:
        app_id: Unique cartridge identifier (e.g. "temperature_marker").
        description: Short natural-language description of what the app handles.
    """
    _APP_DESCRIPTORS[app_id] = description
    logger.debug("[SemanticRouter] Registered app descriptor: %s", app_id)


# Hardcoded fallback descriptors for known cartridges.
_DEFAULT_DESCRIPTORS: Dict[str, str] = {
    "temperature_marker": (
        "Handles factory floor attendance and temperature recording. "
        "Processes selfie photos with face recognition and chiller display OCR. "
        "Keywords: attendance, check-in, temperature, chiller, CaneBot, photo."
    ),
    "mail_organizer": (
        "Handles email triage, meeting scheduling, and PM task extraction. "
        "Processes email content, drafts replies, and creates Jira/Linear tickets. "
        "Keywords: email, meeting, schedule, task, draft, calendar, inbox."
    ),
}


class SemanticRouter:
    """Routes an inbound text+media payload to the correct application cartridge."""

    _CONFIDENCE_THRESHOLD: float = 0.75

    @classmethod
    async def route(
        cls,
        text_content: Optional[str],
        candidate_apps: List[str],
        sender_id: str = "",
        channel: str = "whatsapp",
    ) -> RoutingDecision:
        """Determine which application should handle this request.

        Args:
            text_content: Inbound text payload (WhatsApp message body, email subject, etc.).
            candidate_apps: RBAC-pruned list of apps this sender is permitted to access.
            sender_id: Sender identifier for logging.
            channel: Source channel name.

        Returns:
            RoutingDecision with selected_app and confidence.
        """
        if not candidate_apps:
            logger.warning("[SemanticRouter] Empty candidate_apps for sender=%s", sender_id)
            return RoutingDecision(
                selected_app="temperature_marker",
                confidence=0.0,
                reasoning="No candidate apps available — defaulting to temperature_marker",
                intent_category="unknown",
                requires_disambiguation=False,
            )

        # ── Single-app bypass (zero LLM tokens, 100% offline) ────────────────
        if len(candidate_apps) == 1:
            app_id = candidate_apps[0]
            logger.debug(
                "[SemanticRouter] Single-app bypass → %s (sender=%s)", app_id, sender_id
            )
            return RoutingDecision(
                selected_app=app_id,
                confidence=1.0,
                reasoning=f"Single permitted application: {app_id}",
                intent_category="single_app_bypass",
                requires_disambiguation=False,
            )

        # ── Multi-app LLM routing ─────────────────────────────────────────────
        text = (text_content or "").strip()
        if not text:
            # No text: for WhatsApp, image without text → most likely temperature_marker
            first = candidate_apps[0]
            return RoutingDecision(
                selected_app=first,
                confidence=0.65,
                reasoning="No text content — defaulted to first permitted app",
                intent_category="media_only",
                requires_disambiguation=False,
            )

        # Build app descriptor block for the LLM prompt.
        descriptor_lines = []
        for app_id in candidate_apps:
            desc = _APP_DESCRIPTORS.get(app_id) or _DEFAULT_DESCRIPTORS.get(app_id) or app_id
            descriptor_lines.append(f'  "{app_id}": "{desc}"')
        descriptors_block = "{\n" + ",\n".join(descriptor_lines) + "\n}"

        prompt = (
            "You are a request router for a multi-application platform. "
            "Your task is to determine which application should handle the following message.\n\n"
            f"Applications available:\n{descriptors_block}\n\n"
            f"Channel: {channel}\n"
            f"Message: {text[:500]}\n\n"
            "Return a single JSON object with exactly these keys:\n"
            '{ "selected_app": "<app_id>", "confidence": <0.0-1.0>, '
            '"reasoning": "<brief explanation>", "intent_category": "<category>" }'
        )

        result: Optional[Dict[str, Any]] = None
        try:
            gateway = get_platform_llm_gateway()
            result = await gateway.generate(task="intent_routing", prompt=prompt, temperature=0.0)
        except Exception as exc:
            logger.warning("[SemanticRouter] LLM call failed: %s", exc)

        if result and "selected_app" in result and result["selected_app"] in candidate_apps:
            confidence = float(result.get("confidence", 0.0))
            needs_disambig = confidence < cls._CONFIDENCE_THRESHOLD
            return RoutingDecision(
                selected_app=str(result["selected_app"]),
                confidence=confidence,
                reasoning=str(result.get("reasoning", "")),
                intent_category=str(result.get("intent_category", "llm_routed")),
                requires_disambiguation=needs_disambig,
            )

        # ── Deterministic fallback ────────────────────────────────────────────
        logger.warning(
            "[SemanticRouter] LLM routing failed or returned invalid app — "
            "using keyword fallback for sender=%s",
            sender_id,
        )
        return cls._keyword_fallback(text, candidate_apps)

    @classmethod
    def _keyword_fallback(cls, text: str, candidate_apps: List[str]) -> RoutingDecision:
        """Deterministic keyword-based routing fallback when LLM is offline.

        Args:
            text: Inbound message text.
            candidate_apps: Candidate app list.

        Returns:
            RoutingDecision based on keyword heuristics.
        """
        text_lower = text.lower()

        temperature_keywords = {
            "temperature", "temp", "chiller", "attendance", "check-in", "check in",
            "checkin", "punch", "photo", "selfie", "canebot", "face",
        }
        mail_keywords = {
            "email", "mail", "meeting", "schedule", "task", "jira", "linear",
            "calendar", "inbox", "draft", "reply", "forward",
        }

        tm_score = sum(1 for kw in temperature_keywords if kw in text_lower)
        mo_score = sum(1 for kw in mail_keywords if kw in text_lower)

        if "temperature_marker" in candidate_apps and tm_score >= mo_score:
            return RoutingDecision(
                selected_app="temperature_marker",
                confidence=0.7,
                reasoning=f"Keyword fallback: temperature_marker score={tm_score}",
                intent_category="keyword_routed",
                requires_disambiguation=False,
            )
        if "mail_organizer" in candidate_apps and mo_score > tm_score:
            return RoutingDecision(
                selected_app="mail_organizer",
                confidence=0.7,
                reasoning=f"Keyword fallback: mail_organizer score={mo_score}",
                intent_category="keyword_routed",
                requires_disambiguation=False,
            )

        # Last resort: first candidate app.
        return RoutingDecision(
            selected_app=candidate_apps[0],
            confidence=0.5,
            reasoning="No keywords matched — defaulted to first permitted app",
            intent_category="keyword_fallback",
            requires_disambiguation=False,
        )
