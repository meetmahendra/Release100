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

"""Unit tests for GEES Data Sovereignty and Role Segregation invariants."""

import pytest
from fastapi.testclient import TestClient

from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.ui.nav_builder import compose_nav
from core_platform.main import app


def test_devops_nav_segregation() -> None:
    """Verify compose_nav segregates DevOps platform operations from customer single-tenant workspace."""
    devops_ctx = SecurityContext(
        principal_id="devops_admin",
        tenant_id="platform",
        user_roles=["devops_admin", "super_admin"],
        is_authenticated=True,
    )
    customer_admin_ctx = SecurityContext(
        principal_id="customer_admin",
        tenant_id="acme_corp",
        user_roles=["admin"],
        is_authenticated=True,
    )

    devops_items = compose_nav(devops_ctx, allowed_apps=["mail_organizer", "temperature_marker"])
    devops_paths = [i.path for i in devops_items]

    # DevOps MUST see platform ops and diagnostics
    assert "/ops/tenants" in devops_paths
    assert "/ops/daemons" in devops_paths
    assert "/settings" in devops_paths
    assert "/admin/llm-costs" in devops_paths
    assert "/admin/logs" in devops_paths
    assert "/admin/api-keys" in devops_paths

    # DevOps MUST NOT see customer workspace or customer cartridges
    assert "/admin/users" not in devops_paths
    assert "/admin/tenants" not in devops_paths
    assert not any(p.startswith("/admin/apps/") for p in devops_paths)

    # Customer Admin MUST see domain cartridges and tenant workspace
    customer_items = compose_nav(customer_admin_ctx, allowed_apps=["mail_organizer", "temperature_marker"])
    customer_paths = [i.path for i in customer_items]

    assert "/admin/users" in customer_paths
    assert "/admin/tenants" in customer_paths
    assert "/admin/api-keys" in customer_paths
    assert any("/admin/apps/" in p for p in customer_paths)

    # Customer Admin MUST NOT see platform ops
    assert "/ops/tenants" not in customer_paths
    assert "/ops/daemons" not in customer_paths


def test_devops_forbidden_on_plane4_cartridges() -> None:
    """Platform operators (DevOps) must receive 403 Forbidden when accessing Plane 4 cartridges."""
    client = TestClient(app, follow_redirects=False)

    devops_token = create_jwt_token(
        principal_id="devops_admin",
        roles=["devops_admin", "super_admin"],
        permitted_apps=["all", "mail_organizer", "temperature_marker"],
        tenant_id="platform",
    )
    client.cookies.set("admin_token", devops_token)

    # 1. DevOps operator without tenant cartridge access
    resp_mail = client.get("/admin/apps/mail-organizer/dashboard")
    assert resp_mail.status_code == 403
    assert "Access denied" in resp_mail.text or "Data Sovereignty" in resp_mail.text

    resp_accounts = client.get("/admin/apps/mail-organizer/accounts")
    assert resp_accounts.status_code == 403

    resp_tm = client.get("/admin/apps/temperature-marker/fleet")
    assert resp_tm.status_code == 403

    # 2. DevOps operator even if also holding admin role (strict data sovereignty invariant)
    devops_with_admin = create_jwt_token(
        principal_id="devops_admin",
        roles=["devops_admin", "admin"],
        permitted_apps=["all", "mail_organizer", "temperature_marker"],
        tenant_id="default_tenant",
    )
    client.cookies.set("admin_token", devops_with_admin)

    resp_sovereignty = client.get("/admin/apps/mail-organizer/dashboard")
    assert resp_sovereignty.status_code == 403
    assert "Data Sovereignty" in resp_sovereignty.text

    resp_sovereignty_tm = client.get("/admin/apps/temperature-marker/fleet")
    assert resp_sovereignty_tm.status_code == 403
    assert "Data Sovereignty" in resp_sovereignty_tm.text


def test_customer_admin_allowed_on_cartridges() -> None:
    """Customer Workspace Admin must be allowed to access Plane 4 cartridges."""
    client = TestClient(app, follow_redirects=False)

    customer_token = create_jwt_token(
        principal_id="customer_admin",
        roles=["admin"],
        permitted_apps=["all", "mail_organizer", "temperature_marker"],
        tenant_id="default_tenant",
    )
    client.cookies.set("admin_token", customer_token)

    resp_mail = client.get("/admin/apps/mail-organizer/dashboard")
    assert resp_mail.status_code == 200

    resp_tm = client.get("/admin/apps/temperature-marker/fleet")
    assert resp_tm.status_code == 200
