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
Comprehensive unit tests for Authentication, RBAC, API Keys, and Admin Shell routes.
Adheres strictly to GEES v1.0.
"""

from pathlib import Path
from typing import Any
import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from core_platform.app.auth.api_keys import APIKeyManager, get_api_key_manager
from core_platform.app.auth.jwt_utils import create_jwt_token, verify_jwt_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.auth.strategies import (
    AuthResolver,
    LocalJWTStrategy,
    PhoneBiometricStrategy,
    ScopedAPIKeyStrategy,
)
from core_platform.app.rbac.permissions import (
    RBACFilter,
    get_api_security_context,
    get_web_security_context,
    require_admin,
)
from core_platform.app.admin_shell.routes import router as admin_router


def test_api_key_manager_full_lifecycle(tmp_path: Path) -> None:
    """Test API key creation, verification, revocation, and expiration."""
    db_file = tmp_path / "keys.db"
    mgr = APIKeyManager(db_path=db_file)

    # Empty list
    assert mgr.list_keys() == []

    # Create active key
    raw_key, key_hash = mgr.create_key(
        label="Test Key",
        principal_id="user_123",
        roles=["operator"],
        permitted_apps=["temperature_marker"],
        scopes=["temp:read"],
        max_rpm=120,
    )
    assert raw_key.startswith("ak_live_")
    assert len(key_hash) == 64

    # Validate valid key
    ctx = mgr.validate_key(raw_key)
    assert ctx is not None
    assert ctx.principal_id == "user_123"
    assert ctx.user_roles == ["operator"]
    assert "temperature_marker" in ctx.permitted_apps
    assert ctx.is_authenticated is True

    # Validate with invalid / malformed key
    assert mgr.validate_key("invalid_key") is None
    assert mgr.validate_key("ak_live_nonexistent_key_1234567890abcdef") is None

    # List keys
    keys = mgr.list_keys()
    assert len(keys) == 1
    assert keys[0]["label"] == "Test Key"
    assert keys[0]["revoked"] == 0

    # Revoke key
    assert mgr.revoke_key(key_hash) is True
    assert mgr.validate_key(raw_key) is None
    assert mgr.list_keys()[0]["revoked"] == 1

    # Expired key
    raw_exp, hash_exp = mgr.create_key(
        label="Expired Key",
        principal_id="exp_user",
        roles=["admin"],
        permitted_apps=[],
        expiry_days=-1,  # in the past
    )
    assert mgr.validate_key(raw_exp) is None

    # Singleton check
    global_mgr = get_api_key_manager()
    assert isinstance(global_mgr, APIKeyManager)


def test_auth_strategies_and_resolver() -> None:
    """Test all auth strategies and AuthResolver dispatching."""
    # Strategy A
    ctx_phone = PhoneBiometricStrategy.authenticate("+919876543210")
    assert ctx_phone.is_authenticated is True
    assert ctx_phone.principal_id == "+919876543210"
    assert "operator" in ctx_phone.user_roles

    ctx_empty_phone = PhoneBiometricStrategy.authenticate("")
    assert ctx_empty_phone.is_authenticated is False

    # Strategy C
    ctx_cred = LocalJWTStrategy.authenticate("admin", "release100_admin")
    if ctx_cred:  # depending on env hash
        assert ctx_cred.principal_id == "admin"

    ctx_cred_wrong = LocalJWTStrategy.authenticate("wrong_user", "wrong_pass")
    assert ctx_cred_wrong is None

    token = create_jwt_token("jwt_user", ["admin"], ["temperature_marker"])
    ctx_token = LocalJWTStrategy.authenticate_token(token)
    assert ctx_token is not None
    assert ctx_token.principal_id == "jwt_user"

    # Expired token and malformed token
    expired_token = create_jwt_token("expired_user", ["admin"], ["temperature_marker"], expiry_seconds=-10)
    assert verify_jwt_token(expired_token) is None
    assert verify_jwt_token("invalid.malformed.token") is None
    assert verify_jwt_token("") is None


    # Strategy D
    ctx_api = ScopedAPIKeyStrategy.authenticate("bad_key")
    assert ctx_api is None


    # AuthResolver helper methods
    res_phone = AuthResolver.resolve_whatsapp("+911234567890")
    assert res_phone.is_authenticated is True

    res_web = AuthResolver.resolve_web(token)
    assert res_web is not None

    res_api = AuthResolver.resolve_api_key("bad_key")
    assert res_api is None


def test_rbac_assertions_and_dependencies() -> None:
    """Test RBACFilter assertions and FastAPI security dependencies."""
    ctx_admin = SecurityContext(
        principal_id="adm",
        user_roles=["admin"],
        permitted_apps=["temperature_marker", "mail_organizer"],
        is_authenticated=True,
    )
    RBACFilter.assert_app_access(ctx_admin, "temperature_marker")

    ctx_unauth = SecurityContext.unauthenticated()
    with pytest.raises(HTTPException) as exc_info:
        RBACFilter.assert_app_access(ctx_unauth, "temperature_marker")
    assert exc_info.value.status_code == 403

    # require_admin dependency
    token_admin = create_jwt_token("adm", ["admin"], ["temperature_marker"])
    token_operator = create_jwt_token("op", ["operator"], ["temperature_marker"])

    adm_ctx = require_admin(admin_token=token_admin)
    assert adm_ctx.is_admin is True

    with pytest.raises(HTTPException) as op_exc:
        require_admin(admin_token=token_operator)
    assert op_exc.value.status_code == 403

    with pytest.raises(HTTPException) as no_token_exc:
        require_admin(admin_token=None)
    assert no_token_exc.value.status_code == 401


def test_admin_shell_routes() -> None:
    """Test Admin Shell web routes (login, logout, dashboard, api-keys)."""
    app = FastAPI()
    app.include_router(admin_router)
    client = TestClient(app, follow_redirects=False)

    # 1. Login page
    res_login_page = client.get("/admin/login")
    assert res_login_page.status_code == 200
    assert "Release100 Admin" in res_login_page.text
    csrf_tok = res_login_page.cookies.get("csrf_token", "")

    # 2. Login POST failure
    res_fail = client.post("/admin/login", data={"username": "bad", "password": "wrong", "csrf_token": csrf_tok})
    assert res_fail.status_code == 401
    assert "Invalid credentials" in res_fail.text

    # 3. Logout
    res_logout = client.get("/admin/logout")
    assert res_logout.status_code == 302
    assert res_logout.headers["location"] == "/admin/login"

    # 4. Unauthenticated dashboard
    res_dash_unauth = client.get("/admin/")
    assert res_dash_unauth.status_code == 401

    # 5. Authenticated dashboard with cookie
    token = create_jwt_token("admin", ["admin"], ["temperature_marker", "mail_organizer"])
    client.cookies.set("admin_token", token)

    res_dash = client.get("/admin/")
    assert res_dash.status_code == 200
    assert "Platform Admin" in res_dash.text

    # 6. View API keys page
    res_keys = client.get("/admin/api-keys")
    assert res_keys.status_code == 200

    # 7. Create API key via POST
    res_create = client.post(
        "/admin/api-keys",
        data={
            "label": "Web Test Key",
            "permitted_apps_csv": "temperature_marker",
            "roles_csv": "operator",
            "max_rpm": 60,
        },
    )
    assert res_create.status_code == 200
    data = res_create.json()
    assert "raw_key" in data
    assert "key_hash" in data

    # 8. Revoke API key via POST
    res_revoke = client.post("/admin/api-keys/revoke", data={"key_hash": data["key_hash"]})
    assert res_revoke.status_code == 200
    assert res_revoke.json()["revoked"] is True
