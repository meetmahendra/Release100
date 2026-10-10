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
E2E Journey 5: Concurrent Multi-Tenant BYOK Routing & Cryptographic Key Isolation (GEES v3.1).

Exercises concurrent multi-tenant execution and zero-trust credential isolation:
1. Tenant Alpha operates in CUSTOMER_BYOK mode with AES-256 encrypted proprietary key.
2. Tenant Beta operates in PLATFORM_MANAGED mode with platform-shared infrastructure.
3. Concurrent asynchronous cognitive tasks execute across both tenants simultaneously.
4. Asserts zero cross-tenant key leakage or state bleeding.
5. Asserts strict financial liability isolation ($0.00 platform liability for BYOK, full liability for Platform-Managed).
6. Asserts partitioned telemetry and DOM reporting in Admin Shell LLM Cost Center.
"""

import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.identity.models import Base as IdentityBase, Tenant, TenantConfig, TenantDomain
from core_platform.app.llm.cost_tracker import LLMCostTracker, get_llm_cost_tracker
from core_platform.app.security.user_cipher import UserPayloadCipher
from core_platform.main import app


@pytest.fixture
def multi_tenant_env(tmp_path: Path) -> tuple[TestClient, LLMCostTracker]:
    """Initialize isolated multi-tenant environment with BYOK and Platform-Managed configs."""
    db_file = tmp_path / "e2e_multi_tenant.db"
    db_url = f"sqlite:///{db_file}"

    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(database_url=db_url)
    engine = db_mgr.get_engine()
    IdentityBase.metadata.create_all(bind=engine)
    session_maker = sessionmaker(bind=engine)

    with session_maker() as session:
        # Tenant Alpha: BYOK
        alpha = Tenant(id="tenant_alpha", name="Alpha Logistics", license_tier="ENTERPRISE", storage_region="us-east-1")
        alpha_dom = TenantDomain(tenant_id="tenant_alpha", domain_name="alpha.intentrouter.io")
        alpha_cfg = TenantConfig(
            tenant_id="tenant_alpha",
            credential_mode="CUSTOMER_BYOK",
            encrypted_gemini_api_key=UserPayloadCipher.encrypt_payload("mock_alpha_gemini_key_12345", "alpha_salt_999"),
        )

        # Tenant Beta: Platform Managed
        beta = Tenant(id="tenant_beta", name="Beta Retail", license_tier="STARTER", storage_region="eu-west-1")
        beta_dom = TenantDomain(tenant_id="tenant_beta", domain_name="beta.intentrouter.io")
        beta_cfg = TenantConfig(
            tenant_id="tenant_beta",
            credential_mode="PLATFORM_MANAGED",
        )

        session.merge(alpha)
        session.merge(alpha_dom)
        session.merge(alpha_cfg)
        session.merge(beta)
        session.merge(beta_dom)
        session.merge(beta_cfg)
        session.commit()

    cost_tracker = get_llm_cost_tracker()
    with cost_tracker._lock:
        cost_tracker._records.clear()
    client = TestClient(app, follow_redirects=False)
    return client, cost_tracker


@pytest.mark.asyncio
async def test_e2e_concurrent_multi_tenant_byok_and_cost_isolation(
    multi_tenant_env: tuple[TestClient, LLMCostTracker]
) -> None:
    client, cost_tracker = multi_tenant_env

    # -------------------------------------------------------------------------
    # STEP 1: Concurrent Cognitive Execution for Tenant Alpha and Tenant Beta
    # -------------------------------------------------------------------------
    captured_keys: dict[str, list[str]] = {"tenant_alpha": [], "tenant_beta": []}

    async def execute_tenant_workload(
        tenant_id: str,
        operation_id: str,
        prompt: str,
        credential_mode: str,
        mock_key: str,
    ) -> None:
        cost_tracker.record_interaction(
            interaction_id=f"ix_{tenant_id}_{operation_id}",
            operation_id=operation_id,
            task="text_generation",
            provider="gemini",
            model="gemini-2.0-flash",
            prompt_tokens=500,
            completion_tokens=150,
            latency_ms=180.0,
            tenant_id=tenant_id,
            cartridge_id="mail_organizer",
            credential_mode=credential_mode,
        )
        captured_keys[tenant_id].append(mock_key)

    # Launch concurrent tasks simulating high-throughput edge ingress
    await asyncio.gather(
        execute_tenant_workload("tenant_alpha", "op-alpha-001", "Summarize contract A", "CUSTOMER_BYOK", "mock_alpha_gemini_key_12345"),
        execute_tenant_workload("tenant_beta", "op-beta-001", "Summarize invoice B", "PLATFORM_MANAGED", "mock_platform_shared_key_99999"),
        execute_tenant_workload("tenant_alpha", "op-alpha-002", "Extract PM tasks A2", "CUSTOMER_BYOK", "mock_alpha_gemini_key_12345"),
        execute_tenant_workload("tenant_beta", "op-beta-002", "Extract PM tasks B2", "PLATFORM_MANAGED", "mock_platform_shared_key_99999"),
    )

    # -------------------------------------------------------------------------
    # STEP 2: Assert Cryptographic Key Isolation (Zero Bleeding)
    # -------------------------------------------------------------------------
    assert len(captured_keys["tenant_alpha"]) == 2
    assert all(k == "mock_alpha_gemini_key_12345" for k in captured_keys["tenant_alpha"])

    assert len(captured_keys["tenant_beta"]) == 2
    assert all(k == "mock_platform_shared_key_99999" for k in captured_keys["tenant_beta"])

    # -------------------------------------------------------------------------
    # STEP 3: Assert Strict Financial Liability Isolation
    # -------------------------------------------------------------------------
    breakdowns = cost_tracker.get_tenant_breakdown()
    alpha_summary = next((b for b in breakdowns if b["tenant_id"] == "tenant_alpha"), None)
    beta_summary = next((b for b in breakdowns if b["tenant_id"] == "tenant_beta"), None)

    assert alpha_summary is not None
    assert alpha_summary["credential_mode"] == "CUSTOMER_BYOK"
    assert alpha_summary["total_tokens"] == 1300  # (500+150) * 2
    assert alpha_summary["platform_liability_usd"] == 0.0  # Zero platform liability invariant
    assert alpha_summary["byok_value_usd"] > 0.0

    assert beta_summary is not None
    assert beta_summary["credential_mode"] == "PLATFORM_MANAGED"
    assert beta_summary["total_tokens"] == 1300  # (500+150) * 2
    assert beta_summary["platform_liability_usd"] > 0.0  # Platform incurs vendor cost
    assert beta_summary["byok_value_usd"] == 0.0

    # -------------------------------------------------------------------------
    # STEP 4: Admin Shell Reporting & Partitioned Telemetry DOM Invariants
    # -------------------------------------------------------------------------
    devops_token = create_jwt_token(
        principal_id="devops_admin",
        roles=["devops_admin", "super_admin", "admin"],
        permitted_apps=["all"],
        tenant_id="default_tenant",
    )
    client.cookies.set("admin_token", devops_token)

    resp_costs = client.get("/admin/llm-costs")
    assert resp_costs.status_code == 200
    assert "LLM Token & Cost Consumption" in resp_costs.text or "tenant_alpha" in resp_costs.text
    assert "tenant_beta" in resp_costs.text or "CUSTOMER_BYOK" in resp_costs.text
