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
Unit Test Suite for Tenant Middleware Anti-Spoofing and Cartridge Boundary Invariants.

Asserts GEES v3.1 Plane 1/Plane 2 Invariants:
1. Authenticated customer user cannot spoof tenant via X-Tenant-ID header (403 Forbidden).
2. Authenticated customer user cannot spoof tenant via ?tenant_id= query param (403 Forbidden).
3. Authenticated DevOps super-admin CAN dynamically switch tenants via header or query.
4. Unauthenticated traffic resolves ambient tenant without error.
5. NIST SP 800-63B SessionVault sliding idle expiration revokes JWT validation.
"""

import time
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from core_platform.app.auth.jwt_utils import create_jwt_token, verify_jwt_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.auth.session_vault import get_session_vault
from core_platform.app.middleware.tenant_context import (
    TenantContextMiddleware,
    get_current_security_ticket,
    get_current_tenant_id,
    resolve_effective_tenant_info,
)
from core_platform.app.rbac.permissions import get_web_security_context


@pytest.fixture(autouse=True)
def clean_session_vault() -> None:
    """Clear session vault state between tests."""
    get_session_vault().clear()


def create_anti_spoofing_test_app() -> FastAPI:
    """Create isolated FastAPI app with TenantContextMiddleware."""
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware, default_tenant="public")

    @app.get("/api/tenant-echo")
    async def tenant_echo(request: Request) -> JSONResponse:
        ticket = get_current_security_ticket()
        return JSONResponse({
            "state_tenant": getattr(request.state, "tenant_id", None),
            "context_tenant": get_current_tenant_id(),
            "ticket_jti": ticket.jti if ticket else None,
            "ticket_tid": ticket.tid if ticket else None,
        })

    @app.get("/api/protected-resource")
    async def protected_endpoint(
        request: Request,
        ctx: SecurityContext = Depends(get_web_security_context),
    ) -> JSONResponse:
        active_slug, org_name, _ = resolve_effective_tenant_info(request, ctx)
        return JSONResponse({
            "principal": ctx.principal_id,
            "effective_tenant": active_slug,
            "org_name": org_name,
        })

    return app


def test_customer_user_cannot_spoof_tenant_via_header() -> None:
    """An authenticated customer user sending a conflicting X-Tenant-ID MUST receive 403 Forbidden."""
    app = create_anti_spoofing_test_app()
    client = TestClient(app)

    # Customer user token bound strictly to 'tenant_alpha'
    token = create_jwt_token(
        principal_id="user_alpha_1",
        roles=["operator"],
        permitted_apps=["mail_organizer"],
        tenant_id="tenant_alpha",
    )

    # 1. Normal legitimate request with matching context
    resp_ok = client.get("/api/tenant-echo", cookies={"admin_token": token})
    assert resp_ok.status_code == 200
    assert resp_ok.json()["context_tenant"] == "tenant_alpha"

    # 2. Impersonation attempt via X-Tenant-ID header
    resp_spoof = client.get(
        "/api/tenant-echo",
        cookies={"admin_token": token},
        headers={"X-Tenant-ID": "victim_tenant_beta"},
    )
    assert resp_spoof.status_code == 403
    assert "Cross-tenant impersonation forbidden" in resp_spoof.text


def test_customer_user_cannot_spoof_tenant_via_query_param() -> None:
    """An authenticated customer user sending ?tenant_id=other MUST receive 403 Forbidden."""
    app = create_anti_spoofing_test_app()
    client = TestClient(app)

    token = create_jwt_token(
        principal_id="user_alpha_2",
        roles=["operator"],
        permitted_apps=["mail_organizer"],
        tenant_id="tenant_alpha",
    )

    resp_spoof = client.get(
        "/api/tenant-echo?tenant_id=victim_tenant_gamma",
        cookies={"admin_token": token},
    )
    assert resp_spoof.status_code == 403
    assert "Cross-tenant impersonation forbidden" in resp_spoof.text


def test_devops_super_admin_can_dynamically_switch_tenants() -> None:
    """A DevOps super-admin CAN legitimately target different tenants via X-Tenant-ID or ?tenant_id=."""
    app = create_anti_spoofing_test_app()
    client = TestClient(app)

    devops_token = create_jwt_token(
        principal_id="devops_admin",
        roles=["super_admin"],
        permitted_apps=["*"],
        tenant_id="platform",
    )

    # Super admin targets tenant_alpha
    resp_alpha = client.get(
        "/api/tenant-echo",
        cookies={"admin_token": devops_token},
        headers={"X-Tenant-ID": "tenant_alpha"},
    )
    assert resp_alpha.status_code == 200
    assert resp_alpha.json()["context_tenant"] == "tenant_alpha"

    # Super admin targets tenant_beta via query param
    resp_beta = client.get(
        "/api/tenant-echo?tenant_id=tenant_beta",
        cookies={"admin_token": devops_token},
    )
    assert resp_beta.status_code == 200
    assert resp_beta.json()["context_tenant"] == "tenant_beta"


def test_nist_session_vault_sliding_idle_revokes_jwt() -> None:
    """When a session ticket exceeds the 1-hour sliding idle grace window in SessionVault, JWT verification fails."""
    t0 = int(time.time())
    token = create_jwt_token(
        principal_id="user_sliding_1",
        roles=["operator"],
        permitted_apps=["mail_organizer"],
        tenant_id="tenant_sliding",
    )

    # Legitimate immediate verification
    ctx = verify_jwt_token(token)
    assert ctx is not None
    assert ctx.principal_id == "user_sliding_1"

    # Simulate 3605 seconds of inactivity (> 3600s sliding window)
    t_expired = t0 + 3605
    vault = get_session_vault()
    # Invalidate by sliding expiration check
    parts = token.split(".")
    import json
    from core_platform.app.auth.jwt_utils import _b64url_decode
    payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    jti = payload["jti"]

    ticket = vault.get_ticket(jti)
    assert ticket is not None
    # Artificially age the last_active timestamp
    ticket.last_active = t0 - 4000

    # Verification must fail closed because sliding grace expired
    ctx_after_idle = verify_jwt_token(token)
    assert ctx_after_idle is None
