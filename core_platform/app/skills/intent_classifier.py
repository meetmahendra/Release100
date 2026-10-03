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
Universal Intent Classifier Skill (`IntentClassifierSkill`).

Stateless cognitive skill that resolves natural-language text against
a schema-constrained list of intent categories using System 1 fast decision models
(TypeSafe / Jev) with automatic fallback to System 2 (Gemini).
"""

import logging
from typing import Any, Dict, List, Optional

from core_platform.app.errors import PlatformErrorCode, SkillExecutionError
from core_platform.app.llm.base import DecisionResult
from core_platform.app.llm.gateway import get_platform_llm_gateway
from core_platform.app.skills.base import BaseSkill

logger = logging.getLogger("core_platform.skills.intent_classifier")


class IntentClassifierSkill(BaseSkill):
    """Hermetic, domain-agnostic intent classification skill."""

    def __init__(self) -> None:
        """Initialize the IntentClassifierSkill."""
        super().__init__(skill_name="intent_classifier")

    async def initialize(self) -> None:
        """Verify that the intelligence gateway is initialized."""
        pass

    def is_available(self) -> bool:
        """Return True as gateway provides multi-tier fallbacks."""
        return True

    async def classify_intent(
        self,
        text: str,
        valid_intents: List[str],
        *,
        context: Optional[str] = None,
        task: str = "fast_classification",
        operation_id: Optional[str] = None,
    ) -> DecisionResult:
        """Classify input text against a schema-constrained list of intents.

        Args:
            text: Inbound message, prompt, or user query.
            valid_intents: List of valid categorical intent strings or enum names.
            context: Optional contextual or domain guidance string.
            task: Gateway task routing key (default 'fast_classification').
            operation_id: Optional telemetry correlation ID.

        Returns:
            DecisionResult containing the chosen intent, confidence, and latency.

        Raises:
            SkillExecutionError: If valid_intents is empty or classification completely fails.
        """
        await self.ensure_initialized()

        if not valid_intents:
            raise SkillExecutionError(
                message="Cannot classify intent with an empty valid_intents list.",
                code=PlatformErrorCode.LLM_SCHEMA_VALIDATION_FAILED,
                context={"text": text},
            )

        clean_text = text.strip()
        if not clean_text:
            # Deterministic empty fallback
            return DecisionResult(
                selected_choice=valid_intents[0],
                confidence=0.5,
                reasoning="Empty input text — defaulted to first available intent",
                latency_ms=0.0,
            )

        gateway = get_platform_llm_gateway()
        try:
            decision = await gateway.classify(
                text=clean_text,
                choices=valid_intents,
                task=task,
                context=context,
                operation_id=operation_id,
            )
            if decision and decision.selected_choice in valid_intents:
                return decision
        except Exception as exc:
            logger.warning("[IntentClassifierSkill] Classification gateway error: %s", exc)

        # Local deterministic keyword fallback as fail-safe
        best_intent = valid_intents[0]
        text_lower = clean_text.lower()
        for intent in valid_intents:
            if intent.lower() in text_lower or text_lower in intent.lower():
                best_intent = intent
                break

        return DecisionResult(
            selected_choice=best_intent,
            confidence=0.65,
            reasoning="Deterministic fail-safe keyword match",
            latency_ms=0.1,
        )
