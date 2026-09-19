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
Unit tests for all pluggable LLM Providers, Gateway, and Semantic Router.
Adheres strictly to GEES v1.0 (with mocked HTTP boundaries).
"""

import io
import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest

from core_platform.app.llm.claude_provider import ClaudeProvider
from core_platform.app.llm.gateway import LLMGateway, get_platform_llm_gateway
from core_platform.app.llm.gemini_provider import GeminiProvider
from core_platform.app.llm.ollama_provider import OllamaProvider
from core_platform.app.llm.openai_provider import OpenAIProvider
from core_platform.app.routing.disambiguation import DisambiguationEngine
from core_platform.app.routing.semantic_router import (
    RoutingDecision,
    SemanticRouter,
    register_app_descriptor,
)


def _mock_http_response(body_dict: Dict[str, Any], status: int = 200) -> MagicMock:
    """Helper to mock urllib.request.urlopen response."""
    body_bytes = json.dumps(body_dict).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body_bytes
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


# ── Gemini Provider Tests ───────────────────────────────────────────────────

@pytest.mark.anyio
async def test_gemini_provider_generate_and_multimodal() -> None:
    """Test Gemini text generation and multimodal vision parsing."""
    provider = GeminiProvider(api_key="AIzaSyTestKey123")
    assert provider.is_available() is True
    assert provider.provider_name == "gemini"

    # Mock success text response
    mock_gemini_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps({"category": "@Action", "urgency": 8})}]
                }
            }
        ]
    }

    with patch("urllib.request.urlopen", return_value=_mock_http_response(mock_gemini_payload)):
        res = await provider.generate("Test prompt", temperature=0.1, system_instruction="Be concise")
        assert res is not None
        assert res.get("category") == "@Action"

    # Mock multimodal response
    with patch("urllib.request.urlopen", return_value=_mock_http_response(mock_gemini_payload)):
        res_mm = await provider.generate_multimodal("Describe image", b"\xff\xd8\xff\xe0test_jpeg")
        assert res_mm is not None
        assert res_mm.get("urgency") == 8

    # Unavailable provider check
    unavail_provider = GeminiProvider(api_key="")
    assert unavail_provider.is_available() is False
    assert await unavail_provider.generate("prompt") is None
    assert await unavail_provider.generate_multimodal("prompt", b"bytes") is None


# ── Claude Provider Tests ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_claude_provider_generate_and_multimodal() -> None:
    """Test Claude provider text generation and multimodal processing."""
    provider = ClaudeProvider(api_key="sk-ant-test-key-12345")
    assert provider.is_available() is True
    assert provider.provider_name == "claude"

    mock_claude_payload = {
        "content": [{"text": json.dumps({"classification": "urgent", "score": 9})}]
    }

    with patch("urllib.request.urlopen", return_value=_mock_http_response(mock_claude_payload)):
        res = await provider.generate("Classify this email", system_instruction="Sys prompt")
        assert res is not None
        assert res.get("classification") == "urgent"

    with patch("urllib.request.urlopen", return_value=_mock_http_response(mock_claude_payload)):
        res_mm = await provider.generate_multimodal("Analyze image", b"fake_img")
        assert res_mm is not None
        assert res_mm.get("score") == 9

    # Unavailable
    unavail = ClaudeProvider(api_key="")
    assert unavail.is_available() is False
    assert await unavail.generate("prompt") is None


# ── OpenAI Provider Tests ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_openai_provider_generate_and_multimodal() -> None:
    """Test OpenAI provider text generation and multimodal processing."""
    provider = OpenAIProvider(api_key="sk-test-openai-key-12345")
    assert provider.is_available() is True
    assert provider.provider_name == "openai"

    mock_openai_payload = {
        "choices": [{"message": {"content": json.dumps({"result": "success", "tokens": 42})}}]
    }

    with patch("urllib.request.urlopen", return_value=_mock_http_response(mock_openai_payload)):
        res = await provider.generate("Hello OpenAI", response_mime_type="application/json")
        assert res is not None
        assert res.get("result") == "success"

    with patch("urllib.request.urlopen", return_value=_mock_http_response(mock_openai_payload)):
        res_mm = await provider.generate_multimodal("Vision prompt", b"img_bytes")
        assert res_mm is not None
        assert res_mm.get("tokens") == 42

    unavail = OpenAIProvider(api_key="")
    assert unavail.is_available() is False
    assert await unavail.generate("prompt") is None


# ── Ollama Provider Tests ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_ollama_provider_generate_and_multimodal() -> None:
    """Test local Ollama provider text and vision endpoints."""
    provider = OllamaProvider(base_url="http://localhost:11434")
    assert provider.provider_name == "ollama"

    mock_ollama_payload = {
        "response": json.dumps({"local_status": "ok", "model": "deepseek-r1"})
    }

    # Mock both the health check probe (/api/tags) and the generate call.
    with patch("urllib.request.urlopen", return_value=_mock_http_response({"models": []}, status=200)):
        assert provider.is_available() is True

    with patch("urllib.request.urlopen", return_value=_mock_http_response(mock_ollama_payload)):
        res = await provider.generate("Local inference", system_instruction="Private mode")
        assert res is not None
        assert res.get("local_status") == "ok"

    with patch("urllib.request.urlopen", return_value=_mock_http_response(mock_ollama_payload)):
        res_mm = await provider.generate_multimodal("Vision local", b"img")
        assert res_mm is not None
        assert res_mm.get("model") == "deepseek-r1"

    unavail = OllamaProvider(base_url="")
    assert unavail.is_available() is False
    assert await unavail.generate("prompt") is None


@pytest.mark.anyio
async def test_ollama_provider_offline_returns_false() -> None:
    """TECH-2: is_available() must return False when Ollama server is unreachable."""
    import urllib.error

    provider = OllamaProvider(base_url="http://localhost:11434")
    # Force cache invalidation
    provider._last_check = 0.0
    provider._available = None

    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
        result = provider.is_available()
        assert result is False
        assert provider._available is False

    # Confirm generate() also returns None when unavailable
    provider._last_check = 0.0
    provider._available = None
    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
        gen_result = await provider.generate("test")
        assert gen_result is None


@pytest.mark.anyio
async def test_ollama_availability_cached_60_seconds() -> None:
    """TECH-2: is_available() caches result for 60s to avoid per-request probes."""
    import time

    provider = OllamaProvider(base_url="http://localhost:11434")
    provider._last_check = 0.0
    provider._available = None

    with patch("urllib.request.urlopen", return_value=_mock_http_response({"models": []}, status=200)) as mock_url:
        provider.is_available()
        provider.is_available()  # Second call — should NOT probe again
        assert mock_url.call_count == 1  # Cached after first call

    # Expire cache and confirm re-probe happens
    provider._last_check = time.monotonic() - 61.0
    with patch("urllib.request.urlopen", return_value=_mock_http_response({"models": []}, status=200)) as mock_url2:
        provider.is_available()
        assert mock_url2.call_count == 1  # Re-probed after cache expiry


@pytest.mark.anyio
async def test_gemini_multimodal_mime_type_parameter() -> None:
    """TECH-1: generate_multimodal() must accept and pass through mime_type parameter."""
    provider = GeminiProvider(api_key="AIzaSyTestKey123")

    mock_payload = {
        "candidates": [{"content": {"parts": [{"text": json.dumps({"ok": True})}]}}]
    }

    captured_payloads: list[Any] = []

    def capture_urlopen(req: Any, timeout: float = 10.0) -> Any:
        import json as _json
        body = _json.loads(req.data.decode("utf-8"))
        captured_payloads.append(body)
        return _mock_http_response(mock_payload)

    with patch("urllib.request.urlopen", side_effect=capture_urlopen):
        await provider.generate_multimodal("Describe", b"\x89PNG", mime_type="image/png")

    assert len(captured_payloads) == 1
    inline = captured_payloads[0]["contents"][0]["parts"][1]["inline_data"]
    assert inline["mime_type"] == "image/png"  # Must NOT be hardcoded "image/jpeg"





# ── LLM Gateway Tests ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_llm_gateway_routing_and_fallback() -> None:
    """Test LLMGateway task dispatch, dynamic mapping, and fallback chain."""
    mock_gemini = GeminiProvider(api_key="key1")
    mock_ollama = OllamaProvider(base_url="http://localhost:11434")
    # Pre-seed availability so the health probe never fires in a unit test.
    import time as _time
    mock_ollama._available = True
    mock_ollama._last_check = _time.monotonic()

    # Mock provider generates
    async def mock_g_generate(*args: Any, **kwargs: Any) -> Dict[str, str]:
        return {"source": "gemini"}

    async def mock_o_generate(*args: Any, **kwargs: Any) -> Dict[str, str]:
        return {"source": "ollama"}

    mock_gemini.generate = mock_g_generate  # type: ignore[assignment]
    mock_ollama.generate = mock_o_generate  # type: ignore[assignment]

    gateway = LLMGateway(providers={"gemini": mock_gemini, "ollama": mock_ollama})

    # Default task routing
    res1 = await gateway.generate(task="intent_routing", prompt="Test")
    assert res1 == {"source": "gemini"}

    res2 = await gateway.generate(task="private_local_logs", prompt="Test logs")
    assert res2 == {"source": "ollama"}

    # Dynamic task override
    gateway.configure_task("intent_routing", "ollama")
    res3 = await gateway.generate(task="intent_routing", prompt="Test")
    assert res3 == {"source": "ollama"}

    # Multimodal routing
    async def mock_g_mm(*args: Any, **kwargs: Any) -> Dict[str, str]:
        return {"multimodal": "gemini"}

    mock_gemini.generate_multimodal = mock_g_mm  # type: ignore[assignment]
    res_mm = await gateway.generate_multimodal(task="vision_processing", prompt="look", image_bytes=b"123")
    assert res_mm == {"multimodal": "gemini"}

    # No available provider returns None
    empty_gateway = LLMGateway(providers={})
    assert await empty_gateway.generate(task="any", prompt="test") is None
    assert await empty_gateway.generate_multimodal(task="any", prompt="test", image_bytes=b"") is None


# ── Semantic Router & Disambiguation Tests ───────────────────────────────────

@pytest.mark.anyio
async def test_semantic_router_multi_app_and_fallback() -> None:
    """Test SemanticRouter LLM intent routing and keyword fallback."""
    register_app_descriptor("app_a", "Handles sales and invoices.")
    register_app_descriptor("app_b", "Handles customer support.")

    # 1. LLM routing success
    mock_routing_res = {
        "selected_app": "temperature_marker",
        "confidence": 0.88,
        "reasoning": "User mentioned chiller temperature check",
        "intent_category": "attendance",
    }
    with patch("core_platform.app.llm.gateway.LLMGateway.generate", return_value=mock_routing_res):
        decision = await SemanticRouter.route(
            text_content="Check temperature at kiosk 1",
            candidate_apps=["temperature_marker", "mail_organizer"],
        )
        assert decision.selected_app == "temperature_marker"
        assert decision.confidence == 0.88
        assert decision.requires_disambiguation is False

    # 2. LLM routing with low confidence triggers disambiguation
    mock_low_conf = {
        "selected_app": "temperature_marker",
        "confidence": 0.60,
        "reasoning": "Unclear intent",
        "intent_category": "ambiguous",
    }
    with patch("core_platform.app.llm.gateway.LLMGateway.generate", return_value=mock_low_conf):
        decision2 = await SemanticRouter.route(
            text_content="Help me with something",
            candidate_apps=["temperature_marker", "mail_organizer"],
        )
        assert decision2.requires_disambiguation is True

    # 3. Deterministic keyword fallback
    kw_decision = SemanticRouter._keyword_fallback(
        "Please triage this email draft and update jira",
        ["temperature_marker", "mail_organizer"],
    )
    assert kw_decision.selected_app == "mail_organizer"
    assert kw_decision.confidence == 0.7

    # 4. Disambiguation engine keyword resolution
    resolved = DisambiguationEngine.resolve_selection(
        "attendance checkin",
        ["temperature_marker", "mail_organizer"],
    )
    assert resolved == "temperature_marker"

    # 5. Disambiguation engine numeric selection ("1", "2") and out of bounds
    assert DisambiguationEngine.resolve_selection("1", ["temperature_marker", "mail_organizer"]) == "temperature_marker"
    assert DisambiguationEngine.resolve_selection("2", ["temperature_marker", "mail_organizer"]) == "mail_organizer"
    assert DisambiguationEngine.resolve_selection("99", ["temperature_marker", "mail_organizer"]) == "temperature_marker"
    assert DisambiguationEngine.resolve_selection("gibberish_unknown", ["temperature_marker", "mail_organizer"]) == "temperature_marker"

    # 6. Semantic router empty text media-only path
    media_decision = await SemanticRouter.route(
        text_content="",
        candidate_apps=["temperature_marker", "mail_organizer"],
    )
    assert media_decision.selected_app == "temperature_marker"
    assert media_decision.intent_category == "media_only"

    # 7. Keyword fallback with no keywords matched (defaults with confidence 0.7)
    unmatched_decision = SemanticRouter._keyword_fallback(
        "the quick brown fox jumps over the lazy dog",
        ["temperature_marker", "mail_organizer"],
    )
    assert unmatched_decision.selected_app == "temperature_marker"
    assert unmatched_decision.requires_disambiguation is False


