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
Anthropic Claude LLM Provider.

Implements BaseLLMProvider using Anthropic Messages REST API.
Uses stdlib urllib.request — zero additional dependencies.
HTTP calls are dispatched via asyncio.to_thread() to avoid blocking the event loop.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, cast

from core_platform.app.llm.base import BaseLLMProvider

logger = logging.getLogger("core_platform.llm.claude")

_CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude provider via Messages REST API."""

    provider_name: str = "claude"

    def __init__(
        self,
        api_key: str = "",
        default_model: str = "claude-3-5-sonnet-20241022",
        timeout_seconds: float = 15.0,
    ) -> None:
        """Initialise Claude provider.

        Args:
            api_key: Anthropic API key (sk-ant-...).
            default_model: Default Claude model identifier.
            timeout_seconds: HTTP request timeout.
        """
        self._api_key = api_key
        self._default_model = default_model
        self._timeout = timeout_seconds

    def is_available(self) -> bool:
        """Return True when an Anthropic API key is configured."""
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
        """Generate text response using Claude Messages API.

        Args:
            prompt: Task prompt.
            temperature: Clamped to [0.0, 0.2].
            response_mime_type: Unused for Claude (informational only).
            model: Model identifier override.
            system_instruction: System-level instruction string.

        Returns:
            Parsed JSON dict extracted from Claude's response, or None.
        """
        if not self.is_available():
            return None

        temperature = max(0.0, min(0.2, temperature))
        model_id = model or self._default_model

        payload: Dict[str, Any] = {
            "model": model_id,
            "max_tokens": 1024,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_instruction:
            payload["system"] = system_instruction

        return await asyncio.to_thread(self._post_json, payload)

    async def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Vision task via Claude (base64-encoded image in message content).

        Args:
            prompt: Vision prompt.
            image_bytes: Raw JPEG/PNG bytes.
            temperature: Clamped to [0.0, 0.2].
            model: Model identifier override.

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
            "max_tokens": 1024,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        return await asyncio.to_thread(self._post_json, payload)

    def _post_json(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST payload to Claude Messages API and extract text response.

        Args:
            payload: Request body dict.

        Returns:
            Parsed JSON dict or None on any error.
        """
        try:
            req = urllib.request.Request(
                _CLAUDE_API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self._api_key,
                    "anthropic-version": _ANTHROPIC_VERSION,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status == 200:
                    raw = json.loads(resp.read().decode("utf-8"))
                    text = raw.get("content", [{}])[0].get("text", "").strip()
                    if text:
                        try:
                            parsed = json.loads(text)
                            return cast(Dict[str, Any], parsed) if isinstance(parsed, dict) else {"raw_text": text}
                        except json.JSONDecodeError:
                            return {"raw_text": text}
        except urllib.error.HTTPError as exc:
            logger.warning("[ClaudeProvider] HTTP %s: %s", exc.code, exc.reason)
        except Exception as exc:
            logger.warning("[ClaudeProvider] Request failed: %s", exc)
        return None
