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
Unit Tests for Multi-Tenancy Isolation & Dynamic Context Middleware.

Adheres strictly to GEES v2.0 Dual-Engine Verification Regime (Engine A).
"""

import asyncio
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from core_platform.app.middleware.tenant_context import (
    TenantContext,
    TenantContextMiddleware,
    get_current_tenant_context,
    get_current_tenant_id,
    reset_tenant_context,
    set_current_tenant_id,
    sync_tenant_scope,
    tenant_scope,
)


def test_tenant_context_default() -> None:
    """Verify default tenant fallback when no context is active."""
    tenant = get_current_tenant_id()
    assert tenant is not None
    assert len(tenant) > 0

    ctx = get_current_tenant_context()
    assert isinstance(ctx, TenantContext)
    assert ctx.tenant_id == tenant


def test_tenant_context_explicit_set_and_reset() -> None:
    """Verify set_current_tenant_id and reset_tenant_context operations."""
    initial_tenant = get_current_tenant_id()
    token = set_current_tenant_id("tenant_custom_alpha", organization_name="Alpha Corp", metadata={"tier": "enterprise"})
    try:
        assert get_current_tenant_id() == "tenant_custom_alpha"
        ctx = get_current_tenant_context()
        assert ctx.organization_name == "Alpha Corp"
        assert ctx.metadata["tier"] == "enterprise"
    finally:
        reset_tenant_context(token)

    assert get_current_tenant_id() == initial_tenant


def test_sync_tenant_scope() -> None:
    """Verify synchronous context manager scoping."""
    initial = get_current_tenant_id()
    with sync_tenant_scope("tenant_sync_scope_1"):
        assert get_current_tenant_id() == "tenant_sync_scope_1"
    assert get_current_tenant_id() == initial


@pytest.mark.asyncio
async def test_async_tenant_scope_concurrency() -> None:
    """Verify that async tenant scopes are isolated across concurrent tasks."""
    async def worker(tenant_name: str, delay: float) -> str:
        async with tenant_scope(tenant_name):
            await asyncio.sleep(delay)
            return get_current_tenant_id()

    results = await asyncio.gather(
        worker("tenant_task_1", 0.02),
        worker("tenant_task_2", 0.01),
        worker("tenant_task_3", 0.03),
    )
    assert results == ["tenant_task_1", "tenant_task_2", "tenant_task_3"]


def test_tenant_middleware_header_resolution() -> None:
    """Verify TenantContextMiddleware extracts tenant from X-Tenant-ID header."""
    test_app = FastAPI()
    test_app.add_middleware(TenantContextMiddleware, default_tenant="default_test_tenant")

    @test_app.get("/test-tenant")
    async def test_endpoint(request: Request) -> JSONResponse:
        return JSONResponse({
            "state_tenant": getattr(request.state, "tenant_id", None),
            "context_tenant": get_current_tenant_id(),
        })

    client = TestClient(test_app)

    # 1. Header extraction
    resp = client.get("/test-tenant", headers={"X-Tenant-ID": "tenant_header_99"})
    assert resp.status_code == 200
    assert resp.headers["X-Tenant-ID"] == "tenant_header_99"
    data = resp.json()
    assert data["state_tenant"] == "tenant_header_99"
    assert data["context_tenant"] == "tenant_header_99"

    # 2. Query param extraction
    resp_query = client.get("/test-tenant?tenant_id=tenant_param_88")
    assert resp_query.status_code == 200
    assert resp_query.headers["X-Tenant-ID"] == "tenant_param_88"
    assert resp_query.json()["state_tenant"] == "tenant_param_88"

    # 3. Subdomain extraction
    resp_subdomain = client.get("/test-tenant", headers={"Host": "franchise42.apex.com"})
    assert resp_subdomain.status_code == 200
    assert resp_subdomain.headers["X-Tenant-ID"] == "franchise42"
    assert resp_subdomain.json()["state_tenant"] == "franchise42"

    # 4. Default fallback
    resp_default = client.get("/test-tenant")
    assert resp_default.status_code == 200
    assert resp_default.headers["X-Tenant-ID"] == "default_test_tenant"
    assert resp_default.json()["state_tenant"] == "default_test_tenant"
