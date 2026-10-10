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
Unit Test Suite for Multi-Tenant LLM Cost Attribution & Product Optimization Analytics.

Verifies:
  1. Multi-tenant cost isolation: PLATFORM_MANAGED vs CUSTOMER_BYOK vs CORE_INTERNAL_JEV.
  2. Financial liability calculation: Customer BYOK incurs $0.00 platform liability.
  3. Core microkernel Jev tracking: Internal System 1 intent routing attribution.
  4. Workload hotspots & architectural recommendations.
  5. JSONL backward-compatibility serialization and replay.
  6. LLMGateway automated tenant context resolution.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from core_platform.app.llm.cost_tracker import (
    LLMCostTracker,
    LLMInteractionRecord,
)
from core_platform.app.llm.gateway import LLMGateway
from core_platform.app.middleware.tenant_context import set_current_tenant_id


def test_cost_tracker_multi_tenant_financial_isolation(tmp_path: Path) -> None:
    """Verify that PLATFORM_MANAGED, CUSTOMER_BYOK, and CORE_INTERNAL_JEV are strictly separated."""
    log_file = tmp_path / "test_costs.jsonl"
    tracker = LLMCostTracker(max_records=100, jsonl_log_path=log_file)

    # 1. Tenant A: Uses Platform-Managed Key (Platform incurs real cost)
    tracker.record_interaction(
        interaction_id="ix_tenant_a_01",
        operation_id="op_email_triage_1",
        task="text_generation",
        provider="gemini",
        model="gemini-2.5-flash",
        prompt_tokens=1000,
        completion_tokens=200,
        latency_ms=450.0,
        tenant_id="tenant_alpha",
        cartridge_id="mail_organizer",
        credential_mode="PLATFORM_MANAGED",
    )

    # 2. Tenant B: Uses Customer BYOK Key (Platform incurs $0.00 liability)
    tracker.record_interaction(
        interaction_id="ix_tenant_b_01",
        operation_id="op_chiller_ocr_1",
        task="vision_ocr",
        provider="gemini",
        model="gemini-2.5-flash",
        prompt_tokens=2000,
        completion_tokens=100,
        latency_ms=650.0,
        tenant_id="tenant_beta_logistics",
        cartridge_id="temperature_marker",
        credential_mode="CUSTOMER_BYOK",
    )

    # 3. Core Microkernel: Jev System 1 Intent Routing (Platform fixed compute)
    tracker.record_interaction(
        interaction_id="ix_core_jev_01",
        operation_id="op_router_inbound_1",
        task="intent_routing",
        provider="typesafe",
        model="jev-1",
        prompt_tokens=30,
        completion_tokens=5,
        latency_ms=8.5,
        tenant_id="platform",
        cartridge_id="core_router",
        credential_mode="CORE_INTERNAL_JEV",
    )

    summary = tracker.get_summary()
    assert summary["total_interactions"] == 3
    assert summary["total_tokens"] == (1200 + 2100 + 35)

    # Financial liability assertions
    # Tenant A (Platform-Managed) + Core Jev = Platform Liability
    # Tenant B (BYOK) = Customer Absorbed
    assert summary["total_platform_liability_usd"] > 0.0
    assert summary["total_byok_value_usd"] > 0.0
    assert summary["total_internal_jev_cost_usd"] > 0.0
    assert round(summary["total_platform_liability_usd"] + summary["total_byok_value_usd"], 4) == summary["total_cost_usd"]

    # Verify Tenant Breakdown
    tenant_report = tracker.get_tenant_breakdown()
    assert len(tenant_report) == 3

    beta_report = next(t for t in tenant_report if t["tenant_id"] == "tenant_beta_logistics")
    assert beta_report["credential_mode"] == "CUSTOMER_BYOK"
    assert beta_report["platform_liability_usd"] == 0.0
    assert beta_report["byok_value_usd"] > 0.0
    assert beta_report["cartridges_used"] == ["temperature_marker"]

    alpha_report = next(t for t in tenant_report if t["tenant_id"] == "tenant_alpha")
    assert alpha_report["credential_mode"] == "PLATFORM_MANAGED"
    assert alpha_report["platform_liability_usd"] > 0.0
    assert alpha_report["byok_value_usd"] == 0.0
    assert alpha_report["cartridges_used"] == ["mail_organizer"]


