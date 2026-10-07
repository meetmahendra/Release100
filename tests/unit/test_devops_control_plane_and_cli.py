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
Unit tests for DevOps Multi-Tenant Control Plane CLI & Super-Admin Web Routes.
Validates:
1. CLI commands (provision, list, clone, transfer, set-byok, verify-audit, archive).
2. ASCII-safe CLI output formatting without unicode exceptions.
3. Super-Admin Web Dashboard RBAC privilege enforcement.
4. Web endpoints for full tenant lifecycle & BYOK key vault configuration.
5. Cryptographic SHA-256 tamper-evident audit inspection.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from sqlalchemy import select

from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.identity.models import Tenant, TenantAuditLog, TenantConfig
from core_platform.app.middleware.tenant_context import TenantContextMiddleware
from ops_control_plane.cli import build_parser, format_table
from ops_control_plane.devops_vault import DevOpsKeyVault
from ops_control_plane.super_admin.routes import router as ops_router
from ops_control_plane.tenant_lifecycle import TenantLifecycleManager


@pytest.fixture
def test_app() -> FastAPI:
    """Create a test FastAPI application with TenantContextMiddleware and DevOps Router."""
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)
    app.include_router(ops_router)
    return app


def test_format_table_ascii_safe() -> None:
    """Verify ASCII table formatting is safe and properly aligned."""
    headers = ["Slug", "Name", "Status"]
    rows = [["acme", "Acme Corp", "ACTIVE"], ["beta", "Beta Inc", "ARCHIVED"]]
    table_str = format_table(headers, rows)
    assert "Slug" in table_str
    assert "Acme Corp" in table_str
    assert "-+-" in table_str
    # Verify no unicode box chars
    assert "│" not in table_str
    assert "┌" not in table_str


def test_cli_lifecycle_end_to_end() -> None:
    """Verify end-to-end CLI commands."""
    import uuid
    slug = f"cli_{uuid.uuid4().hex[:6]}"
    clone_slug = f"{slug}_clone"

    parser = build_parser()

    # 1. Provision via CLI
    args_prov = parser.parse_args([
        "provision",
        "--slug", slug,
        "--name", "CLI Test Corp",
        "--admin-phone", "+919900112233",
        "--admin-name", "CLI Admin",
    ])
    code_prov = args_prov.func(args_prov)
    assert code_prov == 0

    # 2. Configure BYOK via CLI
    args_byok = parser.parse_args([
        "set-byok",
        "--slug", slug,
        "--gemini-key", "mock_synthetic_gemini_key_12345",
        "--waba-token", "mock_synthetic_waba_token_abcdef",
        "--waba-phone-id", "1092837465",
    ])
    code_byok = args_byok.func(args_byok)
    assert code_byok == 0

    # 3. Verify Audit Chain via CLI
    args_audit = parser.parse_args(["verify-audit", "--slug", slug])
    code_audit = args_audit.func(args_audit)
    assert code_audit == 0

    # 4. List Tenants via CLI
    args_list = parser.parse_args(["list-tenants"])
    code_list = args_list.func(args_list)
    assert code_list == 0

    # 5. Clone via CLI
    args_clone = parser.parse_args([
        "clone",
        "--source-slug", slug,
        "--target-slug", clone_slug,
    ])
    code_clone = args_clone.func(args_clone)
    assert code_clone == 0

    # 6. Archive via CLI
    args_arch = parser.parse_args(["archive", "--slug", slug])
    code_arch = args_arch.func(args_arch)
    assert code_arch == 0


def test_super_admin_web_rbac(test_app: FastAPI) -> None:
    """Verify customer admin cannot access /ops/tenants while DevOps super-admin can."""
    client = TestClient(test_app)

    # 1. Regular customer admin token
    customer_token = create_jwt_token(
        principal_id="customer_admin",
        roles=["admin"],
        permitted_apps=["mail_organizer"],
        tenant_id="customer_corp",
    )
    client.cookies.set("admin_token", customer_token)

    resp_forbidden = client.get("/ops/tenants")
    assert resp_forbidden.status_code == 403

    # 2. DevOps super-admin token
    devops_token = create_jwt_token(
        principal_id="devops_admin",
        roles=["admin", "devops_admin"],
        permitted_apps=["mail_organizer", "temperature_marker"],
        tenant_id="platform",
    )
    client.cookies.set("admin_token", devops_token)

    resp_allowed = client.get("/ops/tenants")
    assert resp_allowed.status_code == 200
    assert "DevOps Multi-Tenant Control Plane" in resp_allowed.text


def test_super_admin_web_lifecycle_flow(test_app: FastAPI) -> None:
    """Verify web actions for provision, vault configure, clone, and audit inspect."""
    import uuid
    slug = f"web_{uuid.uuid4().hex[:6]}"
    staging_slug = f"{slug}_staging"

    devops_token = create_jwt_token(
        principal_id="devops_admin",
        roles=["admin", "devops_admin"],
        permitted_apps=["mail_organizer", "temperature_marker"],
        tenant_id="platform",
    )

    client = TestClient(test_app)
    client.cookies.set("admin_token", devops_token)
    client.cookies.set("csrf_token", "test_csrf_token")

    # 1. Web Provision
    resp_prov = client.post(
        "/ops/tenants/provision",
        data={
            "slug": slug,
            "name": "Web Test Tenant",
            "admin_phone": "+919911223344",
            "admin_name": "Web Admin",
            "license_tier": "ENTERPRISE",
            "storage_region": "ap-south-1",
            "db_mode": "sqlite",
            "csrf_token": "test_csrf_token",
        },
        follow_redirects=False,
    )
    assert resp_prov.status_code == 303

    # 2. Web Vault BYOK Configuration
    resp_vault = client.post(
        f"/ops/tenants/{slug}/vault",
        data={
            "credential_mode": "CUSTOMER_BYOK",
            "gemini_api_key": "mock_synthetic_gemini_test_key_99999",
            "waba_access_token": "mock_synthetic_waba_test_token_88888",
            "waba_phone_number_id": "9988776655",
            "csrf_token": "test_csrf_token",
        },
        follow_redirects=False,
    )
    assert resp_vault.status_code == 303

    # 3. Web Deep-Clone
    resp_clone = client.post(
        f"/ops/tenants/{slug}/clone",
        data={
            "target_slug": staging_slug,
            "target_name": "Web Test Staging",
            "csrf_token": "test_csrf_token",
        },
        follow_redirects=False,
    )
    assert resp_clone.status_code == 303

    # 4. Web Audit Trail View
    resp_audit = client.get(f"/ops/tenants/{slug}/audit")
    assert resp_audit.status_code == 200
    assert "SHA-256 Integrity Verified" in resp_audit.text
    assert "PROVISION" in resp_audit.text
