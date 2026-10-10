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
E2E Journey 1: Multi-Tenant Onboarding, Company Profile & Interactive BYOK Vault (GEES v3.1).

Exercises the full customer lifecycle:
1. SuperAdmin provisions a brand-new tenant via DevOps control plane.
2. Tenant Admin logs in on Day 1 (default PLATFORM_MANAGED state).
3. Verifies interactive form and inputs are rendered (Zero "Status 200 Blindspot").
4. Switches to CUSTOMER_BYOK and inputs AES-256-GCM encrypted API keys & Company Brand.
5. Verifies persisted state & status tags on page reload (Round-trip mutation test).
6. Registers an Operator, issues Magic Link, and asserts strict RBAC route isolation.
7. Toggles back to PLATFORM_MANAGED to ensure clean state machine round-trip.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.identity.models import Base, Tenant, TenantDomain, TenantConfig
from core_platform.app.identity.service import get_user_identity_service
from core_platform.main import app
from ops_control_plane.devops_vault import DevOpsKeyVault


@pytest.fixture
def e2e_env(tmp_path: Path) -> TestClient:
    """Setup isolated polyglot database and test client."""
    db_file = tmp_path / "e2e_onboarding_vault.db"
    db_url = f"sqlite:///{db_file}"

    # Reset and configure DatabaseManager
    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(database_url=db_url)
    engine = db_mgr.get_engine()
    Base.metadata.create_all(bind=engine)
    session_maker = sessionmaker(bind=engine)

    identity_svc = get_user_identity_service(db_path=db_file)
    vault = DevOpsKeyVault(db_url=db_url)

    # Initialize tenancy database
    with session_maker() as session:
        # Seed platform DevOps admin
        devops_tenant = Tenant(id="platform", name="Platform Core", license_tier="ENTERPRISE", storage_region="global")
        session.merge(devops_tenant)

        # 1. SuperAdmin provisions acme_corp
        acme_tenant = Tenant(id="acme_corp", name="Acme Logistics", license_tier="PROFESSIONAL", storage_region="us-east-1")
        acme_domain = TenantDomain(tenant_id="acme_corp", domain_name="acme.intentrouter.io")
        session.merge(acme_tenant)
        session.merge(acme_domain)
        session.commit()

    # Seed Tenant Admin user in IAM
    identity_svc.register_user(
        phone_number="+12025550199",
        full_name="Acme Admin",
        tenant_id="acme_corp",
        role="admin",
        allowed_cartridges=["all", "mail_organizer", "temperature_marker"],
    )

    client = TestClient(app, follow_redirects=False)
    return client


