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
Abstract Base LLM Provider Interface.

Adheres strictly to Plan 02 v1.3 Section 4 (Pluggable LLM Provider Gateway).
All concrete providers (Gemini, Claude, OpenAI, Ollama) must inherit BaseLLMProvider.
Guarantees vendor-neutral task-based dispatch from application cartridges.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DecisionResult(BaseModel):
    """Structured result from a System 1 decision/classification model."""

    selected_choice: str = Field(description="Selected choice label or enum variant name")
    confidence: float = Field(ge=0.0, le=1.0, description="Calibrated confidence score (0.0 - 1.0)")
    reasoning: str = Field(default="", description="Brief explanation or decision trace")
    latency_ms: float = Field(default=0.0, description="Decision latency in milliseconds")
    raw_scores: Optional[Dict[str, float]] = Field(
        default=None, description="Per-choice probability distribution if available"
    )


# [CODE-MARKER: CP-JEV-01] Multi-Question System 1 Specification & Decision Result
class QuestionSpec(BaseModel):
    """Specification for a single schema-constrained question in a multi-question System 1 call."""

    question_id: str = Field(description="Unique key for this question (e.g. 'category', 'speech_act')")
    instructions: str = Field(description="Evaluation instructions for this specific dimension")
    choices: Dict[str, str] = Field(description="Mapping of choice_key -> choice_description")


class MultiQuestionDecisionResult(BaseModel):
    """Structured result from a multi-question System 1 (/systemone) evaluation."""

    answers: Dict[str, DecisionResult] = Field(
        default_factory=dict, description="Mapping of question_id -> DecisionResult"
    )
    latency_ms: float = Field(default=0.0, description="Total batch decision latency in milliseconds")


class BaseDecisionProvider(ABC):
    """Vendor-neutral abstract interface for System 1 fast decision and classification models (e.g. TypeSafe / Jev)."""

    provider_name: str = "base_decision"

    @abstractmethod
    async def classify(
        self,
        text: str,
        choices: List[str],
        *,
        context: Optional[str] = None,
        model: Optional[str] = None,
        priority_lane: str = "HIGH",
    ) -> Optional[DecisionResult]:
        """Classify input text against a schema-constrained list of choices.

        Args:
            text: Input text/query to classify.
            choices: Valid categorical target choices.
            context: Optional contextual guidance or metadata.
            model: Optional model override.
            priority_lane: Concurrency lane ('HIGH' for real-time interactive/kiosk, 'LOW' for background pollers).

        Returns:
            DecisionResult with selected_choice and confidence, or None on failure.
        """
        ...

    async def classify_multi(
        self,
        text: str,
        questions: List[QuestionSpec],
        *,
        context: Optional[str] = None,
        model: Optional[str] = None,
        priority_lane: str = "HIGH",
    ) -> Optional[MultiQuestionDecisionResult]:
        """Evaluate multiple orthogonal classification questions in a single System 1 pass.

        Default implementation sequentially invokes classify() per question if the provider
        does not support native multi-question batching.
        """
        if not questions:
            return None
        answers: Dict[str, DecisionResult] = {}
        total_latency = 0.0
        for q in questions:
            choice_keys = list(q.choices.keys())
            if not choice_keys:
                continue
            combined_ctx = f"{context or ''}\n{q.instructions}".strip()
            res = await self.classify(
                text,
                choice_keys,
                context=combined_ctx,
                model=model,
                priority_lane=priority_lane,
            )
            if res is None:
                return None
            answers[q.question_id] = res
            total_latency += res.latency_ms
        return MultiQuestionDecisionResult(answers=answers, latency_ms=total_latency)

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this decision provider is configured and available."""
        ...

    def get_provider_info(self) -> Dict[str, Any]:
        """Return human-readable metadata for /health endpoint."""
        return {
            "provider_name": self.provider_name,
            "available": self.is_available(),
            "tier": "system_1",
        }


class BaseLLMProvider(ABC):
    """Vendor-neutral abstract interface for all LLM providers.

    Applications call provider methods via the LLMGateway singleton — they
    never import a specific provider directly, ensuring zero vendor lock-in.
    """

    #: Short identifier reported in audit records (e.g. "gemini", "claude").
    provider_name: str = "base"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        response_mime_type: str = "application/json",
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate a structured JSON response from a text prompt.

        Args:
            prompt: The user / task prompt.
            temperature: Sampling temperature; clamped to 0.0–0.2 per GEES Layer 1.
            response_mime_type: Expected MIME type for the response body.
            model: Provider-specific model identifier override.
            system_instruction: Optional system-level instruction.

        Returns:
            Parsed JSON dict, or None on failure (caller uses deterministic fallback).
        """
        ...

    @abstractmethod
    async def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate structured output from a prompt + image (vision tasks).

        Args:
            prompt: The vision analysis prompt.
            image_bytes: Raw JPEG/PNG image bytes.
            temperature: Sampling temperature (clamped).
            model: Provider-specific model identifier override.

        Returns:
            Parsed JSON dict, or None on failure.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is configured and reachable.

        A provider is available if it has a non-empty API key / endpoint
        configured. Network reachability is tested lazily on first call.

        Returns:
            True when the provider can accept requests.
        """
        ...

    def get_provider_info(self) -> Dict[str, Any]:
        """Return human-readable provider metadata for /health endpoint.

        Returns:
            Dict with 'provider_name' and 'available' keys.
        """
        return {
            "provider_name": self.provider_name,
            "available": self.is_available(),
        }
