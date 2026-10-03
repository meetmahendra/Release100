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
TypeSafe AI / Jev Provider Implementation.

Provides ultra-low-latency System 1 decision and schema-constrained classification
capabilities. Implements both BaseDecisionProvider and BaseLLMProvider interfaces.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from core_platform.app.errors import LLMProviderError, PlatformErrorCode
from core_platform.app.llm.base import BaseDecisionProvider, BaseLLMProvider, DecisionResult

logger = logging.getLogger("core_platform.llm.typesafe_provider")


class TypeSafeProviderError(LLMProviderError):
    """Raised when an operation against the TypeSafe AI API fails."""


class TypeSafeProvider(BaseDecisionProvider, BaseLLMProvider):
    """TypeSafe AI / Jev System 1 Decision & Classification Provider.

    Connects to the TypeSafe AI API (or compatible local mock/runtime)
    to perform fast non-autoregressive schema evaluations with calibrated confidence.
    """

    provider_name: str = "typesafe"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.typesafe.ai/v1",
        default_model: str = "jev-latest",
        timeout_seconds: float = 3.0,
    ) -> None:
        """Initialize the TypeSafe AI provider.

        Args:
            api_key: Secret API key for TypeSafe AI service.
            base_url: Base URL for API endpoints.
            default_model: Default Jev decision model (e.g. 'jev-latest').
            timeout_seconds: Request timeout in seconds (default 3.0s for low latency).
        """
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._default_model = self._normalize_model(default_model)
        self._timeout = timeout_seconds
        self.last_error: Optional[str] = None

    @staticmethod
    def _normalize_model(model_name: Optional[str]) -> str:
        """Normalize legacy or alias model names to supported Jev models."""
        m = (model_name or "jev-latest").strip()
        if m in ("jev-1", "jev", "jev_1", ""):
            return "jev-latest"
        return m

    def _get_systemone_endpoint(self) -> str:
        """Resolve full URL to the TypeSafe AI /systemone endpoint."""
        url = self._base_url.rstrip("/")
        if url.endswith("/systemone"):
            return url
        return f"{url}/systemone"

    def is_available(self) -> bool:
        """Return True if the API key or local mock endpoint is configured."""
        return bool(self._api_key or "localhost" in self._base_url or "127.0.0.1" in self._base_url)

    async def classify(
        self,
        text: str,
        choices: List[str],
        *,
        context: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[DecisionResult]:
        """Classify input text against candidate choices in sub-100ms.

        Uses the TypeSafe AI System 1 endpoint (/systemone) with calibrated confidence.

        Args:
            text: Input message or query string.
            choices: List of target categorical choices.
            context: Optional domain context or system prompt guidance.
            model: Optional model identifier override.

        Returns:
            DecisionResult containing selected choice and calibrated confidence, or None.
        """
        if not choices:
            self.last_error = "Choices list cannot be empty"
            return None

        if not self.is_available():
            self.last_error = "TypeSafe API key is not configured"
            return None

        target_model = self._normalize_model(model or self._default_model)
        endpoint = self._get_systemone_endpoint()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Release100-Microkernel/2.0",
        }
        question_key = "decision"
        criteria_dict: Dict[str, str] = {c: f"Category {c}" for c in choices}
        payload: Dict[str, Any] = {
            "model": target_model,
            "state": text,
            "questions": {
                question_key: {
                    "type": "choice",
                    "instructions": context or "Classify the input into the most appropriate category.",
                    "criteria": criteria_dict,
                }
            },
        }

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                if response.status_code != 200:
                    self.last_error = f"TypeSafe HTTP {response.status_code}: {response.text[:200]}"
                    logger.warning("[TypeSafeProvider] Request failed: %s", self.last_error)
                    return None

                data = response.json()
                answers = data.get("answers")
                ans_obj: Dict[str, Any] = {}
                if isinstance(answers, dict) and answers:
                    ans_obj = answers.get(question_key) or next(iter(answers.values()), {})
                elif isinstance(data, dict):
                    ans_obj = data

                selected = str(
                    ans_obj.get("choice")
                    or ans_obj.get("selection")
                    or ans_obj.get("selected_choice")
                    or data.get("selected_choice")
                    or data.get("choice")
                    or choices[0]
                )
                prob = ans_obj.get("confidence")
                if prob is None:
                    prob = ans_obj.get("probability")
                if prob is None:
                    prob = data.get("confidence", 0.95)
                confidence = float(prob)

                reasoning = str(
                    ans_obj.get("reasoning")
                    or data.get("reasoning")
                    or f"TypeSafe System 1 calibrated decision ({selected})"
                )
                raw_scores = (
                    ans_obj.get("probabilities")
                    or ans_obj.get("scores")
                    or data.get("probabilities")
                    or data.get("scores")
                )
                raw_scores_dict: Optional[Dict[str, float]] = (
                    raw_scores if isinstance(raw_scores, dict) else None
                )

                return DecisionResult(
                    selected_choice=selected,
                    confidence=confidence,
                    reasoning=reasoning,
                    latency_ms=latency_ms,
                    raw_scores=raw_scores_dict,
                )
        except Exception as exc:
            self.last_error = f"TypeSafe network/inference exception: {exc}"
            logger.warning("[TypeSafeProvider] Classification failed: %s", exc)
            return None

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        response_mime_type: str = "application/json",
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """LLM generation adapter translating text prompt into structured decision.

        Args:
            prompt: Text prompt.
            temperature: Inference temperature.
            response_mime_type: Expected MIME type.
            model: Optional model identifier.
            system_instruction: Optional system instruction.

        Returns:
            Parsed JSON dictionary or None.
        """
        if not self.is_available():
            return None

        target_model = self._normalize_model(model or self._default_model)
        endpoint = self._get_systemone_endpoint()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        question_key = "analysis"
        payload: Dict[str, Any] = {
            "model": target_model,
            "state": prompt,
            "questions": {
                question_key: {
                    "type": "choice",
                    "instructions": system_instruction or "Evaluate the input state.",
                    "criteria": {
                        "approved": "Operation approved or valid",
                        "flagged": "Operation flagged for manual review",
                        "neutral": "Informational or neutral state",
                    },
                }
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                if response.status_code != 200:
                    self.last_error = f"TypeSafe HTTP {response.status_code}: {response.text[:200]}"
                    return None
                data = response.json()
                if isinstance(data, dict):
                    answers = data.get("answers")
                    if isinstance(answers, dict):
                        return answers
                    return data
                return {"result": data}
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("[TypeSafeProvider] generate failed: %s", exc)
            return None

    async def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Multimodal adapter - delegates vision tasks to System 2."""
        self.last_error = "TypeSafe / Jev is a System 1 text/decision model. Multimodal delegated to System 2."
        logger.debug("[TypeSafeProvider] generate_multimodal not natively supported, deferring to System 2.")
        return None