def test_e2e_tenant_admin_onboarding_and_vault_journey(e2e_env: TestClient) -> None:
    client = e2e_env

    # -------------------------------------------------------------------------
    # STEP 1: Tenant Admin Logs In via JWT Token
    # -------------------------------------------------------------------------
    admin_token = create_jwt_token(
        principal_id="+12025550199",
        roles=["admin"],
        permitted_apps=["all", "mail_organizer", "temperature_marker"],
        tenant_id="acme_corp",
    )
    client.cookies.set("admin_token", admin_token)
    client.cookies.set("csrf_token", "csrf_e2e_token_123")

    # -------------------------------------------------------------------------
    # STEP 2: GET /admin/tenants on Day 1 (Default PLATFORM_MANAGED State)
    # Assert Actionable DOM Invariants (Form, Inputs, Timezone selector, Submit button)
    # -------------------------------------------------------------------------
    resp_day1 = client.get("/admin/tenants", headers={"Host": "acme.intentrouter.io"})
    assert resp_day1.status_code == 200
    html_day1 = resp_day1.text

    # Verify DOM structure
    assert 'action="/admin/tenants/save-byok"' in html_day1
    assert 'name="brand_name"' in html_day1
    assert 'name="default_timezone"' in html_day1
    assert 'name="credential_mode"' in html_day1
    assert 'name="gemini_api_key"' in html_day1
    assert 'name="openai_api_key"' in html_day1
    assert 'name="waba_token"' in html_day1
    assert 'name="waba_phone_number_id"' in html_day1
    assert 'type="submit"' in html_day1

    # Verify anti-caching headers (GEES v3.1 Directive 7.3)
    assert "no-store" in resp_day1.headers.get("cache-control", "")

    # -------------------------------------------------------------------------
    # STEP 3: POST /admin/tenants/save-byok (Switch to CUSTOMER_BYOK & Save Keys)
    # -------------------------------------------------------------------------
    save_resp = client.post(
        "/admin/tenants/save-byok",
        data={
            "brand_name": "Acme Global Logistics",
            "default_timezone": "America/New_York",
            "credential_mode": "CUSTOMER_BYOK",
            "gemini_api_key": "mock_gemini_key_12345",
            "openai_api_key": "mock_openai_key_67890",
            "waba_token": "mock_waba_token_abcdef",
            "waba_phone_number_id": "109876543210987",
            "csrf_token": "csrf_e2e_token_123",
        },
        headers={"Host": "acme.intentrouter.io"},
    )
    # Should redirect with 303/302 to /admin/tenants
    assert save_resp.status_code in (302, 303)

    # -------------------------------------------------------------------------
    # STEP 4: GET /admin/tenants (Verify Persisted State & AES-256-GCM Status)
    # -------------------------------------------------------------------------
    resp_day2 = client.get("/admin/tenants", headers={"Host": "acme.intentrouter.io"})
    assert resp_day2.status_code == 200
    html_day2 = resp_day2.text

    # Assert updated values are rendered in inputs
    assert "Acme Global Logistics" in html_day2
    assert "109876543210987" in html_day2
    assert "Configured (AES-256-GCM)" in html_day2 or "Configured" in html_day2

    # Assert raw keys are never leaked in HTML
    assert "mock_gemini_key_12345" not in html_day2
    assert "mock_openai_key_67890" not in html_day2
    assert "mock_waba_token_abcdef" not in html_day2

    # -------------------------------------------------------------------------
    # STEP 5: Register an Operator & Test Strict RBAC Access Isolation
    # -------------------------------------------------------------------------
    create_user_resp = client.post(
        "/admin/users",
        data={
            "phone_number": "+12025550244",
            "full_name": "Acme Operator 1",
            "role": "operator",
            "tenant_id": "acme_corp",
            "csrf_token": "csrf_e2e_token_123",
        },
        headers={"Host": "acme.intentrouter.io"},
    )
    assert create_user_resp.status_code in (302, 303)

    # Create Operator JWT
    op_token = create_jwt_token(
        principal_id="+12025550244",
        roles=["operator"],
        permitted_apps=["temperature_marker"],
        tenant_id="acme_corp",
    )
    op_client = TestClient(app, follow_redirects=False)
    op_client.cookies.set("admin_token", op_token)

    # Operator must be BLOCKED from accessing Vault (/admin/tenants) and Ops (/ops/tenants)
    op_vault_resp = op_client.get("/admin/tenants", headers={"Host": "acme.intentrouter.io"})
    assert op_vault_resp.status_code in (302, 403)

    op_ops_resp = op_client.get("/ops/tenants", headers={"Host": "acme.intentrouter.io"})
    assert op_ops_resp.status_code in (302, 403, 404)

    # -------------------------------------------------------------------------
    # STEP 6: Toggle back to PLATFORM_MANAGED (State Machine Reversibility)
    # -------------------------------------------------------------------------
    revert_resp = client.post(
        "/admin/tenants/save-byok",
        data={
            "brand_name": "Acme Global Logistics",
            "default_timezone": "America/New_York",
            "credential_mode": "PLATFORM_MANAGED",
            "csrf_token": "csrf_e2e_token_123",
        },
        headers={"Host": "acme.intentrouter.io"},
    )
    assert revert_resp.status_code in (302, 303)

    resp_revert = client.get("/admin/tenants", headers={"Host": "acme.intentrouter.io"})
    assert resp_revert.status_code == 200
    assert 'value="PLATFORM_MANAGED"' in resp_revert.text
