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
Unit tests for Universal Intelligence Skills (IntentClassifierSkill & SentimentUrgencySkill).
Adheres strictly to GEES v2.0 with mocked boundaries and synthetic fixtures.
"""

from unittest.mock import AsyncMock, patch
import pytest

from core_platform.app.errors import SkillExecutionError
from core_platform.app.llm.base import DecisionResult
from core_platform.app.skills.entity_extractor import EntityExtractorSkill
from core_platform.app.skills.intent_classifier import IntentClassifierSkill
from core_platform.app.skills.registry import SkillRegistry, get_platform_skill
from core_platform.app.skills.sentiment_urgency import (
    SentimentTier,
    SentimentUrgencySkill,
    UrgencyTier,
)


@pytest.mark.anyio
async def test_intent_classifier_skill_empty_and_error_cases() -> None:
    """Test IntentClassifierSkill handling empty inputs and empty valid intents."""
    skill = IntentClassifierSkill()
    assert skill.is_available() is True
    assert skill.skill_name == "intent_classifier"

    # Empty valid intents raises SkillExecutionError
    with pytest.raises(SkillExecutionError):
        await skill.classify_intent("hello", [])

    # Empty text returns first intent with confidence 0.5
    res = await skill.classify_intent("", ["intent_a", "intent_b"])
    assert res.selected_choice == "intent_a"
    assert res.confidence == 0.5


@pytest.mark.anyio
async def test_intent_classifier_skill_successful_decision() -> None:
    """Test IntentClassifierSkill successfully resolving intent via gateway."""
    skill = IntentClassifierSkill()
    mock_decision = DecisionResult(
        selected_choice="record_punch",
        confidence=0.97,
        reasoning="User requested attendance punch",
        latency_ms=10.2,
    )

    with patch("core_platform.app.llm.gateway.LLMGateway.classify", new_callable=AsyncMock, return_value=mock_decision):
        result = await skill.classify_intent(
            text="I want to punch in for the morning shift",
            valid_intents=["record_punch", "view_status", "device_help"],
            context="Attendance kiosk",
        )
        assert result.selected_choice == "record_punch"
        assert result.confidence == 0.97
        assert result.latency_ms == 10.2


@pytest.mark.anyio
async def test_intent_classifier_skill_keyword_fail_safe() -> None:
    """Test IntentClassifierSkill fail-safe keyword matching when gateway fails."""
    skill = IntentClassifierSkill()

    with patch("core_platform.app.llm.gateway.LLMGateway.classify", new_callable=AsyncMock, return_value=None):
        result = await skill.classify_intent(
            text="Please help me with device_help instructions",
            valid_intents=["record_punch", "view_status", "device_help"],
        )
        assert result.selected_choice == "device_help"
        assert result.confidence == 0.65


@pytest.mark.anyio
async def test_sentiment_urgency_skill_critical_bypass() -> None:
    """Test SentimentUrgencySkill instant critical bypass for emergency keywords."""
    skill = SentimentUrgencySkill()

    result = await skill.assess_triage("Emergency: boiler temperature severe failure alarm active!")
    assert result.urgency == UrgencyTier.CRITICAL
    assert result.sentiment == SentimentTier.ESCALATED
    assert result.requires_escalation is True
    assert result.confidence == 0.99


@pytest.mark.anyio
async def test_sentiment_urgency_skill_empty_text() -> None:
    """Test SentimentUrgencySkill empty text."""
    skill = SentimentUrgencySkill()

    result = await skill.assess_triage("   ")
    assert result.urgency == UrgencyTier.LOW
    assert result.sentiment == SentimentTier.NEUTRAL
    assert result.requires_escalation is False


@pytest.mark.anyio
async def test_sentiment_urgency_skill_gateway_classification() -> None:
    """Test SentimentUrgencySkill classification via gateway."""
    skill = SentimentUrgencySkill()
    mock_decision = DecisionResult(
        selected_choice="HIGH",
        confidence=0.91,
        reasoning="Critical customer complaint requiring immediate action",
        latency_ms=14.0,
    )

    with patch("core_platform.app.llm.gateway.LLMGateway.classify", new_callable=AsyncMock, return_value=mock_decision):
        result = await skill.assess_triage(
            text="Customer shipment is delayed by 3 weeks and order is at risk of cancellation",
            context="Email customer triage",
        )
        assert result.urgency == UrgencyTier.HIGH
        assert result.requires_escalation is True
        assert result.confidence == 0.91


@pytest.mark.anyio
async def test_entity_extractor_skill_regex_and_empty() -> None:
    """Test EntityExtractorSkill regex extraction on structured patterns."""
    skill = EntityExtractorSkill()
    assert skill.is_available() is True
    assert skill.skill_name == "entity_extractor"

    # Empty text
    empty_res = await skill.extract_entities("")
    assert empty_res.confidence == 1.0
    assert len(empty_res.dates) == 0

    # Text with patterns
    sample_text = (
        "Meeting on 2026-10-05 with john.doe@example.com to discuss ticket JIRA-4589. "
        "Contact operator at +919876543210."
    )
    res = await skill.extract_entities(sample_text)
    assert "2026-10-05" in res.dates
    assert "john.doe@example.com" in res.email_addresses
    assert "JIRA-4589" in res.ticket_ids
    assert any("9876543210" in p for p in res.phone_numbers)


@pytest.mark.anyio
async def test_entity_extractor_skill_custom_schema() -> None:
    """Test EntityExtractorSkill extracting custom schema via gateway."""
    skill = EntityExtractorSkill()
    mock_extracted = {"vendor_name": "Acme Industrial", "total_amount": 1500.0}

    with patch("core_platform.app.llm.gateway.LLMGateway.generate", new_callable=AsyncMock, return_value=mock_extracted):
        res = await skill.extract_entities(
            "Invoice from Acme Industrial for USD 1500.00",
            target_schema={"vendor_name": "Vendor name string", "total_amount": "Total invoice amount float"},
        )
        assert res.custom_entities == mock_extracted
        assert res.confidence >= 0.90


@pytest.mark.anyio
async def test_skill_registry_resolves_new_skills() -> None:
    """Test that SkillRegistry returns IntentClassifierSkill, SentimentUrgencySkill, and EntityExtractorSkill."""
    registry = SkillRegistry.get_instance()

    s1 = registry.get_skill("intent_classifier")
    assert isinstance(s1, IntentClassifierSkill)

    s2 = get_platform_skill("sentiment_urgency")
    assert isinstance(s2, SentimentUrgencySkill)

    s3 = get_platform_skill("entity_extractor")
    assert isinstance(s3, EntityExtractorSkill)

    health = registry.get_all_health_statuses()
    assert "intent_classifier" in health
    assert "sentiment_urgency" in health
    assert "entity_extractor" in health
