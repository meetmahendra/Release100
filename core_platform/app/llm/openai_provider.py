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
OpenAI Chat Completions LLM Provider.

Implements BaseLLMProvider using OpenAI's Chat Completions REST API.
Uses stdlib urllib.request — zero additional dependencies.
HTTP calls are dispatched via asyncio.to_thread() to avoid blocking the event loop.
"""

import asyncio
import base64
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, cast

from core_platform.app.llm.base import BaseLLMProvider

logger = logging.getLogger("core_platform.llm.openai")

_OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Chat Completions provider."""

    provider_name: str = "openai"

    def __init__(
        self,
        api_key: str = "",
        default_model: str = "gpt-4o",
        timeout_seconds: float = 15.0,
    ) -> None:
        """Initialise OpenAI provider.

        Args:
            api_key: OpenAI API key (sk-...).
            default_model: Default model identifier.
            timeout_seconds: HTTP request timeout.
        """
        self._api_key = api_key
        self._default_model = default_model
        self._timeout = timeout_seconds

    def is_available(self) -> bool:
        """Return True when an OpenAI API key is configured."""
        return bool(self._api_key and not self._api_key.startswith("your_"))

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        response_mime_type: str = "application/json",
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate JSON-structured response via Chat Completions API.

        Args:
            prompt: Task prompt.
            temperature: Clamped to [0.0, 0.2].
            response_mime_type: When "application/json", enables JSON mode.
            model: Model identifier override.
            system_instruction: System message prepended to conversation.

        Returns:
            Parsed dict or None.
        """
        if not self.is_available():
            return None

        temperature = max(0.0, min(0.2, temperature))
        model_id = model or self._default_model
        messages: list[Dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model_id,
            "temperature": temperature,
            "messages": messages,
        }
        if response_mime_type == "application/json":
            payload["response_format"] = {"type": "json_object"}

        return await asyncio.to_thread(self._post, payload)

    async def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Vision task via GPT-4o Vision.

        Args:
            prompt: Vision analysis prompt.
            image_bytes: Raw JPEG/PNG bytes.
            temperature: Clamped to [0.0, 0.2].
            model: Model identifier override (defaults to gpt-4o).

        Returns:
            Parsed dict or None.
        """
        if not self.is_available():
            return None

        temperature = max(0.0, min(0.2, temperature))
        model_id = model or self._default_model
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload: Dict[str, Any] = {
            "model": model_id,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        }
        return await asyncio.to_thread(self._post, payload)

    def _post(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST to Chat Completions endpoint and extract JSON.

        Args:
            payload: Request body dict.

        Returns:
            Parsed JSON content from assistant message, or None.
        """
        try:
            req = urllib.request.Request(
                _OPENAI_API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status == 200:
                    raw = json.loads(resp.read().decode("utf-8"))
                    text = raw.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    if text:
                        try:
                            parsed = json.loads(text)
                            return cast(Dict[str, Any], parsed) if isinstance(parsed, dict) else {"raw_text": text}
                        except json.JSONDecodeError:
                            return {"raw_text": text}
        except urllib.error.HTTPError as exc:
            logger.warning("[OpenAIProvider] HTTP %s: %s", exc.code, exc.reason)
        except Exception as exc:
            logger.warning("[OpenAIProvider] Request failed: %s", exc)
        return None
