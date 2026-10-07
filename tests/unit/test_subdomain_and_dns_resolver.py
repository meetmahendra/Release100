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
Unit tests for Subdomain & Dynamic DNS Domain Resolution Middleware.
Validates:
1. Subdomain resolution (e.g. acme.release100.com -> acme).
2. Custom CNAME domain resolution from in-memory cache and database.
3. Default fallback to 'public' tenant context for apex / unmapped hosts.
4. Explicit header and query parameter priority overrides.
"""

from pathlib import Path
from typing import Any, Dict
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core_platform.app.identity.models import Base, Tenant, TenantDomain
from core_platform.app.middleware.tenant_context import (
    TenantContextMiddleware,
    clear_domain_mappings,
    get_current_tenant_id,
    register_domain_mapping,
    resolve_domain_to_tenant,
)


@pytest.fixture
def app_with_middleware() -> FastAPI:
    """Create FastAPI test application with TenantContextMiddleware attached."""
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware, default_tenant="public")

    @app.get("/test/tenant")
    async def get_active_tenant(request: Request) -> Dict[str, Any]:
        return {
            "tenant_id": get_current_tenant_id(),
            "state_tenant": getattr(request.state, "tenant_id", None),
        }

    return app


@pytest.fixture(autouse=True)
def clean_cache() -> None:
    """Clear in-memory domain cache before each test."""
    clear_domain_mappings()


def test_subdomain_extraction_from_host(app_with_middleware: FastAPI) -> None:
    """Verify subdomain extraction from Host header (acme.release100.com -> acme)."""
    client = TestClient(app_with_middleware)
    resp = client.get("/test/tenant", headers={"host": "acme.release100.com"})
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "acme"
    assert resp.headers["X-Tenant-ID"] == "acme"


def test_custom_cname_domain_resolution_cached(app_with_middleware: FastAPI) -> None:
    """Verify custom CNAME domain resolution from in-memory cache."""
    register_domain_mapping("mail.acme-logistics.com", "acme_logistics")

    client = TestClient(app_with_middleware)
    resp = client.get("/test/tenant", headers={"host": "mail.acme-logistics.com"})
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "acme_logistics"
    assert resp.headers["X-Tenant-ID"] == "acme_logistics"


def test_public_default_fallback(app_with_middleware: FastAPI) -> None:
    """Verify apex domain, raw IP, and unmapped hosts fall back to 'public'."""
    client = TestClient(app_with_middleware)

    # Apex domain
    resp1 = client.get("/test/tenant", headers={"host": "release100.com"})
    assert resp1.json()["tenant_id"] == "public"

    # Localhost
    resp2 = client.get("/test/tenant", headers={"host": "localhost:8000"})
    assert resp2.json()["tenant_id"] == "public"

    # Raw IP
    resp3 = client.get("/test/tenant", headers={"host": "192.168.1.50"})
    assert resp3.json()["tenant_id"] == "public"

    # Standard prefix (www, app, api)
    resp4 = client.get("/test/tenant", headers={"host": "app.release100.com"})
    assert resp4.json()["tenant_id"] == "public"


def test_header_and_query_param_priority(app_with_middleware: FastAPI) -> None:
    """Verify explicit X-Tenant-ID header and query param take precedence over subdomain."""
    client = TestClient(app_with_middleware)

    # Header override
    resp1 = client.get(
        "/test/tenant",
        headers={"host": "acme.release100.com", "X-Tenant-ID": "override_tenant_xyz"},
    )
    assert resp1.json()["tenant_id"] == "override_tenant_xyz"

    # Query param override
    resp2 = client.get(
        "/test/tenant?tenant_id=query_tenant_abc",
        headers={"host": "acme.release100.com"},
    )
    assert resp2.json()["tenant_id"] == "query_tenant_abc"
