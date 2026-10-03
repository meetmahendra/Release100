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
Platform LLM Gateway — Singleton Task-Routed Inference Engine.

Adheres strictly to Plan 02 v1.3 Section 4.
Routes inference requests to the correct vendor provider based on task type,
with an automatic fallback chain:

  primary provider → Ollama (local) → deterministic stub (None)

Task types defined by the platform:
  - "intent_routing"     : route inbound messages to the correct app
  - "vision_processing"  : display/meter OCR and multimodal analysis
  - "text_generation"    : classify, summarise, extract structured data
  - "private_local_logs" : local Ollama for privacy-sensitive log analysis

All application cartridges obtain the gateway via:
    from core_platform.app.llm.gateway import get_platform_llm_gateway
    gateway = get_platform_llm_gateway()
    result = await gateway.generate(task="text_generation", prompt=my_prompt, ...)
"""

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from core_platform.app.llm.base import BaseDecisionProvider, BaseLLMProvider, DecisionResult
from core_platform.app.llm.cost_tracker import get_llm_cost_tracker

logger = logging.getLogger("core_platform.llm.gateway")

# Task → provider name mapping. Overridable via config at startup.
_DEFAULT_TASK_PROVIDER: Dict[str, str] = {
    "intent_routing": "typesafe",
    "fast_classification": "typesafe",
    "vision_processing": "gemini",
    "text_generation": "gemini",
    "private_local_logs": "ollama",
}


class LLMGateway:
    """Singleton task-routed LLM inference gateway.

    Manages multiple provider instances and dispatches by task type with
    an automatic fallback chain. All methods are async-safe (no shared
    mutable state after initialization).
    """

    def __init__(self, providers: Dict[str, BaseLLMProvider]) -> None:
        """Initialise gateway with a dict of named providers.

        Args:
            providers: Dict mapping provider_name → BaseLLMProvider instance.
        """
        self._providers = providers
        self._task_map: Dict[str, str] = dict(_DEFAULT_TASK_PROVIDER)

    def configure_task(self, task: str, provider_name: str) -> None:
        """Override the provider assigned to a specific task.

        Args:
            task: Task identifier string (e.g. "intent_routing").
            provider_name: Provider name (e.g. "ollama").
        """
        self._task_map[task] = provider_name

    def _get_provider(self, task: str) -> Optional[BaseLLMProvider]:
        """Resolve the provider for a task, falling back through the chain.

        Fallback order: configured provider → gemini → ollama → None.

        Args:
            task: Task identifier.

        Returns:
            A provider instance that reports is_available(), or None.
        """
        preferred_name = self._task_map.get(task, "gemini")
        fallback_names = [preferred_name, "gemini", "ollama"]

        for name in fallback_names:
            provider = self._providers.get(name)
            if provider and provider.is_available():
                return provider

        return None

    async def generate(
        self,
        task: str,
        prompt: str,
        *,
        temperature: float = 0.0,
        response_mime_type: str = "application/json",
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Route a text generation request to the appropriate provider.

        Args:
            task: Task type key (e.g. "text_generation").
            prompt: The user/task prompt.
            temperature: Inference temperature clamped to [0.0, 0.2].
            response_mime_type: Expected response MIME type.
            model: Provider-specific model override.
            system_instruction: System-level instruction for the model.
            operation_id: Optional correlation ID / trigger name for telemetry.

        Returns:
            Parsed JSON dict, or None when all providers fail (caller should
            use its own deterministic fallback).
        """
        provider = self._get_provider(task)
        if provider is None:
            logger.debug("[LLMGateway] No available provider for task=%s", task)
            return None

        actual_model = str(model or getattr(provider, "_default_model", "default"))
        op_id = operation_id or f"op_{uuid.uuid4().hex[:10]}"
        interaction_id = f"ix_{uuid.uuid4().hex[:10]}"

        logger.debug(
            "[LLMGateway] task=%s → provider=%s model=%s (op=%s)",
            task,
            provider.provider_name,
            actual_model,
            op_id,
        )

        start_time = time.perf_counter()
        success = True
        err_msg = None
        result: Optional[Dict[str, Any]] = None

        try:
            result = await provider.generate(
                prompt,
                temperature=temperature,
                response_mime_type=response_mime_type,
                model=model,
                system_instruction=system_instruction,
            )
            if result is None:
                success = False
                err_msg = getattr(provider, "last_error", None) or "Provider returned None / empty response"
        except Exception as exc:
            success = False
            err_msg = str(exc)
            result = None
        finally:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            # Approximate tokens: ~4 chars per token if usage metadata is absent
            prompt_tokens = max(1, len(prompt) // 4 + (len(system_instruction or "") // 4))
            resp_str = json.dumps(result) if result else ""
            completion_tokens = max(1, len(resp_str) // 4) if result else 0

            # If rejected at ingress (HTTP 4xx client error), zero tokens were billed by cloud provider
            if not success and err_msg and ("HTTP 4" in err_msg or "INVALID_ARGUMENT" in err_msg):
                prompt_tokens = 0
                completion_tokens = 0

            get_llm_cost_tracker().record_interaction(
                interaction_id=interaction_id,
                operation_id=op_id,
                task=task,
                provider=provider.provider_name,
                model=actual_model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=success,
                error_message=err_msg,
            )

        return result

    async def generate_multimodal(
        self,
        task: str,
        prompt: str,
        image_bytes: bytes,
        *,
        temperature: float = 0.0,
        model: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Route a vision/multimodal request to the appropriate provider.

        Args:
            task: Task type key (e.g. "vision_processing").
            prompt: Vision analysis prompt.
            image_bytes: Raw JPEG/PNG bytes.
            temperature: Clamped to [0.0, 0.2].
            model: Provider-specific model override.
            operation_id: Optional correlation ID / trigger name for telemetry.

        Returns:
            Parsed JSON dict, or None when all providers fail.
        """
        provider = self._get_provider(task)
        if provider is None:
            logger.debug("[LLMGateway] No available provider for multimodal task=%s", task)
            return None

        actual_model = str(model or getattr(provider, "_default_model", "default"))
        op_id = operation_id or f"op_{uuid.uuid4().hex[:10]}"
        interaction_id = f"ix_{uuid.uuid4().hex[:10]}"

        logger.debug(
            "[LLMGateway] multimodal task=%s → provider=%s (op=%s)",
            task,
            provider.provider_name,
            op_id,
        )

        start_time = time.perf_counter()
        success = True
        err_msg = None
        result: Optional[Dict[str, Any]] = None

        try:
            result = await provider.generate_multimodal(
                prompt,
                image_bytes,
                temperature=temperature,
                model=model,
            )
            if result is None:
                success = False
                err_msg = getattr(provider, "last_error", None) or "Provider returned None / empty response"
        except Exception as exc:
            success = False
            err_msg = str(exc)
            result = None
        finally:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            # Standard vision token base: ~258 tokens per high-res tile + prompt text
            prompt_tokens = max(1, (len(prompt) // 4) + 258)
            resp_str = json.dumps(result) if result else ""
            completion_tokens = max(1, len(resp_str) // 4) if result else 0

            # If rejected at ingress (HTTP 4xx client error), zero tokens were billed by cloud provider
            if not success and err_msg and ("HTTP 4" in err_msg or "INVALID_ARGUMENT" in err_msg):
                prompt_tokens = 0
                completion_tokens = 0

            get_llm_cost_tracker().record_interaction(
                interaction_id=interaction_id,
                operation_id=op_id,
                task=task,
                provider=provider.provider_name,
                model=actual_model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=success,
                error_message=err_msg,
            )

        return result

    async def classify(
        self,
        text: str,
        choices: List[str],
        *,
        task: str = "intent_routing",
        context: Optional[str] = None,
        model: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> Optional[DecisionResult]:
        """Classify input text against candidate choices using System 1 decision engine.

        If System 1 (TypeSafe / Jev) is unavailable or fails, automatically falls back
        to System 2 (Gemini / Claude) via structured JSON prompt.

        Args:
            text: Inbound message or query string.
            choices: Valid target choice labels or cartridge IDs.
            task: Task identifier string (e.g. 'intent_routing', 'fast_classification').
            context: Optional domain context or metadata.
            model: Optional model override.
            operation_id: Optional correlation ID for telemetry.

        Returns:
            DecisionResult with selected_choice, confidence, latency_ms, or None.
        """
        if not choices:
            return None

        provider = self._get_provider(task)
        op_id = operation_id or f"op_{uuid.uuid4().hex[:10]}"
        interaction_id = f"ix_{uuid.uuid4().hex[:10]}"
        start_time = time.perf_counter()

        # ── Primary: Direct System 1 Decision Model (TypeSafe / Jev) ────────────
        if isinstance(provider, BaseDecisionProvider) and provider.is_available():
            logger.debug(
                "[LLMGateway] System 1 classify task=%s → provider=%s choices=%s (op=%s)",
                task,
                provider.provider_name,
                choices,
                op_id,
            )
            result = await provider.classify(text, choices, context=context, model=model)
            if result is not None:
                # Record System 1 metric (~5 tokens per query)
                get_llm_cost_tracker().record_interaction(
                    interaction_id=interaction_id,
                    operation_id=op_id,
                    task=task,
                    provider=provider.provider_name,
                    model=model or getattr(provider, "_default_model", "jev-1"),
                    prompt_tokens=max(1, len(text) // 4 + len(str(choices)) // 4),
                    completion_tokens=5,
                    latency_ms=result.latency_ms,
                    success=True,
                    error_message=None,
                )
                return result

        # ── Secondary: System 2 Generative Fallback (Gemini / Claude) ──────────
        logger.debug(
            "[LLMGateway] Falling back to System 2 generative classification for task=%s (op=%s)",
            task,
            op_id,
        )
        choices_json = json.dumps(choices)
        prompt = (
            "You are a schema-constrained decision classifier. "
            f"Classify the following text into exactly ONE of these choices: {choices_json}.\n\n"
            f"Context: {context or 'None'}\n"
            f"Input text: {text[:500]}\n\n"
            "Return a single JSON object with exactly these keys: "
            '{"selected_choice": "<one_of_choices>", "confidence": <0.0-1.0>, "reasoning": "<brief explanation>"}'
        )

        gen_result = await self.generate(
            task="text_generation",
            prompt=prompt,
            temperature=0.0,
            operation_id=op_id,
        )
        if gen_result and "selected_choice" in gen_result and str(gen_result["selected_choice"]) in choices:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return DecisionResult(
                selected_choice=str(gen_result["selected_choice"]),
                confidence=float(gen_result.get("confidence", 0.85)),
                reasoning=str(gen_result.get("reasoning", "System 2 generative fallback")),
                latency_ms=latency_ms,
            )

        return None

    def get_health(self) -> List[Dict[str, Any]]:
        """Return health metadata for all registered providers.

        Returns:
            List of provider info dicts for /health endpoint.
        """
        return [p.get_provider_info() for p in self._providers.values()]


# ── Singleton ─────────────────────────────────────────────────────────────────

_gateway_instance: Optional[LLMGateway] = None
_gateway_lock = threading.Lock()


def get_platform_llm_gateway() -> LLMGateway:
    """Return the platform-level LLMGateway singleton.

    Lazy-initialised on first call using platform settings.
    All providers are instantiated from environment configuration.

    Returns:
        Shared LLMGateway singleton.
    """
    global _gateway_instance

    if _gateway_instance is None:
        with _gateway_lock:
            if _gateway_instance is None:
                _gateway_instance = _build_gateway()

    return _gateway_instance


def _build_gateway() -> LLMGateway:
    """Build and configure the LLMGateway from platform settings.

    Returns:
        Configured LLMGateway instance.
    """
    from core_platform.app.config import settings
    from core_platform.app.llm.claude_provider import ClaudeProvider
    from core_platform.app.llm.gemini_provider import GeminiProvider
    from core_platform.app.llm.ollama_provider import OllamaProvider
    from core_platform.app.llm.openai_provider import OpenAIProvider
    from core_platform.app.llm.typesafe_provider import TypeSafeProvider

    providers: Dict[str, BaseLLMProvider] = {
        "typesafe": TypeSafeProvider(
            api_key=getattr(settings, "TYPESAFE_API_KEY", ""),
            base_url=getattr(settings, "TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1"),
            default_model=getattr(settings, "TYPESAFE_MODEL", "jev-1"),
        ),
        "gemini": GeminiProvider(
            api_key=settings.GEMINI_API_KEY,
            default_model=settings.GEMINI_MODEL,
        ),
        "claude": ClaudeProvider(
            api_key=getattr(settings, "CLAUDE_API_KEY", ""),
            default_model=getattr(settings, "CLAUDE_MODEL", "claude-3-5-sonnet-20241022"),
        ),
        "openai": OpenAIProvider(
            api_key=getattr(settings, "OPENAI_API_KEY", ""),
            default_model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
        ),
        "ollama": OllamaProvider(
            base_url=getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434"),
            default_model=getattr(settings, "LOCAL_LLM_MODEL", "deepseek-r1:14b"),
        ),
    }

    gateway = LLMGateway(providers)

    # Apply per-task provider preferences from settings if specified.
    default_decision: str = getattr(settings, "DEFAULT_DECISION_PROVIDER", "typesafe")
    if default_decision:
        for task in ("intent_routing", "fast_classification"):
            gateway.configure_task(task, default_decision)

    default_provider: str = getattr(settings, "DEFAULT_LLM_PROVIDER", "gemini")
    if default_provider and default_provider != "gemini":
        for task in ("text_generation", "vision_processing"):
            gateway.configure_task(task, default_provider)

    logger.info(
        "[LLMGateway] Initialised with providers: %s | default_decision=%s | default_provider=%s",
        list(providers.keys()),
        default_decision,
        default_provider,
    )
    return gateway
