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
Google Gemini LLM Provider.

Implements BaseLLMProvider using Google's Generative Language REST API (v1beta).
Supports text-only and multimodal (vision) prompts with clamped temperature.
Uses stdlib urllib.request — zero additional dependencies beyond what is already present.
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

logger = logging.getLogger("core_platform.llm.gemini")

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider via public REST API."""

    provider_name: str = "gemini"

    def __init__(
        self,
        api_key: str = "",
        default_model: str = "gemini-2.5-flash",
        timeout_seconds: float = 12.0,
    ) -> None:
        """Initialise Gemini provider.

        Args:
            api_key: Google Generative Language API key.
            default_model: Default model identifier.
            timeout_seconds: HTTP request timeout.
        """
        self._api_key = api_key
        self._default_model = default_model
        self._timeout = timeout_seconds
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        """Return the most recent detailed error message, if any."""
        return self._last_error

    def is_available(self) -> bool:
        """Return True when an API key is configured and looks valid."""
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
        """Generate a structured JSON response from a text prompt.

        Args:
            prompt: The task prompt.
            temperature: Clamped to [0.0, 0.2] per GEES Layer 1.
            response_mime_type: Expected response MIME type.
            model: Model identifier override.
            system_instruction: Optional system-level instruction.

        Returns:
            Parsed dict, or None on any failure.
        """
        if not self.is_available():
            return None

        temperature = max(0.0, min(0.2, temperature))
        model_id = model or self._default_model
        url = f"{_GEMINI_BASE_URL}/{model_id}:generateContent?key={self._api_key}"

        contents: list[Dict[str, Any]] = [{"parts": [{"text": prompt}]}]
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": response_mime_type,
            },
        }
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

        return await asyncio.to_thread(self._post_json, url, payload)

    async def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        temperature: float = 0.0,
        mime_type: str = "image/jpeg",
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate structured output from prompt + image (vision OCR etc.).

        Args:
            prompt: Vision analysis prompt.
            image_bytes: Raw image bytes.
            temperature: Clamped to [0.0, 0.2].
            mime_type: MIME type of the image (e.g. "image/jpeg", "image/png").
            model: Model identifier override.

        Returns:
            Parsed dict, or None on failure.
        """
        if not self.is_available():
            return None

        temperature = max(0.0, min(0.2, temperature))
        model_id = model or self._default_model
        url = f"{_GEMINI_BASE_URL}/{model_id}:generateContent?key={self._api_key}"

        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_image,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        return await asyncio.to_thread(self._post_json, url, payload)

    def _post_json(self, url: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST JSON payload and parse response.

        Args:
            url: Full endpoint URL including API key.
            payload: Request body dict.

        Returns:
            Parsed response dict, or None on any error.
        """
        self._last_error = None
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
                    text_part = (
                        raw.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                        .strip()
                    )
                    if text_part:
                        try:
                            parsed = json.loads(text_part)
                            return cast(Dict[str, Any], parsed) if isinstance(parsed, dict) else {"raw_text": text_part}
                        except json.JSONDecodeError:
                            return {"raw_text": text_part}
                    else:
                        cand = raw.get("candidates", [{}])[0]
                        reason = cand.get("finishReason", "EMPTY_CONTENT")
                        self._last_error = f"Gemini returned empty candidate (finishReason: {reason})"
                        logger.warning("[GeminiProvider] %s", self._last_error)
        except urllib.error.HTTPError as exc:
            err_msg = exc.reason or str(exc)
            try:
                body = exc.read().decode("utf-8")
                data = json.loads(body)
                err_msg = data.get("error", {}).get("message", err_msg)
            except Exception:
                pass
            self._last_error = f"HTTP {exc.code}: {err_msg}"
            logger.warning("[GeminiProvider] HTTP %s: %s", exc.code, err_msg)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("[GeminiProvider] Request failed: %s", exc)
        return None
