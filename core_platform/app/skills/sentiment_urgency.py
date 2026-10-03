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
Universal Sentiment and Urgency Triage Skill (`SentimentUrgencySkill`).

Stateless cognitive skill for fast triage of inbound messages, alerts,
and emails into standardized urgency and sentiment tiers.
"""

from enum import Enum
import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from core_platform.app.llm.gateway import get_platform_llm_gateway
from core_platform.app.skills.base import BaseSkill

logger = logging.getLogger("core_platform.skills.sentiment_urgency")


class UrgencyTier(str, Enum):
    """Standardized urgency tiers."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SentimentTier(str, Enum):
    """Standardized sentiment categories."""

    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    ESCALATED = "ESCALATED"


class TriageAssessment(BaseModel):
    """Result from the SentimentUrgencySkill."""

    urgency: UrgencyTier = Field(description="Assessed message urgency level")
    sentiment: SentimentTier = Field(description="Assessed sentiment or customer tone")
    confidence: float = Field(ge=0.0, le=1.0, description="Calibrated assessment confidence score")
    requires_escalation: bool = Field(default=False, description="True if urgency is HIGH or CRITICAL")
    reasoning: str = Field(default="", description="Brief assessment rationale")


class SentimentUrgencySkill(BaseSkill):
    """Hermetic cognitive skill for fast message triage and priority scoring."""

    def __init__(self) -> None:
        """Initialize SentimentUrgencySkill."""
        super().__init__(skill_name="sentiment_urgency")

    async def initialize(self) -> None:
        """Warm up / initialize skill."""
        pass

    def is_available(self) -> bool:
        """Skill availability."""
        return True

    async def assess_triage(
        self,
        text: str,
        *,
        context: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> TriageAssessment:
        """Assess urgency and sentiment of a message in sub-100ms.

        Args:
            text: Inbound message, ticket, or email text.
            context: Optional contextual guidance.
            operation_id: Optional telemetry correlation ID.

        Returns:
            TriageAssessment containing urgency, sentiment, confidence, and escalation flag.
        """
        await self.ensure_initialized()

        clean_text = text.strip()
        if not clean_text:
            return TriageAssessment(
                urgency=UrgencyTier.LOW,
                sentiment=SentimentTier.NEUTRAL,
                confidence=1.0,
                requires_escalation=False,
                reasoning="Empty input text",
            )

        # Keyword heuristics for high-urgency triggers (Layer 0 deterministic pre-check)
        text_lower = clean_text.lower()
        critical_keywords = ["fire", "emergency", "danger", "critical", "severe", "failure", "burst", "sos"]
        if any(kw in text_lower for kw in critical_keywords):
            return TriageAssessment(
                urgency=UrgencyTier.CRITICAL,
                sentiment=SentimentTier.ESCALATED,
                confidence=0.99,
                requires_escalation=True,
                reasoning="Deterministic critical safety keyword detected",
            )

        gateway = get_platform_llm_gateway()
        urgency_choices = [u.value for u in UrgencyTier]

        try:
            decision = await gateway.classify(
                text=clean_text,
                choices=urgency_choices,
                task="fast_classification",
                context=f"Evaluate urgency and severity for operational triage. Context: {context or 'General'}",
                operation_id=operation_id,
            )
            if decision and decision.selected_choice in urgency_choices:
                urgency = UrgencyTier(decision.selected_choice)
                is_high_or_crit = urgency in (UrgencyTier.HIGH, UrgencyTier.CRITICAL)
                return TriageAssessment(
                    urgency=urgency,
                    sentiment=SentimentTier.ESCALATED if is_high_or_crit else SentimentTier.NEUTRAL,
                    confidence=decision.confidence,
                    requires_escalation=is_high_or_crit,
                    reasoning=decision.reasoning,
                )
        except Exception as exc:
            logger.warning("[SentimentUrgencySkill] Assessment gateway error: %s", exc)

        # Deterministic fallback
        return TriageAssessment(
            urgency=UrgencyTier.MEDIUM,
            sentiment=SentimentTier.NEUTRAL,
            confidence=0.70,
            requires_escalation=False,
            reasoning="Default heuristic fallback",
        )
