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
Multi-Tenancy Isolation & Dynamic Context Middleware.

Enforces Plan 09 / GEES v2.0 Multi-Tenancy Architecture:
- Thread-safe asynchronous context variables (ContextVar).
- Deterministic tenant extraction from request headers, query params, or subdomains.
- Dual-mode support for sync and async execution scopes.
"""

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import logging
from typing import Any, AsyncGenerator, Callable, Dict, Generator, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core_platform.app.config import settings

logger = logging.getLogger("core_platform.middleware.tenant")


@dataclass(frozen=True)
class TenantContext:
    """Immutable representation of the active tenant execution context."""
    tenant_id: str
    organization_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# Asynchronous context variable tracking the active tenant
_current_tenant_ctx: ContextVar[Optional[TenantContext]] = ContextVar(
    "current_tenant_ctx",
    default=None,
)


def get_current_tenant_id() -> str:
    """
    Return the active tenant ID from current execution context.
    Falls back to settings.TENANT_ID if no dynamic context is bound.
    """
    ctx = _current_tenant_ctx.get()
    if ctx is not None and ctx.tenant_id.strip():
        return ctx.tenant_id.strip()
    return getattr(settings, "TENANT_ID", "default")


def get_current_tenant_context() -> TenantContext:
    """Return the active TenantContext object or default fallback context."""
    ctx = _current_tenant_ctx.get()
    if ctx is not None:
        return ctx
    return TenantContext(
        tenant_id=getattr(settings, "TENANT_ID", "default"),
        organization_name=getattr(settings, "ORGANIZATION_NAME", None),
        metadata={},
    )


def set_current_tenant_id(
    tenant_id: str,
    organization_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Token[Optional[TenantContext]]:
    """
    Explicitly set the active tenant context for the current async task.
    Returns the token needed to reset the context later.
    """
    ctx = TenantContext(
        tenant_id=tenant_id.strip() if tenant_id else getattr(settings, "TENANT_ID", "default"),
        organization_name=organization_name,
        metadata=metadata or {},
    )
    return _current_tenant_ctx.set(ctx)


def reset_tenant_context(token: Token[Optional[TenantContext]]) -> None:
    """Reset the tenant context variable to its previous state."""
    _current_tenant_ctx.reset(token)


@asynccontextmanager
async def tenant_scope(
    tenant_id: str,
    organization_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
    """
    Deterministic async context manager for scoping operations to a specific tenant.

    Usage:
        async with tenant_scope("tenant_retail_01"):
            await process_tenant_records()
    """
    token = set_current_tenant_id(
        tenant_id=tenant_id,
        organization_name=organization_name,
        metadata=metadata,
    )
    try:
        yield get_current_tenant_id()
    finally:
        reset_tenant_context(token)


@contextmanager
def sync_tenant_scope(
    tenant_id: str,
    organization_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Generator[str, None, None]:
    """
    Deterministic synchronous context manager for scoping operations to a specific tenant.

    Usage:
        with sync_tenant_scope("tenant_retail_01"):
            process_tenant_sync_jobs()
    """
    token = set_current_tenant_id(
        tenant_id=tenant_id,
        organization_name=organization_name,
        metadata=metadata,
    )
    try:
        yield get_current_tenant_id()
    finally:
        reset_tenant_context(token)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    FastAPI / Starlette Middleware that resolves tenant context per HTTP request.
    
    Resolution Order:
    1. Header: 'X-Tenant-ID' or 'X-Tenant'
    2. Query Parameter: 'tenant_id'
    3. Host Header Subdomain (e.g. 'tenantA.platform.local' -> 'tenantA')
    4. Fallback to settings.TENANT_ID
    """

    def __init__(self, app: Any, default_tenant: Optional[str] = None) -> None:
        super().__init__(app)
        self.default_tenant = default_tenant or getattr(settings, "TENANT_ID", "default")

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        tenant_id: str = self._resolve_tenant_id(request)

        # Attach tenant ID to request state for downstream handlers
        request.state.tenant_id = tenant_id

        # Bind context variable for downstream async execution
        token = set_current_tenant_id(tenant_id)
        try:
            response: Response = await call_next(request)
            # Inject response header for telemetry and verification
            response.headers["X-Tenant-ID"] = tenant_id
            return response
        finally:
            reset_tenant_context(token)

    def _resolve_tenant_id(self, request: Request) -> str:
        """Extract tenant ID from request attributes in priority order."""
        # 1. Custom HTTP Headers
        header_tenant = request.headers.get("X-Tenant-ID") or request.headers.get("X-Tenant")
        if header_tenant and header_tenant.strip():
            return header_tenant.strip()

        # 2. Query Parameters
        query_tenant = request.query_params.get("tenant_id")
        if query_tenant and query_tenant.strip():
            return query_tenant.strip()

        # 3. Host Subdomain (excluding standard localhost and raw IPs)
        host = request.headers.get("host", "").split(":")[0].strip()
        if host and "." in host and not host.replace(".", "").isdigit() and "localhost" not in host:
            subdomain = host.split(".")[0].strip()
            if subdomain and subdomain not in ("www", "api", "app", "kiosk", "admin"):
                return subdomain

        # 4. Fallback Default
        return self.default_tenant
