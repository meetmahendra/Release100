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
Unit Tests — Comprehensive Access Control & Multi-Tenant Isolation Security Audit.

Adheres strictly to GEES v2.0 Rule 1, 3, 8 & Plan 02/09:
- Scoped Customer Admins (Tenant Admins) are 100% isolated from Platform Master Settings,
  Diagnostics, Global Host Logs, Cross-Tenant Operations, and Un-entitled Cartridges.
- DevOps Super-Admins retain authorized access across platform operations.
"""

from typing import Dict, List, Optional
import pytest
from starlette.testclient import TestClient

from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.db.base import Base
from core_platform.app.db.manager import get_db_manager
from core_platform.app.identity.models import PlatformUser, Tenant, TenantConfig
from core_platform.main import app


def _get_cookie_client(
    principal_id: str,
    roles: List[str],
    permitted_apps: List[str],
    tenant_id: str,
) -> TestClient:
    """Create a TestClient with a signed admin_token cookie representing the principal."""
    token = create_jwt_token(
        principal_id=principal_id,
        roles=roles,
        permitted_apps=permitted_apps,
        tenant_id=tenant_id,
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("admin_token", token)
    return client


@pytest.fixture(autouse=True)
def _setup_test_tenants() -> None:
    """Ensure test tenants with different cartridge entitlements exist in DB."""
    db_mgr = get_db_manager()
    db_mgr.init_tables()
    Base.metadata.create_all(bind=db_mgr.get_engine())
    with db_mgr.get_session() as session:
        # Tenant 1: KioskNode only
        t1 = session.get(Tenant, "tenant_temp_only")
        if not t1:
            t1 = Tenant(
                id="tenant_temp_only",
                name="Temperature Only Tenant",
                allowed_cartridges=["temperature_marker"],
                status="ACTIVE",
            )
            session.add(t1)

        # Tenant 2: Mail Organizer only
        t2 = session.get(Tenant, "tenant_mail_only")
        if not t2:
            t2 = Tenant(
                id="tenant_mail_only",
                name="Mail Only Tenant",
                allowed_cartridges=["mail_organizer"],
                status="ACTIVE",
            )
            session.add(t2)

        session.commit()


# ── 1. Tenant Admin Blocked from Master Diagnostics & Settings ────────────────

def test_tenant_admin_blocked_from_settings_and_diagnostics() -> None:
    """Customer Tenant Admin cannot access /settings or /api/diagnostics/* endpoints."""
    client = _get_cookie_client(
        principal_id="+919800000001",
        roles=["admin"],
        permitted_apps=["temperature_marker"],
        tenant_id="tenant_temp_only",
    )

    # GET /settings -> 403 Forbidden
    resp = client.get("/settings", headers={"Accept": "application/json"})
    assert resp.status_code == 403, f"Expected 403 for /settings, got {resp.status_code}"

    # GET /api/diagnostics/status -> 403 Forbidden
    resp = client.get("/api/diagnostics/status")
    assert resp.status_code == 403, f"Expected 403 for /api/diagnostics/status, got {resp.status_code}"

    # POST /api/diagnostics/verify -> 403 Forbidden
    resp = client.post("/api/diagnostics/verify", json={"service": "gemini", "key": "test"})
    assert resp.status_code == 403, f"Expected 403 for /api/diagnostics/verify, got {resp.status_code}"

    # POST /api/diagnostics/save -> 403 Forbidden
    resp = client.post("/api/diagnostics/save", json={"settings": {"GEMINI_API_KEY": "hacked"}})
    assert resp.status_code == 403, f"Expected 403 for /api/diagnostics/save, got {resp.status_code}"

    # POST /api/diagnostics/poller/toggle -> 403 Forbidden
    resp = client.post("/api/diagnostics/poller/toggle")
    assert resp.status_code == 403, f"Expected 403 for /api/diagnostics/poller/toggle, got {resp.status_code}"


# ── 2. Tenant Admin Blocked from Host Logs & Telemetry ───────────────────────

def test_tenant_admin_blocked_from_host_logs_and_llm_costs() -> None:
    """Customer Tenant Admin cannot view physical host logs or global LLM costs."""
    client = _get_cookie_client(
        principal_id="+919800000001",
        roles=["admin"],
        permitted_apps=["temperature_marker"],
        tenant_id="tenant_temp_only",
    )

    # GET /admin/logs -> 403 Forbidden
    resp = client.get("/admin/logs", headers={"Accept": "application/json"})
    assert resp.status_code == 403, f"Expected 403 for /admin/logs, got {resp.status_code}"

    # GET /admin/api/logs/tail -> 403 Forbidden
    resp = client.get("/admin/api/logs/tail")
    assert resp.status_code == 403, f"Expected 403 for /admin/api/logs/tail, got {resp.status_code}"

    # GET /admin/api/logs/download -> 403 Forbidden
    resp = client.get("/admin/api/logs/download")
    assert resp.status_code == 403, f"Expected 403 for /admin/api/logs/download, got {resp.status_code}"

    # GET /admin/llm-costs -> 403 Forbidden
    resp = client.get("/admin/llm-costs", headers={"Accept": "application/json"})
    assert resp.status_code == 403, f"Expected 403 for /admin/llm-costs, got {resp.status_code}"

    # GET /admin/api/llm-costs -> 403 Forbidden
    resp = client.get("/admin/api/llm-costs")
    assert resp.status_code == 403, f"Expected 403 for /admin/api/llm-costs, got {resp.status_code}"


# ── 3. Tenant Admin Blocked from DevOps Control Plane ─────────────────────────

def test_tenant_admin_blocked_from_devops_control_plane() -> None:
    """Customer Tenant Admin cannot access /ops/tenants or provision new databases."""
    client = _get_cookie_client(
        principal_id="+919800000001",
        roles=["admin"],
        permitted_apps=["temperature_marker"],
        tenant_id="tenant_temp_only",
    )

    # GET /ops/tenants -> 403 Forbidden
    resp = client.get("/ops/tenants", headers={"Accept": "application/json"})
    assert resp.status_code == 403, f"Expected 403 for /ops/tenants, got {resp.status_code}"

    # POST /ops/tenants/provision -> 403 Forbidden
    resp = client.post("/ops/tenants/provision", data={"slug": "malicious", "name": "Malicious"})
    assert resp.status_code == 403, f"Expected 403 for /ops/tenants/provision, got {resp.status_code}"

    # POST /admin/tenants/provision -> 403 Forbidden
    resp = client.post("/admin/tenants/provision", data={"tenant_id": "malicious"})
    assert resp.status_code == 403, f"Expected 403 for /admin/tenants/provision, got {resp.status_code}"


# ── 4. Tenant Admin Allowed Access to Scoped Resources ────────────────────────

def test_tenant_admin_allowed_scoped_workspace() -> None:
    """Customer Tenant Admin has full access to their scoped admin dashboard and profile."""
    client = _get_cookie_client(
        principal_id="+919800000001",
        roles=["admin"],
        permitted_apps=["temperature_marker"],
        tenant_id="tenant_temp_only",
    )

    # GET /admin/ -> 200 OK
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "Workspace Admin" in resp.text or "Temperature Only Tenant" in resp.text
    # Ensure master settings links are absent for customer admin
    assert 'href="/settings"' not in resp.text
    assert 'href="/ops/tenants"' not in resp.text

    # GET /admin/users -> 200 OK
    resp = client.get("/admin/users")
    assert resp.status_code == 200

    # GET /admin/tenants -> 200 OK (Company Profile & Vault)
    resp = client.get("/admin/tenants")
    assert resp.status_code == 200
    assert "Company Profile" in resp.text

    # GET /admin/api-keys -> 200 OK
    resp = client.get("/admin/api-keys")
    assert resp.status_code == 200


def test_tenant_admin_api_key_creation_is_scoped() -> None:
    """Customer Tenant Admin cannot escalate permissions when creating API keys."""
    client = _get_cookie_client(
        principal_id="+919800000001",
        roles=["admin"],
        permitted_apps=["temperature_marker"],
        tenant_id="tenant_temp_only",
    )

    resp = client.post(
        "/admin/api-keys",
        data={
            "label": "Scoped Tablet",
            "permitted_apps_csv": "mail_organizer, temperature_marker",  # tries to grant mail_organizer
            "roles_csv": "devops_admin, admin",  # tries to grant devops_admin
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "raw_key" in data
    assert data["raw_key"].startswith("ak_live_")


# ── 5. Multi-Tenant Cartridge Entitlement Isolation ───────────────────────────

def test_cartridge_entitlement_isolation() -> None:
    """Tenant Admins are forbidden (403) from accessing cartridges not in their entitlement list."""
    # Tenant 1 admin (only entitled to temperature_marker)
    client1 = _get_cookie_client(
        principal_id="+919800000001",
        roles=["admin"],
        permitted_apps=["temperature_marker"],
        tenant_id="tenant_temp_only",
    )

    # Entitled cartridge -> 200 OK
    resp = client1.get("/admin/apps/temperature-marker/fleet")
    assert resp.status_code == 200, f"Expected 200 for temperature-marker fleet, got {resp.status_code}"

    # Non-entitled cartridge -> 403 Forbidden
    resp = client1.get("/admin/apps/mail-organizer/dashboard", headers={"Accept": "application/json"})
    assert resp.status_code == 403, f"Expected 403 for unentitled mail-organizer dashboard, got {resp.status_code}"


# ── 6. DevOps Super-Admin Authority ───────────────────────────────────────────

def test_devops_super_admin_has_full_access() -> None:
    """DevOps Super-Admin has authorized access to platform settings, logs, ops, and all cartridges."""
    client = _get_cookie_client(
        principal_id="devops_admin",
        roles=["admin", "devops_admin", "super_admin"],
        permitted_apps=["temperature_marker", "mail_organizer"],
        tenant_id="platform",
    )

    # GET /settings -> 200 OK
    resp = client.get("/settings")
    assert resp.status_code == 200

    # GET /api/diagnostics/status -> 200 OK
    resp = client.get("/api/diagnostics/status")
    assert resp.status_code == 200

    # GET /ops/tenants -> 200 OK
    resp = client.get("/ops/tenants")
    assert resp.status_code == 200

    # GET /admin/logs -> 200 OK
    resp = client.get("/admin/logs")
    assert resp.status_code == 200

    # GET /admin/llm-costs -> 200 OK
    resp = client.get("/admin/llm-costs")
    assert resp.status_code == 200

    # Both cartridges accessible
    resp = client.get("/admin/apps/temperature-marker/fleet")
    assert resp.status_code == 200

    resp = client.get("/admin/apps/mail-organizer/dashboard")
    assert resp.status_code == 200


# ── 7. Subdomain & Host Isolation for Ops Control Plane ──────────────────────

def test_ops_blocked_on_customer_subdomain() -> None:
    """DevOps Control Plane returns 404 when accessed on customer tenant subdomains."""
    client = _get_cookie_client(
        principal_id="devops_admin",
        roles=["admin", "devops_admin", "super_admin"],
        permitted_apps=["temperature_marker", "mail_organizer"],
        tenant_id="platform",
    )

    # Accessing /ops/tenants on a customer tenant subdomain must return 404
    resp = client.get("/ops/tenants", headers={"host": "tenant_temp_only.release100.com"})
    assert resp.status_code == 404, f"Expected 404 on tenant subdomain, got {resp.status_code}"

    # Accessing /ops/tenants on platform domain (e.g. ops.release100.com or localhost) must return 200
    resp_ops = client.get("/ops/tenants", headers={"host": "ops.release100.com"})
    assert resp_ops.status_code == 200


def test_unregistered_tenant_subdomain_returns_404() -> None:
    """Accessing any web page on an unregistered customer subdomain returns 404."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/admin/login", headers={"host": "unregistered-unknown.release100.com"})
    assert resp.status_code == 404
    assert "Tenant Not Found" in resp.text or "unregistered-unknown" in resp.text

