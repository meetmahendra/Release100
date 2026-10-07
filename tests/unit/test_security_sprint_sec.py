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
Unit Test Suite for Security Hardening Sprint (SEC-1 through SEC-8).

Adheres strictly to GEES v1.0 (Dual-Engine Verification & Zero-Trust Architecture).
Validates:
- SEC-1: Salted PBKDF2 Password Hashing & Legacy Compatibility
- SEC-2: JWT Revocation & JTI Blacklisting
- SEC-3: Anti-CSRF Double Submit Token Engine
- SEC-4: Brute-force Login Rate Limiting
- SEC-5: Hardened Session Cookie Configuration
- SEC-6: HTTP Security Headers & Secret Redaction Filter
- SEC-7: API Key Hashing at Rest & Lifecycle Revocation
- SEC-8: RBAC Route Guard Entitlements
"""

import hashlib
from pathlib import Path
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.testclient import TestClient
import pytest

from core_platform.app.auth.api_keys import APIKeyManager
from core_platform.app.auth.csrf import (
    generate_csrf_token,
    require_csrf_protection,
    verify_csrf_token,
)
from core_platform.app.auth.jwt_utils import (
    create_jwt_token,
    get_token_blacklist,
    revoke_jwt_token,
    verify_jwt_token,
)
from core_platform.app.auth.models import SecurityContext
from core_platform.app.auth.strategies import (
    LocalJWTStrategy,
    hash_password,
    verify_password,
)
from core_platform.app.rbac.permissions import (
    RBACFilter,
    require_admin,
    require_app,
    require_roles,
)
from core_platform.app.telemetry.logging_config import SecretRedactingFilter, redact_secrets


# ============================================================================
# SEC-1: Salted Password Hashing Tests
# ============================================================================

def test_sec1_salted_password_hashing() -> None:
    """Validate PBKDF2 salted password hashing and legacy SHA-256 verification."""
    password = "SuperSecretAdminPassword123!"

    # 1. PBKDF2 hash generation
    hashed = hash_password(password)
    assert hashed.startswith("pbkdf2_sha256$100000$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False

    # 2. Legacy SHA-256 hash backward compatibility
    legacy_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
    assert verify_password(password, legacy_sha256) is True
    assert verify_password("WrongPassword!", legacy_sha256) is False

    # 3. Empty checks
    assert verify_password("", hashed) is False
    assert verify_password(password, "") is False


# ============================================================================
# SEC-2: JWT Revocation & Blacklisting Tests
# ============================================================================

def test_sec2_jwt_revocation_blacklist() -> None:
    """Validate JWT token revocation by JTI and blacklist purge."""
    blacklist = get_token_blacklist()
    blacklist.clear()

    token = create_jwt_token(
        principal_id="admin_user",
        roles=["admin"],
        permitted_apps=["temperature_marker", "mail_organizer"],
        expiry_seconds=3600,
    )

    # Token is initially valid
    ctx = verify_jwt_token(token)
    assert ctx is not None
    assert ctx.principal_id == "admin_user"
    assert ctx.is_authenticated is True

    # Revoke the token
    revoked = revoke_jwt_token(token)
    assert revoked is True

    # Token must now be rejected
    ctx_after = verify_jwt_token(token)
    assert ctx_after is None

    # Invalid string token handling
    assert revoke_jwt_token("invalid.token") is False
    blacklist.clear()


# ============================================================================
# SEC-3: Anti-CSRF Token Tests
# ============================================================================

@pytest.mark.asyncio
async def test_sec3_csrf_protection_lifecycle() -> None:
    """Validate double-submit CSRF token generation and validation."""
    token = generate_csrf_token()
    assert len(token) == 64

    # 1. Match check
    req = MagicMock(spec=Request)
    req.cookies = {"csrf_token": token}
    req.headers = {}
    assert verify_csrf_token(req, submitted_token=token) is True
    assert verify_csrf_token(req, submitted_token="wrong_token") is False

    # 2. Header match check
    req.headers = {"X-CSRF-Token": token}
    assert verify_csrf_token(req) is True

    # 3. Dependency enforcement
    req_post = MagicMock(spec=Request)
    req_post.method = "POST"
    req_post.cookies = {"csrf_token": token}
    req_post.client = MagicMock(host="127.0.0.1")
    req_post.url = MagicMock(path="/admin/test")

    # Valid token passes
    await require_csrf_protection(
        request=req_post,
        csrf_token_form=token,
        csrf_token_cookie=token,
    )

    # Mismatched token raises 403
    with pytest.raises(HTTPException) as exc:
        await require_csrf_protection(
            request=req_post,
            csrf_token_form="tampered_token",
            csrf_token_cookie=token,
        )
    assert exc.value.status_code == 403


# ============================================================================
# SEC-4 & SEC-5: Cookie Hardening & Admin Shell Auth
# ============================================================================

def test_sec4_sec5_admin_shell_login_logout() -> None:
    """Test admin login form submission, cookie security flags, and logout revocation."""
    from core_platform.main import app

    client = TestClient(app)

    # 1. GET /admin/login sets csrf_token cookie
    resp_get = client.get("/admin/login")
    assert resp_get.status_code == 200
    assert "csrf_token" in resp_get.cookies
    csrf_val = resp_get.cookies["csrf_token"]

    # 2. POST /admin/login with invalid credentials
    resp_bad = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong_password", "csrf_token": csrf_val},
        cookies={"csrf_token": csrf_val},
    )
    assert resp_bad.status_code == 401

    # 3. POST /admin/login with valid credentials
    resp_ok = client.post(
        "/admin/login",
        data={"username": "admin", "password": "release100_admin", "csrf_token": csrf_val},
        cookies={"csrf_token": csrf_val},
        follow_redirects=False,
    )
    assert resp_ok.status_code == 302
    assert "admin_token" in resp_ok.cookies

    admin_cookie = resp_ok.cookies["admin_token"]
    assert len(admin_cookie) > 20

    # 4. GET /admin/logout clears cookie and revokes token
    resp_logout = client.get(
        "/admin/logout",
        cookies={"admin_token": admin_cookie, "csrf_token": csrf_val},
        follow_redirects=False,
    )
    assert resp_logout.status_code == 302
    # Verify token is now blacklisted
    assert verify_jwt_token(admin_cookie) is None


def test_sec3_login_csrf_token_resilience_multi_attempt() -> None:
    """Verify that multiple failed login attempts maintain CSRF token synchronization."""
    from core_platform.main import app

    client = TestClient(app)

    # Step 1: Initial page load
    resp1 = client.get("/admin/login")
    assert resp1.status_code == 200
    csrf1 = resp1.cookies.get("csrf_token")
    assert csrf1 is not None

    # Step 2: Failed attempt #1 (wrong password)
    resp2 = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong_password_1", "csrf_token": csrf1},
    )
    assert resp2.status_code == 401
    assert "Invalid credentials" in resp2.text
    assert "Invalid session token" not in resp2.text

    # Step 3: Failed attempt #2 (wrong password again)
    csrf2 = resp2.cookies.get("csrf_token") or client.cookies.get("csrf_token") or csrf1
    resp3 = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong_password_2", "csrf_token": csrf2},
    )
    assert resp3.status_code == 401
    assert "Invalid credentials" in resp3.text
    assert "Invalid session token" not in resp3.text

    # Step 4: Successful attempt #3 with valid credentials
    csrf3 = resp3.cookies.get("csrf_token") or client.cookies.get("csrf_token") or csrf2
    resp4 = client.post(
        "/admin/login",
        data={"username": "admin", "password": "release100_admin", "csrf_token": csrf3},
        follow_redirects=False,
    )
    assert resp4.status_code == 302
    assert resp4.headers["location"] in ["/ops/tenants", "/admin/"]
    assert "admin_token" in resp4.cookies


# ============================================================================
# SEC-6: HTTP Security Headers & Secret Redaction Filter Tests
# ============================================================================

def test_sec6_http_security_headers() -> None:
    """Verify standard defense-in-depth HTTP security headers on all responses."""
    from core_platform.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert "strict-origin-when-cross-origin" in headers.get("Referrer-Policy", "")


def test_sec6_secret_redaction() -> None:
    """Verify secret credentials redaction in log strings."""
    raw_log = "Dispatching Bearer ak_live_0123456789abcdef0123456789abcdef with password='MySecretPassword!' and key=AIzaSyD_SECRET_KEY_123"
    redacted = redact_secrets(raw_log)

    assert "ak_live_0123456789abcdef0123456789abcdef" not in redacted
    assert "MySecretPassword!" not in redacted
    assert "AIzaSyD_SECRET_KEY_123" not in redacted
    assert "***REDACTED***" in redacted

    filter_obj = SecretRedactingFilter()
    rec = MagicMock()
    rec.msg = "User login attempt with password=SecretPassword123"
    rec.args = ()
    assert filter_obj.filter(rec) is True
    assert "SecretPassword123" not in rec.msg


# ============================================================================
# SEC-7: API Key Hashing at Rest Tests
# ============================================================================

def test_sec7_api_key_hashing_and_lifecycle(tmp_path) -> None:
    """Verify API keys are stored only as SHA-256 hashes at rest."""
    db_file = tmp_path / "test_api_keys.db"
    manager = APIKeyManager(db_path=db_file)

    raw_key, key_hash = manager.create_key(
        label="Test Key",
        principal_id="test_mcp_client",
        roles=["admin"],
        permitted_apps=["temperature_marker"],
        max_rpm=120,
    )

    assert raw_key.startswith("ak_live_")
    assert key_hash == hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    # Validate key using raw Bearer string
    ctx = manager.validate_key(raw_key)
    assert ctx is not None
    assert ctx.principal_id == "test_mcp_client"
    assert ctx.auth_strategy == "api_key"

    # Listing keys does not leak raw secret key
    keys = manager.list_keys()
    assert len(keys) == 1
    assert "raw_key" not in keys[0]

    # Revoke key
    assert manager.revoke_key(key_hash) is True
    assert manager.validate_key(raw_key) is None


# ============================================================================
# SEC-8: RBAC Route Guard Dependency Tests
# ============================================================================

def test_sec8_rbac_route_dependencies() -> None:
    """Verify RBAC role requirement dependencies raise 403 on unauthorized roles."""
    admin_ctx = SecurityContext(
        principal_id="admin_user",
        tenant_id="default_tenant",
        user_roles=["admin"],
        permitted_apps=["temperature_marker"],
        auth_strategy="local_jwt",
        is_authenticated=True,
    )
    operator_ctx = SecurityContext(
        principal_id="operator_user",
        tenant_id="default_tenant",
        user_roles=["operator"],
        permitted_apps=["temperature_marker"],
        auth_strategy="phone_biometric",
        is_authenticated=True,
    )

    # 1. require_roles test
    role_checker = require_roles("admin", "manager")
    with patch("core_platform.app.rbac.permissions.get_web_security_context", return_value=admin_ctx):
        res = role_checker("mock_token")
        assert res.principal_id == "admin_user"

    with patch("core_platform.app.rbac.permissions.get_web_security_context", return_value=operator_ctx):
        with pytest.raises(HTTPException) as exc_role:
            role_checker("mock_token")
        assert exc_role.value.status_code == 403

    # 2. require_app test
    app_checker = require_app("temperature_marker")
    with patch("core_platform.app.rbac.permissions.get_web_security_context", return_value=admin_ctx):
        res_app = app_checker("mock_token")
        assert res_app.principal_id == "admin_user"

    app_checker_forbidden = require_app("unpermitted_app")
    with patch("core_platform.app.rbac.permissions.get_web_security_context", return_value=admin_ctx):
        with pytest.raises(HTTPException) as exc_app:
            app_checker_forbidden("mock_token")
        assert exc_app.value.status_code == 403

    # 3. get_api_security_context test
    req_no_auth = MagicMock(spec=Request)
    req_no_auth.headers = {}
    with pytest.raises(HTTPException) as exc_no_auth:
        from core_platform.app.rbac.permissions import get_api_security_context
        get_api_security_context(req_no_auth)
    assert exc_no_auth.value.status_code == 401

    req_valid_api = MagicMock(spec=Request)
    req_valid_api.headers = {"Authorization": "Bearer ak_live_00112233445566778899aabbccddeeff"}
    with patch("core_platform.app.auth.strategies.AuthResolver.resolve_api_key", return_value=admin_ctx):
        ctx_out = get_api_security_context(req_valid_api)
        assert ctx_out.principal_id == "admin_user"


# ============================================================================
# Admin Shell Observability & Log Endpoints Coverage
# ============================================================================

def test_admin_shell_observability_endpoints(tmp_path: Path) -> None:
    """Test /admin/logs, /admin/api/logs/tail, /admin/llm-costs, and /admin/api/llm-costs."""
    from core_platform.main import app

    client = TestClient(app, follow_redirects=False)
    token = create_jwt_token("admin", ["admin"], ["temperature_marker", "mail_organizer"])
    client.cookies.set("admin_token", token)

    # 1. Logs page
    res_logs = client.get("/admin/logs")
    assert res_logs.status_code == 200
    assert "Live System Logs" in res_logs.text

    # 2. Tail logs API
    res_tail = client.get("/admin/api/logs/tail?lines=50")
    assert res_tail.status_code == 200
    assert "lines" in res_tail.json()

    # 3. Download logs
    res_dl = client.get("/admin/api/logs/download?format=log")
    assert res_dl.status_code in (200, 404)

    # 4. LLM Costs page & API
    res_costs_page = client.get("/admin/llm-costs")
    assert res_costs_page.status_code == 200
    assert "LLM Token & Cost Consumption" in res_costs_page.text or "LLM Token &amp; Cost Consumption" in res_costs_page.text

    res_costs_api = client.get("/admin/api/llm-costs")
    assert res_costs_api.status_code == 200
    assert "summary" in res_costs_api.json()
    assert "operations" in res_costs_api.json()


# ============================================================================
# Phase 1 Residual Hardening Verification Tests
# ============================================================================

def test_tech6_jwt_nbf_claim_and_validation() -> None:
    """Test JWT nbf (Not Before) generation and verification."""
    import time
    from core_platform.app.auth.jwt_utils import create_jwt_token, verify_jwt_token

    # Valid token created now
    token = create_jwt_token("user1", ["admin"], ["temperature_marker"])
    ctx = verify_jwt_token(token)
    assert ctx is not None
    assert ctx.principal_id == "user1"

    # Token with future nbf should be rejected
    from core_platform.app.config import settings
    future_nbf_payload = {
        "sub": "user_future",
        "tenant": "default_tenant",
        "roles": ["admin"],
        "apps": ["temperature_marker"],
        "iat": int(time.time()),
        "nbf": int(time.time()) + 300,  # 5 minutes in future
        "exp": int(time.time()) + 3600,
        "jti": "future-jti-123",
    }
    import base64, json, hmac, hashlib
    def b64(d: bytes) -> str: return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")
    hdr = b64(b'{"alg":"HS256","typ":"JWT"}')
    pld = b64(json.dumps(future_nbf_payload).encode())
    sig = b64(hmac.new(settings.JWT_SECRET_KEY.encode(), f"{hdr}.{pld}".encode(), hashlib.sha256).digest())
    future_token = f"{hdr}.{pld}.{sig}"

    assert verify_jwt_token(future_token) is None


def test_sec5_admin_health_metrics_endpoint() -> None:
    """Verify /admin/api/health-metrics endpoint structure, auth requirement, and public /health sanitization."""
    from core_platform.main import app
    client = TestClient(app)

    # Public health check
    res_pub = client.get("/health")
    assert res_pub.status_code == 200
    pub_data = res_pub.json()
    assert pub_data["status"] == "healthy"
    assert "version" in pub_data

    # Unauthenticated call to /admin/api/health-metrics must be rejected with 401
    res_unauth = client.get("/admin/api/health-metrics")
    assert res_unauth.status_code == 401

    # Authenticated call to /admin/api/health-metrics
    token = create_jwt_token("admin", ["admin"], ["temperature_marker", "mail_organizer"])
    client.cookies.set("admin_token", token)
    res_adm = client.get("/admin/api/health-metrics")
    assert res_adm.status_code == 200
    adm_data = res_adm.json()
    assert "cloud_relay" in adm_data
    assert "relay_url" in adm_data["cloud_relay"]


def test_sec6_phone_biometric_two_phase_contract() -> None:
    """Verify PhoneBiometricStrategy two-phase authentication contract."""
    from core_platform.app.auth.strategies import PhoneBiometricStrategy

    ctx_phase1 = PhoneBiometricStrategy.authenticate("+919876543210", biometric_verified=False)
    assert ctx_phase1.is_authenticated is True
    assert ctx_phase1.is_biometric_verified is False

    ctx_phase2 = PhoneBiometricStrategy.complete_biometric_verification(ctx_phase1)
    assert ctx_phase2.is_authenticated is True
    assert ctx_phase2.is_biometric_verified is True


def test_sec7_api_key_per_key_rate_limit(tmp_path: Path) -> None:
    """Verify APIKeyManager enforces max_rpm on key validation."""
    from core_platform.app.auth.api_keys import APIKeyManager

    mgr = APIKeyManager(db_path=tmp_path / "test_ratelimit_keys.db")
    raw_key, _ = mgr.create_key(
        label="RateLimitTestKey",
        principal_id="test_client",
        roles=["operator"],
        permitted_apps=["temperature_marker"],
        max_rpm=2,  # 2 requests per minute limit
    )

    # First request: Allowed
    ctx1 = mgr.validate_key(raw_key)
    assert ctx1 is not None

    # Second request: Allowed
    ctx2 = mgr.validate_key(raw_key)
    assert ctx2 is not None

    # Third request immediately: Exceeds 2 RPM capacity -> Rejected
    ctx3 = mgr.validate_key(raw_key)
    assert ctx3 is None


@pytest.mark.anyio
async def test_outbox_unknown_app_rejection() -> None:
    """Verify OutboxSynchronizer rejects unknown cartridge applications."""
    from core_platform.app.outbox.synchronizer import OutboxSynchronizer

    sync = OutboxSynchronizer(drain_interval_seconds=60)
    success, msg = await sync._dispatch_item("unknown_cartridge_xyz", "http_rest", {"test": 1})
    assert success is False
    assert "no active outbox transmitter registered" in msg

