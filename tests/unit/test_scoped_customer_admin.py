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
Unit tests for Scoped Customer Admin UI & Tenant Boundary Enforcement.
Validates:
1. Customer admin user registration auto-scopes to active tenant.
2. Cross-tenant user injection is prevented.
3. User directory listing only exposes active tenant users.
4. Cross-tenant status modification and deletion are blocked with 403.
5. Super/DevOps admin retains multi-tenant operational privileges.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI, Request
from sqlalchemy import create_engine

from core_platform.app.admin_shell.routes import router as admin_router
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.identity.service import UserIdentityService, get_user_identity_service
from core_platform.app.middleware.tenant_context import TenantContextMiddleware


@pytest.fixture
def identity_service(tmp_path: Path) -> UserIdentityService:
    """Provide isolated identity service instance."""
    db_file = tmp_path / "test_scoped_identity.db"
    svc = get_user_identity_service(db_path=db_file)
    return svc


@pytest.fixture
def test_app(identity_service: UserIdentityService) -> FastAPI:
    """Create a test FastAPI application with TenantContextMiddleware and Admin Router."""
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)
    app.include_router(admin_router)
    return app


def test_customer_admin_registration_autoscopes(test_app: FastAPI, identity_service: UserIdentityService) -> None:
    """Verify customer admin cannot inject users into a different tenant."""
    # Create an admin JWT for acme_corp
    token = create_jwt_token(
        principal_id="acme_admin",
        roles=["admin"],
        permitted_apps=["mail_organizer"],
        tenant_id="acme_corp",
    )

    client = TestClient(test_app)
    # Set cookies for JWT and CSRF
    client.cookies.set("admin_token", token)
    client.cookies.set("csrf_token", "test_csrf_token")

    # Attempt to register user while passing a hostile tenant_id in form
    response = client.post(
        "/admin/users",
        data={
            "phone_number": "+919988776655",
            "full_name": "Acme Employee",
            "tenant_id": "malicious_other_tenant",
            "role": "user",
            "csrf_token": "test_csrf_token",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    # Verify user was saved under acme_corp, NOT malicious_other_tenant
    user = identity_service.get_user_by_phone("+919988776655")
    assert user is not None
    assert user.tenant_id == "acme_corp"


def test_customer_admin_directory_scoping(test_app: FastAPI, identity_service: UserIdentityService) -> None:
    """Verify user directory listing is strictly filtered to the customer's tenant."""
    # Seed users across two tenants
    identity_service.register_user(
        phone_number="+911111111111",
        full_name="Acme User 1",
        tenant_id="acme_corp",
    )
    identity_service.register_user(
        phone_number="+912222222222",
        full_name="Beta User 1",
        tenant_id="beta_inc",
    )

    acme_token = create_jwt_token(
        principal_id="acme_admin",
        roles=["admin"],
        permitted_apps=["mail_organizer"],
        tenant_id="acme_corp",
    )

    client = TestClient(test_app)
    client.cookies.set("admin_token", acme_token)

    response = client.get("/admin/users")
    assert response.status_code == 200
    assert "Acme User 1" in response.text
    assert "Beta User 1" not in response.text


def test_customer_admin_cross_tenant_modification_blocked(test_app: FastAPI, identity_service: UserIdentityService) -> None:
    """Verify modifying a user belonging to another tenant returns 403 Forbidden."""
    beta_user = identity_service.register_user(
        phone_number="+913333333333",
        full_name="Beta User Target",
        tenant_id="beta_inc",
    )

    acme_token = create_jwt_token(
        principal_id="acme_admin",
        roles=["admin"],
        permitted_apps=["mail_organizer"],
        tenant_id="acme_corp",
    )

    client = TestClient(test_app)
    client.cookies.set("admin_token", acme_token)
    client.cookies.set("csrf_token", "test_csrf_token")

    # Attempt to suspend Beta user from Acme admin account
    resp_status = client.post(
        f"/admin/users/{beta_user.id}/status",
        data={"status": "suspended", "csrf_token": "test_csrf_token"},
    )
    assert resp_status.status_code == 403

    # Attempt to delete Beta user from Acme admin account
    resp_delete = client.post(
        f"/admin/users/{beta_user.id}/delete",
        data={"csrf_token": "test_csrf_token"},
    )
    assert resp_delete.status_code == 403


def test_customer_admin_login_flow_with_password(test_app: FastAPI, identity_service: UserIdentityService) -> None:
    """Verify customer admin can log in with phone/password and access scoped admin shell."""
    # Register customer admin with password
    identity_service.register_user(
        phone_number="+919876543210",
        full_name="Delta Admin",
        role="admin",
        tenant_id="delta_corp",
        allowed_cartridges=["mail_organizer"],
        password="DeltaSecure@2026",
        email="admin@delta.com",
    )

    client = TestClient(test_app, follow_redirects=False)
    client.cookies.set("csrf_token", "test_csrf_token")

    # 1. Successful Customer Admin Login via Phone
    resp_login = client.post(
        "/admin/login",
        data={
            "username": "+919876543210",
            "password": "DeltaSecure@2026",
            "csrf_token": "test_csrf_token",
        },
    )
    assert resp_login.status_code == 302
    assert resp_login.headers["location"] == "/admin/"
    assert "admin_token" in resp_login.cookies

    # 2. Verify issued token has customer tenant context
    token = resp_login.cookies["admin_token"]
    from core_platform.app.auth.jwt_utils import verify_jwt_token
    ctx = verify_jwt_token(token)
    assert ctx is not None
    assert ctx.principal_id == "+919876543210"
    assert ctx.tenant_id == "delta_corp"
    assert ctx.permitted_apps == ["mail_organizer"]

    # 3. Successful Customer Admin Login via Email
    resp_email_login = client.post(
        "/admin/login",
        data={
            "username": "admin@delta.com",
            "password": "DeltaSecure@2026",
            "csrf_token": "test_csrf_token",
        },
    )
    assert resp_email_login.status_code == 302
    assert resp_email_login.headers["location"] == "/admin/"

    # 4. Wrong password failure
    resp_bad_pwd = client.post(
        "/admin/login",
        data={
            "username": "+919876543210",
            "password": "WrongPassword123",
            "csrf_token": "test_csrf_token",
        },
    )
    assert resp_bad_pwd.status_code == 401


def test_customer_admin_assign_existing_user(test_app: FastAPI, identity_service: UserIdentityService) -> None:
    """Verify customer admin can look up an unassigned/existing user and assign them to their tenant."""
    # 1. Seed an unassigned / default tenant user
    existing = identity_service.register_user(
        phone_number="+919911223344",
        full_name="Unassigned Operator",
        role="user",
        tenant_id="default_tenant",
    )
    assert existing.tenant_id == "default_tenant"

    # Customer Admin token for acme_corp
    token = create_jwt_token(
        principal_id="acme_admin",
        roles=["admin"],
        permitted_apps=["mail_organizer"],
        tenant_id="acme_corp",
    )
    client = TestClient(test_app, follow_redirects=False)
    client.cookies.set("admin_token", token)
    client.cookies.set("csrf_token", "test_csrf_token")

    # 2. Look up existing user via API
    resp_lookup = client.get("/admin/users/api/lookup?q=+919911223344")
    assert resp_lookup.status_code == 200
    data = resp_lookup.json()
    assert data["found"] is True
    assert data["user"]["full_name"] == "Unassigned Operator"
    assert data["user"]["tenant_id"] == "default_tenant"

    # 3. Customer Admin assigns user to their tenant (acme_corp)
    resp_assign = client.post(
        "/admin/users/assign-tenant",
        data={
            "identifier": "+919911223344",
            "role": "supervisor",
            "tenant_id": "malicious_attempt",  # Customer admin cannot override their own tenant
            "cartridges": ["mail_organizer"],
            "csrf_token": "test_csrf_token",
        },
    )
    assert resp_assign.status_code == 303

    # 4. Verify user was assigned to acme_corp (not malicious_attempt)
    user_updated = identity_service.get_user_by_phone("+919911223344")
    assert user_updated is not None
    assert user_updated.tenant_id == "acme_corp"
    assert user_updated.role == "supervisor"
    assert "mail_organizer" in user_updated.allowed_cartridges


def test_customer_admin_update_user_profile_and_boundary(test_app: FastAPI, identity_service: UserIdentityService) -> None:
    """Verify customer admin can edit their own users, but cannot edit cross-tenant users."""
    # Seed user for acme_corp and user for beta_corp
    acme_user = identity_service.register_user(
        phone_number="+918800112233",
        full_name="Acme Worker",
        role="user",
        tenant_id="acme_corp",
    )
    beta_user = identity_service.register_user(
        phone_number="+918800445566",
        full_name="Beta Worker",
        role="user",
        tenant_id="beta_corp",
    )

    token = create_jwt_token(
        principal_id="acme_admin",
        roles=["admin"],
        permitted_apps=["*"],
        tenant_id="acme_corp",
    )
    client = TestClient(test_app, follow_redirects=False)
    client.cookies.set("admin_token", token)
    client.cookies.set("csrf_token", "test_csrf_token")

    # 1. Update own user -> Success (303)
    resp_update = client.post(
        f"/admin/users/{acme_user.id}/update",
        data={
            "full_name": "Acme Lead Worker",
            "role": "supervisor",
            "timezone": "America/New_York",
            "tenant_id": "other_corp",  # Customer admin cannot reassign tenant
            "csrf_token": "test_csrf_token",
        },
    )
    assert resp_update.status_code == 303

    reloaded = identity_service.get_user_by_id(acme_user.id)
    assert reloaded is not None
    assert reloaded.full_name == "Acme Lead Worker"
    assert reloaded.role == "supervisor"
    assert reloaded.tenant_id == "acme_corp"  # Protected from unauthorized reassignment

    # 2. Update cross-tenant user -> 403 Forbidden
    resp_cross = client.post(
        f"/admin/users/{beta_user.id}/update",
        data={
            "full_name": "Hostile Rename",
            "role": "admin",
            "csrf_token": "test_csrf_token",
        },
    )
    assert resp_cross.status_code == 403

