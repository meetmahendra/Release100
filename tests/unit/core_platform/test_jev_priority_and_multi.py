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

"""Unit tests for Phase 1 [CODE-MARKER: CP-JEV-01..03]: Two-Lane Priority Semaphore & Multi-Question Jev Batching."""

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core_platform.app.llm.base import BaseLLMProvider, QuestionSpec
from core_platform.app.llm.gateway import LLMGateway
from core_platform.app.llm.typesafe_provider import TwoLanePriorityLimiter, TypeSafeProvider


class _DummySystem2Provider(BaseLLMProvider):
    provider_name = "gemini"

    def __init__(self, response: Optional[Dict[str, Any]] = None) -> None:
        self._resp = response

    def is_available(self) -> bool:
        return True

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        response_mime_type: str = "application/json",
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._resp

    async def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return None


@pytest.mark.asyncio
async def test_two_lane_priority_limiter_preempts_low_lane() -> None:
    """Verify HIGH priority lane increments active counter and LOW lane waits until HIGH finishes."""
    limiter = TwoLanePriorityLimiter(max_low_concurrency=1)
    execution_order: list[str] = []

    async def high_task() -> None:
        async with limiter.acquire("HIGH"):
            assert limiter.active_high_priority_count == 1
            execution_order.append("high_start")
            await asyncio.sleep(0.05)
            execution_order.append("high_end")

    async def low_task() -> None:
        await asyncio.sleep(0.01)
        async with limiter.acquire("LOW"):
            execution_order.append("low_ran")

    await asyncio.gather(high_task(), low_task())
    assert execution_order == ["high_start", "high_end", "low_ran"]
    assert limiter.active_high_priority_count == 0


@pytest.mark.asyncio
async def test_typesafe_provider_classify_multi_single_http_roundtrip() -> None:
    """Verify TypeSafeProvider.classify_multi batches multiple questions into one /systemone request."""
    provider = TypeSafeProvider(
        api_key="mock_typesafe_test_key_12345",
        base_url="https://api.typesafe.ai/v1",
        default_model="jev-latest",
    )
    questions = [
        QuestionSpec(
            question_id="category",
            instructions="Select email category",
            choices={"@Urgent": "Immediate blocker", "@Action": "Standard deliverable"},
        ),
        QuestionSpec(
            question_id="speech_act",
            instructions="Select speech act",
            choices={"REQUEST": "Direct request", "INFORM": "Informational"},
        ),
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "answers": {
            "category": {"choice": "@Urgent", "confidence": 0.96, "reasoning": "Production outage"},
            "speech_act": {"choice": "REQUEST", "confidence": 0.94, "reasoning": "Asks for immediate fix"},
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        res = await provider.classify_multi(
            "Production database is down, please restore immediately.",
            questions,
            context="Executive triage",
            priority_lane="LOW",
        )
        assert res is not None
        assert mock_post.call_count == 1
        assert res.answers["category"].selected_choice == "@Urgent"
        assert res.answers["category"].confidence == 0.96
        assert res.answers["speech_act"].selected_choice == "REQUEST"


@pytest.mark.asyncio
async def test_gateway_classify_multi_falls_back_to_system2() -> None:
    """Verify LLMGateway.classify_multi falls back to System 2 JSON when System 1 is unavailable."""
    unavailable_s1 = TypeSafeProvider(api_key="", base_url="https://api.typesafe.ai/v1")
    fallback_s2 = _DummySystem2Provider(
        response={
            "category": {"selected_choice": "@Action", "confidence": 0.89, "reasoning": "Fallback s2"},
            "speech_act": {"selected_choice": "COMMIT_PROMISE", "confidence": 0.91, "reasoning": "Promise detected"},
        }
    )
    gateway = LLMGateway({"typesafe": unavailable_s1, "gemini": fallback_s2})
    questions = [
        QuestionSpec(
            question_id="category",
            instructions="Pick category",
            choices={"@Action": "Actionable", "@Promotions": "Promo"},
        ),
        QuestionSpec(
            question_id="speech_act",
            instructions="Pick speech act",
            choices={"REQUEST": "Ask", "COMMIT_PROMISE": "Promise"},
        ),
    ]

    res = await gateway.classify_multi("I will send the signed contract by Friday.", questions, priority_lane="HIGH")
    assert res is not None
    assert res.answers["category"].selected_choice == "@Action"
    assert res.answers["speech_act"].selected_choice == "COMMIT_PROMISE"
