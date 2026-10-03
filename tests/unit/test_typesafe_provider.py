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
Unit tests for TypeSafe AI / Jev System 1 Provider and Dual-Tier Gateway.
Adheres strictly to GEES v2.0 with mocked HTTP boundaries and synthetic fixtures.
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core_platform.app.llm.base import DecisionResult
from core_platform.app.llm.gateway import LLMGateway
from core_platform.app.llm.typesafe_provider import TypeSafeProvider


def _build_mock_response(status_code: int, json_data: Dict[str, Any]) -> MagicMock:
    """Build mock httpx.Response object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.text = str(json_data)
    return mock_resp


@pytest.mark.anyio
async def test_typesafe_provider_availability() -> None:
    """Test availability check based on synthetic api_key and endpoint."""
    p1 = TypeSafeProvider(api_key="")
    assert p1.is_available() is False

    p2 = TypeSafeProvider(api_key="mock_typesafe_key_12345")
    assert p2.is_available() is True
    assert p2.provider_name == "typesafe"

    info = p2.get_provider_info()
    assert info["provider_name"] == "typesafe"
    assert info["available"] is True
    assert info["tier"] == "system_1"


@pytest.mark.anyio
async def test_typesafe_provider_classify_success() -> None:
    """Test successful schema-constrained classification in TypeSafeProvider."""
    provider = TypeSafeProvider(
        api_key="mock_typesafe_test_key_abc",
        base_url="https://api.typesafe.ai/v1",
        default_model="jev-latest",
    )

    mock_json = {
        "model": "jev-latest",
        "answers": {
            "decision": {
                "type": "choice",
                "choice": "temperature_marker",
                "probability": 0.98,
                "scores": {"temperature_marker": 0.98, "mail_organizer": 0.02},
                "reasoning": "Detected temperature check inquiry",
            }
        },
        "usage": {"input_tokens": 40, "output_tokens": 5},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _build_mock_response(200, mock_json)

        result = await provider.classify(
            text="Please record my morning temperature punch",
            choices=["temperature_marker", "mail_organizer"],
            context="Multi-cartridge routing",
        )

        assert result is not None
        assert isinstance(result, DecisionResult)
        assert result.selected_choice == "temperature_marker"
        assert result.confidence == 0.98
        assert result.reasoning == "Detected temperature check inquiry"
        assert result.raw_scores == {"temperature_marker": 0.98, "mail_organizer": 0.02}
        assert result.latency_ms >= 0.0


@pytest.mark.anyio
async def test_typesafe_provider_classify_legacy_flat_format() -> None:
    """Test backward compatibility with legacy flat JSON response."""
    provider = TypeSafeProvider(
        api_key="mock_typesafe_test_key_abc",
        base_url="https://api.typesafe.ai/v1",
    )

    mock_json = {
        "selected_choice": "mail_organizer",
        "confidence": 0.94,
        "reasoning": "Triage request",
        "scores": {"mail_organizer": 0.94, "temperature_marker": 0.06},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _build_mock_response(200, mock_json)

        result = await provider.classify(
            text="Sort my unread emails",
            choices=["temperature_marker", "mail_organizer"],
        )

        assert result is not None
        assert result.selected_choice == "mail_organizer"
        assert result.confidence == 0.94


@pytest.mark.anyio
async def test_typesafe_provider_classify_failure_and_edge_cases() -> None:
    """Test empty choices, HTTP errors, and offline exceptions."""
    provider = TypeSafeProvider(api_key="mock_typesafe_key_12345")

    # Empty choices
    assert await provider.classify("hello", []) is None

    # HTTP 500 error
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _build_mock_response(500, {"error": "Internal Server Error"})
        res = await provider.classify("test", ["choice_a", "choice_b"])
        assert res is None
        assert "HTTP 500" in (provider.last_error or "")

    # Network exception
    with patch("httpx.AsyncClient.post", side_effect=Exception("Network timeout")):
        res_ex = await provider.classify("test", ["choice_a", "choice_b"])
        assert res_ex is None
        assert "Network timeout" in (provider.last_error or "")


@pytest.mark.anyio
async def test_typesafe_provider_generate_adapter() -> None:
    """Test evaluate/generate text generation adapter."""
    provider = TypeSafeProvider(api_key="mock_typesafe_key_12345")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _build_mock_response(200, {"decision": "approved", "confidence": 0.99})
        res = await provider.generate("Evaluate risk for this action")
        assert res == {"decision": "approved", "confidence": 0.99}

    # Multimodal delegation to System 2
    mm_res = await provider.generate_multimodal("analyze image", b"fake_bytes")
    assert mm_res is None


@pytest.mark.anyio
async def test_llm_gateway_dual_tier_routing() -> None:
    """Test LLMGateway fast classification via System 1 with fallback to System 2."""
    typesafe_mock = TypeSafeProvider(api_key="mock_typesafe_key_12345")
    gemini_mock = MagicMock()
    gemini_mock.provider_name = "gemini"
    gemini_mock.is_available.return_value = True

    gateway = LLMGateway(providers={"typesafe": typesafe_mock, "gemini": gemini_mock})

    # Test 1: System 1 (TypeSafe) handles classification
    with patch.object(typesafe_mock, "classify", new_callable=AsyncMock) as mock_ts_classify:
        mock_ts_classify.return_value = DecisionResult(
            selected_choice="mail_organizer",
            confidence=0.96,
            reasoning="Email triage request",
            latency_ms=12.5,
        )

        res = await gateway.classify(
            text="Sort my unread emails into folders",
            choices=["mail_organizer", "temperature_marker"],
            task="intent_routing",
        )
        assert res is not None
        assert res.selected_choice == "mail_organizer"
        assert res.confidence == 0.96
        assert mock_ts_classify.called

    # Test 2: System 1 fails/offline -> System 2 (Gemini fallback) generates structured choice
    with patch.object(typesafe_mock, "classify", new_callable=AsyncMock) as mock_ts_fail:
        mock_ts_fail.return_value = None

        with patch.object(gateway, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {
                "selected_choice": "temperature_marker",
                "confidence": 0.88,
                "reasoning": "Fallback reasoning",
            }

            res2 = await gateway.classify(
                text="Record my temperature punch",
                choices=["mail_organizer", "temperature_marker"],
                task="intent_routing",
            )
            assert res2 is not None
            assert res2.selected_choice == "temperature_marker"
            assert res2.confidence == 0.88
            assert mock_gen.called
