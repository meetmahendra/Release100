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
Ollama Local LLM Provider.

Implements BaseLLMProvider targeting a local Ollama / vLLM / LM Studio endpoint.
Ideal for air-gapped deployments and private-data processing (HR logs, legal docs).
Uses stdlib urllib.request — zero additional dependencies.
HTTP calls are dispatched via asyncio.to_thread() to avoid blocking the event loop.
"""

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, cast

from core_platform.app.llm.base import BaseLLMProvider

logger = logging.getLogger("core_platform.llm.ollama")


class OllamaProvider(BaseLLMProvider):
    """Local Ollama server provider (also compatible with LM Studio and vLLM).

    The provider is considered UNAVAILABLE when ``base_url`` is empty or when
    the Ollama server cannot be reached on the first call — no exception is raised.
    """

    provider_name: str = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "deepseek-r1:14b",
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialise Ollama provider.

        Args:
            base_url: Base URL of the Ollama REST endpoint.
            default_model: Default local model to use.
            timeout_seconds: HTTP request timeout (local inference can be slower).
        """
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout_seconds
        self._available: Optional[bool] = None  # Lazily evaluated, cached 60s
        self._last_check: float = 0.0

    def is_available(self) -> bool:
        """Return True when the Ollama server is reachable.

        Performs a lightweight GET /api/tags health check on first call,
        then caches the result for 60 seconds to avoid per-request probes.

        Returns:
            True when base_url is non-empty AND server responds HTTP 200.
        """
        if not self._base_url:
            return False

        now = time.monotonic()
        if self._available is not None and now - self._last_check < 60.0:
            return self._available

        try:
            req = urllib.request.Request(
                f"{self._base_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                self._available = resp.status == 200
        except Exception:
            self._available = False

        self._last_check = now
        return bool(self._available)

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        response_mime_type: str = "application/json",
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate text via Ollama /api/generate endpoint.

        Args:
            prompt: Task prompt.
            temperature: Clamped to [0.0, 0.2].
            response_mime_type: When "application/json", enables Ollama format=json.
            model: Model name override.
            system_instruction: System prompt prepended as a system message.

        Returns:
            Parsed JSON dict or None.
        """
        if not self.is_available():
            return None

        temperature = max(0.0, min(0.2, temperature))
        model_id = model or self._default_model

        full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        payload: Dict[str, Any] = {
            "model": model_id,
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if response_mime_type == "application/json":
            payload["format"] = "json"

        url = f"{self._base_url}/api/generate"
        return await asyncio.to_thread(self._post_json, url, payload)

    async def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Vision task via Ollama (llava-compatible models only).

        Args:
            prompt: Vision prompt.
            image_bytes: Raw JPEG/PNG bytes.
            temperature: Clamped to [0.0, 0.2].
            model: Model override (e.g. "llava:13b").

        Returns:
            Parsed dict or None.
        """
        import base64

        if not self.is_available():
            return None

        temperature = max(0.0, min(0.2, temperature))
        model_id = model or self._default_model
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload: Dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature},
        }
        url = f"{self._base_url}/api/generate"
        return await asyncio.to_thread(self._post_json, url, payload)

    def _post_json(self, url: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST JSON payload to Ollama and parse response.

        Args:
            url: Full endpoint URL.
            payload: Request body dict.

        Returns:
            Parsed JSON dict or None on any error.
        """
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status == 200:
                    raw = json.loads(resp.read().decode("utf-8"))
                    text = raw.get("response", "").strip()
                    if text:
                        try:
                            parsed = json.loads(text)
                            return cast(Dict[str, Any], parsed) if isinstance(parsed, dict) else {"raw_text": text}
                        except json.JSONDecodeError:
                            return {"raw_text": text}
        except ConnectionRefusedError:
            logger.debug("[OllamaProvider] Ollama server not running at %s", self._base_url)
            self._available = False
            self._last_check = time.monotonic()
        except Exception as exc:
            logger.warning("[OllamaProvider] Request failed: %s", exc)
        return None