def test_product_optimization_insights(tmp_path: Path) -> None:
    """Verify workload hotspot detection and architectural recommendation generation."""
    tracker = LLMCostTracker(max_records=50, jsonl_log_path=tmp_path / "opt_test.jsonl")

    # Simulate high prompt volume in mail_organizer
    for i in range(6):
        tracker.record_interaction(
            interaction_id=f"ix_high_prompt_{i}",
            operation_id=f"op_bulk_{i}",
            task="email_triage",
            provider="gemini",
            model="gemini-1.5-pro",
            prompt_tokens=4500,
            completion_tokens=250,
            latency_ms=1800.0,
            cartridge_id="mail_organizer",
            credential_mode="PLATFORM_MANAGED",
        )

    # Simulate fast microkernel Jev routing
    for i in range(10):
        tracker.record_interaction(
            interaction_id=f"ix_jev_{i}",
            operation_id=f"op_route_{i}",
            task="intent_routing",
            provider="typesafe",
            model="jev-1",
            prompt_tokens=25,
            completion_tokens=5,
            latency_ms=6.0,
            cartridge_id="core_router",
            credential_mode="CORE_INTERNAL_JEV",
        )

    insights = tracker.get_product_optimization_insights()
    assert len(insights) == 2

    # High prompt mail_organizer insight
    mail_insight = next(ins for ins in insights if ins["cartridge_id"] == "mail_organizer")
    assert mail_insight["avg_prompt_tokens"] == 4500.0
    assert "prompt caching" in mail_insight["recommendation"].lower()

    # Jev microkernel insight
    jev_insight = next(ins for ins in insights if ins["cartridge_id"] == "core_router")
    assert "microkernel fast-path" in jev_insight["recommendation"].lower()


def test_legacy_jsonl_replay_backward_compatibility(tmp_path: Path) -> None:
    """Verify that older audit log files without new fields load cleanly without KeyError."""
    legacy_log = tmp_path / "legacy.jsonl"
    legacy_record = {
        "interaction_id": "ix_legacy_001",
        "operation_id": "op_legacy_op",
        "task": "text_generation",
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "prompt_tokens": 500,
        "completion_tokens": 100,
        "total_tokens": 600,
        "estimated_cost_usd": 0.000067,
        "latency_ms": 350.0,
        "success": True,
        "error_message": None,
        "timestamp": "2026-10-09T10:00:00Z",
    }
    legacy_log.write_text(json.dumps(legacy_record) + "\n", encoding="utf-8")

    tracker = LLMCostTracker(max_records=10, jsonl_log_path=legacy_log)
    assert len(tracker._records) == 1
    loaded = tracker._records[0]
    assert loaded.tenant_id == "default_tenant"
    assert loaded.cartridge_id == "core_platform"
    assert loaded.credential_mode == "PLATFORM_MANAGED"
    assert loaded.is_platform_liability is True


@pytest.mark.asyncio
async def test_gateway_context_resolution_and_attribution(tmp_path: Path) -> None:
    """Verify LLMGateway automatically binds active tenant and cartridge context without parameter boilerplate."""
    from core_platform.app.llm.base import BaseDecisionProvider, BaseLLMProvider, DecisionResult
    from core_platform.app.middleware.tenant_context import async_cartridge_scope

    class MockProvider(BaseLLMProvider, BaseDecisionProvider):
        @property
        def provider_name(self) -> str:
            return "typesafe"

        def is_available(self) -> bool:
            return True

        async def generate(self, prompt: str, **kwargs: object) -> dict[str, str]:
            return {"result": "success"}

        async def generate_multimodal(self, prompt: str, image_bytes: bytes, **kwargs: object) -> dict[str, str]:
            return {"reading": "25.0"}

        async def classify(self, text: str, choices: list[str], **kwargs: object) -> DecisionResult:
            return DecisionResult(selected_choice=choices[0], confidence=0.95, reasoning="mock", latency_ms=5.0)

    mock_prov = MockProvider()
    gateway = LLMGateway({"gemini": mock_prov, "typesafe": mock_prov})

    custom_log = tmp_path / "gateway_test.jsonl"
    with patch("core_platform.app.llm.gateway.get_llm_cost_tracker") as mock_get_tracker:
        test_tracker = LLMCostTracker(jsonl_log_path=custom_log)
        mock_get_tracker.return_value = test_tracker

        # 1. Set dynamic tenant context
        set_current_tenant_id("tenant_enterprise_xyz")

        # 2. Execute generation within clean async_cartridge_scope (ZERO telemetry args in caller)
        async with async_cartridge_scope("mail_organizer"):
            res = await gateway.generate(
                task="text_generation",
                prompt="Analyze payload",
            )
            assert res == {"result": "success"}

        # Verify recorded telemetry automatically bound tenant and cartridge
        assert len(test_tracker._records) == 1
        rec = test_tracker._records[0]
        assert rec.tenant_id == "tenant_enterprise_xyz"
        assert rec.cartridge_id == "mail_organizer"
        assert rec.credential_mode == "PLATFORM_MANAGED"
        assert rec.is_platform_liability is True

        # 3. Test Core Jev Intent Routing automatically resolves CORE_INTERNAL_JEV
        async with async_cartridge_scope("core_router"):
            dec = await gateway.classify(
                text="schedule email",
                choices=["mail_organizer", "temperature_marker"],
                task="intent_routing",
            )
            assert dec is not None

        assert len(test_tracker._records) == 2
        rec_jev = test_tracker._records[1]
        assert rec_jev.cartridge_id == "core_router"
        assert rec_jev.credential_mode == "CORE_INTERNAL_JEV"
        assert rec_jev.is_platform_liability is True
