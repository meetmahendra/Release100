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
Strict RBAC Access Matrix & User Persona Boundary Verification.

Adheres strictly to GEES v3.0 Multi-Plane Architecture (Rule 1) and Zero-Trust Security (Rule 8).
Verifies that:
1. DevOps Super-Admin has full operational access across control plane and diagnostic routes.
2. Tenant/Workspace Admin has full workspace access but is STRICTLY FORBIDDEN (403) from DevOps control plane and diagnostics.
3. Field Operator has cartridge access but is STRICTLY FORBIDDEN (403) from all administrative and DevOps routes.
"""

from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core_platform.app.admin_shell.routes import router as admin_router
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.diagnostics.web_dashboard import router as diagnostics_router
from core_platform.app.middleware.tenant_context import TenantContextMiddleware
from core_platform.app.rbac.permissions import is_devops_context
from ops_control_plane.super_admin.routes import router as ops_router


@pytest.fixture
def matrix_app() -> FastAPI:
    """Create a fully integrated test application with all routers mounted."""
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)
    app.include_router(admin_router)
    app.include_router(ops_router)
    app.include_router(diagnostics_router)
    return app


def test_is_devops_context_evaluation() -> None:
    """Verify is_devops_context returns True ONLY for devops/super_admin principals."""
    # 1. DevOps user -> True
    devops_ctx = SecurityContext(
        principal_id="devops",
        tenant_id="platform",
        user_roles=["super_admin", "devops_admin"],
        is_authenticated=True,
    )
    assert is_devops_context(devops_ctx) is True
    assert devops_ctx.is_devops is True

    # 2. Workspace Admin -> False
    admin_ctx = SecurityContext(
        principal_id="admin",
        tenant_id="default_tenant",
        user_roles=["admin"],
        is_authenticated=True,
    )
    assert is_devops_context(admin_ctx) is False
    assert admin_ctx.is_devops is False
    assert admin_ctx.is_admin is True

    # 3. Customer Admin -> False
    customer_admin_ctx = SecurityContext(
        principal_id="acme_admin",
        tenant_id="acme_corp",
        user_roles=["admin"],
        is_authenticated=True,
    )
    assert is_devops_context(customer_admin_ctx) is False
    assert customer_admin_ctx.is_devops is False
    assert customer_admin_ctx.is_admin is True

    # 4. Field Operator -> False
    operator_ctx = SecurityContext(
        principal_id="+919876543210",
        tenant_id="default_tenant",
        user_roles=["operator"],
        is_authenticated=True,
    )
    assert is_devops_context(operator_ctx) is False
    assert operator_ctx.is_devops is False
    assert operator_ctx.is_admin is False


def test_devops_persona_access_matrix(matrix_app: FastAPI) -> None:
    """Verify DevOps super-admin can access control plane, diagnostics, and workspace pages."""
    token = create_jwt_token(
        principal_id="devops_admin",
        roles=["admin", "devops_admin", "super_admin"],
        permitted_apps=["*"],
        tenant_id="platform",
    )
    client = TestClient(matrix_app)
    client.cookies.set("admin_token", token)

    # Allowed routes for DevOps
    assert client.get("/ops/tenants").status_code == 200
    assert client.get("/admin/logs").status_code == 200
    assert client.get("/admin/llm-costs").status_code == 200
    assert client.get("/settings").status_code == 200
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/users").status_code == 200
    assert client.get("/admin/tenants").status_code == 200
    assert client.get("/admin/api-keys").status_code == 200


def test_admin_persona_forbidden_from_devops_plane(matrix_app: FastAPI) -> None:
    """Verify Workspace Admin is STRICTLY FORBIDDEN from DevOps control plane and host diagnostics."""
    token = create_jwt_token(
        principal_id="admin",
        roles=["admin"],
        permitted_apps=["*"],
        tenant_id="default_tenant",
    )
    client = TestClient(matrix_app)
    client.cookies.set("admin_token", token)

    # 1. Allowed Workspace routes
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/users").status_code == 200
    assert client.get("/admin/tenants").status_code == 200
    assert client.get("/admin/api-keys").status_code == 200

    # 2. STRICTLY FORBIDDEN DevOps routes
    assert client.get("/ops/tenants").status_code == 403
    assert client.get("/admin/logs").status_code == 403
    assert client.get("/admin/llm-costs").status_code == 403
    assert client.get("/settings").status_code == 403


def test_operator_persona_forbidden_from_admin_and_devops(matrix_app: FastAPI) -> None:
    """Verify Field Operator is STRICTLY FORBIDDEN from all admin and DevOps pages."""
    token = create_jwt_token(
        principal_id="+919876543210",
        roles=["operator"],
        permitted_apps=["temperature_marker"],
        tenant_id="default_tenant",
    )
    client = TestClient(matrix_app)
    client.cookies.set("admin_token", token)

    # 1. Allowed home route
    assert client.get("/admin/").status_code == 200

    # 2. STRICTLY FORBIDDEN Admin Workspace routes
    assert client.get("/admin/users").status_code == 403
    assert client.get("/admin/tenants").status_code == 403
    assert client.get("/admin/api-keys").status_code == 403

    # 3. STRICTLY FORBIDDEN DevOps routes
    assert client.get("/ops/tenants").status_code == 403
    assert client.get("/admin/logs").status_code == 403
    assert client.get("/admin/llm-costs").status_code == 403
    assert client.get("/settings").status_code == 403
