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


@dataclass(frozen=True)
class UserContext:
    """Immutable representation of the active authenticated user context."""
    user_id: Any
    phone_number: str
    tenant_id: str = "default_tenant"
    full_name: str = ""
    role: str = "user"
    user_secret_salt: str = ""
    allowed_cartridges: tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)


# Asynchronous context variable tracking the active tenant
_current_tenant_ctx: ContextVar[Optional[TenantContext]] = ContextVar(
    "current_tenant_ctx",
    default=None,
)

# Asynchronous context variable tracking the active user
_current_user_ctx: ContextVar[Optional[UserContext]] = ContextVar(
    "current_user_ctx",
    default=None,
)


def get_current_user_context() -> Optional[UserContext]:
    """Return the active UserContext or None if not set."""
    return _current_user_ctx.get()


def set_current_user_context(user_context: UserContext) -> Token[Optional[UserContext]]:
    """Set active user context for the current async task / thread."""
    return _current_user_ctx.set(user_context)


def reset_user_context(token: Token[Optional[UserContext]]) -> None:
    """Reset user context variable to previous state."""
    _current_user_ctx.reset(token)


@contextmanager
def user_scope(user_context: UserContext) -> Generator[UserContext, None, None]:
    """Context manager for scoping execution to a specific UserContext."""
    token = set_current_user_context(user_context)
    try:
        yield user_context
    finally:
        reset_user_context(token)


@asynccontextmanager
async def async_user_scope(user_context: UserContext) -> AsyncGenerator[UserContext, None]:
    """Async context manager for scoping async tasks to a specific UserContext."""
    token = set_current_user_context(user_context)
    try:
        yield user_context
    finally:
        reset_user_context(token)



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


# In-memory cache for dynamic custom domains / subdomains
_domain_tenant_cache: Dict[str, str] = {}


def register_domain_mapping(domain_name: str, tenant_id: str) -> None:
    """Register or update an in-memory domain-to-tenant mapping."""
    clean_domain = domain_name.lower().strip()
    if clean_domain and tenant_id:
        _domain_tenant_cache[clean_domain] = tenant_id.strip()


def clear_domain_mappings() -> None:
    """Clear cached domain mappings."""
    _domain_tenant_cache.clear()


def resolve_domain_to_tenant(domain_name: str) -> Optional[str]:
    """Resolve a domain or host string to a tenant ID using cache or database lookup."""
    clean_host = domain_name.lower().split(":")[0].strip()
    if not clean_host:
        return None

    # 1. Check in-memory fast cache
    if clean_host in _domain_tenant_cache:
        return _domain_tenant_cache[clean_host]

    # 2. Query platform_tenant_domains table
    try:
        from sqlalchemy import select
        from core_platform.app.db.manager import get_db_manager
        from core_platform.app.identity.models import TenantDomain

        engine = get_db_manager().get_engine()
        with engine.connect() as conn:
            stmt = select(TenantDomain.tenant_id).where(
                TenantDomain.domain_name == clean_host,
                TenantDomain.is_verified == True,  # noqa: E712
            ).limit(1)
            row = conn.execute(stmt).fetchone()
            if row:
                tenant_id = str(row[0])
                _domain_tenant_cache[clean_host] = tenant_id
                return tenant_id
    except Exception:
        pass

    return None


def verify_tenant_exists(tenant_id: str) -> Optional[str]:
    """Check if tenant exists in platform_tenants (supporting hyphen/underscore variants)."""
    clean = tenant_id.lower().strip()
    if clean in ("public", "default", "default_tenant", "platform", "system", "test"):
        return clean
    variants = list(dict.fromkeys([
        clean,
        clean.replace("-", "_"),
        clean.replace("_", "-"),
    ]))
    try:
        from sqlalchemy import or_, select
        from core_platform.app.db.manager import get_db_manager
        from core_platform.app.identity.models import Tenant, TenantDomain

        engine = get_db_manager().get_engine()
        with engine.connect() as conn:
            # 1. Check Tenant.id
            stmt = select(Tenant.id).where(Tenant.id.in_(variants)).limit(1)
            row = conn.execute(stmt).fetchone()
            if row:
                return str(row[0])

            # 2. Check TenantDomain.domain_name
            dom_names = [f"{v}.release100.com" for v in variants] + variants
            dom_stmt = select(TenantDomain.tenant_id).where(
                TenantDomain.domain_name.in_(dom_names),
                TenantDomain.is_verified == True,  # noqa: E712
            ).limit(1)
            dom_row = conn.execute(dom_stmt).fetchone()
            if dom_row:
                return str(dom_row[0])
    except Exception:
        pass
    return None


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    FastAPI / Starlette Middleware that resolves tenant context per HTTP request.
    
    Resolution Order:
    1. Header: 'X-Tenant-ID' or 'X-Tenant'
    2. Query Parameter: 'tenant_id'
    3. Custom Verified Domain / CNAME (e.g. 'mail.acme.com' -> 'acme')
    4. Host Header Subdomain (e.g. 'acme.release100.com' -> 'acme')
    5. Fallback Default to 'public'
    """

    def __init__(self, app: Any, default_tenant: Optional[str] = None) -> None:
        super().__init__(app)
        self.default_tenant: str = str(default_tenant or getattr(settings, "TENANT_ID", "public") or "public")

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        tenant_id: str = self._resolve_tenant_id(request)

        # Attach tenant ID to request state for downstream handlers
        request.state.tenant_id = tenant_id

        # If tenant was explicitly requested via customer subdomain but does not exist in DB:
        if getattr(request.state, "tenant_not_found", False):
            path = request.url.path
            # Allow health check, favicon, logs, static assets, UI gallery, and mock test paths to pass through
            if not path.startswith(("/health", "/favicon.ico", "/logs", "/static", "/test", "/ui-gallery")):
                from fastapi.responses import HTMLResponse, JSONResponse
                unregistered = getattr(request.state, "unregistered_tenant", tenant_id)
                accept = request.headers.get("accept", "")
                if "text/html" in accept or not ("application/json" in accept):
                    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tenant Not Found — Release100</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 2.5rem; max-width: 500px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        h1 {{ font-size: 1.5rem; margin-bottom: 0.75rem; color: #f43f5e; }}
        p {{ color: #94a3b8; line-height: 1.6; margin-bottom: 1.5rem; }}
        code {{ background: #0f172a; color: #38bdf8; padding: 0.2rem 0.4rem; border-radius: 4px; font-size: 0.9em; }}
        .btn {{ display: inline-block; background: #3b82f6; color: white; text-decoration: none; padding: 0.6rem 1.2rem; border-radius: 6px; font-weight: 500; }}
        .btn:hover {{ background: #2563eb; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Tenant Not Found (404)</h1>
        <p>The organization partition <code>{unregistered}</code> does not exist or has not been registered yet on Release100.</p>
        <p>If you are an administrator, please register this tenant from the platform operations control plane.</p>
    </div>
</body>
</html>"""
                    return HTMLResponse(content=html_content, status_code=404)
                return JSONResponse(
                    status_code=404,
                    content={"detail": f"Tenant '{unregistered}' does not exist on this platform."},
                )

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

        # 3. Custom Domain / Host resolution
        host = request.headers.get("host", "").split(":")[0].strip().lower()
        if host:
            resolved = resolve_domain_to_tenant(host)
            if resolved:
                return resolved

            # 4. Host Subdomain (requires at least 3 domain segments, e.g. 'acme.release100.com' -> 'acme')
            tunnel_domains = ("ngrok-free.dev", "ngrok-free.app", "ngrok.app", "loca.lt", "lhr.life", "pinggy.link", "pinggy.io", "localhost.run")
            is_tunnel = any(host.endswith(td) for td in tunnel_domains)
            if not is_tunnel and "." in host and not host.replace(".", "").isdigit() and "localhost" not in host:
                parts = host.split(".")
                if len(parts) >= 3:
                    subdomain = parts[0].strip()
                    if subdomain in ("ops", "ops-admin"):
                        request.state.is_ops_domain = True
                        return self.default_tenant
                    elif subdomain not in ("www", "api", "app", "kiosk", "admin", "public"):
                        real_tenant = verify_tenant_exists(subdomain)
                        if real_tenant:
                            return real_tenant
                        else:
                            request.state.tenant_not_found = True
                            request.state.unregistered_tenant = subdomain
                            return subdomain

        # 5. Session Cookie (admin_token) or Authorization Header (JWT)
        auth_cookie = request.cookies.get("admin_token")
        auth_header = request.headers.get("Authorization")
        raw_jwt: Optional[str] = None
        if auth_cookie and auth_cookie.strip():
            raw_jwt = auth_cookie.strip()
        elif auth_header and auth_header.startswith("Bearer "):
            raw_jwt = auth_header[7:].strip()

        if raw_jwt:
            try:
                from core_platform.app.auth.jwt_utils import verify_jwt_token
                s_ctx = verify_jwt_token(raw_jwt)
                if s_ctx and s_ctx.tenant_id and s_ctx.tenant_id.strip():
                    return s_ctx.tenant_id.strip()
            except Exception:
                pass

        # 6. Fallback Default to 'public'
        return self.default_tenant


def resolve_effective_tenant_info(
    request: Request,
    ctx: Optional[Any] = None,
) -> tuple[str, str, Optional[Any]]:
    """
    Resolve active (tenant_id, tenant_name, tenant_obj) for any request and security context.

    Rules:
    1. If security context is non-devops customer user/admin: strictly bound to ctx.tenant_id.
    2. If security context is devops: respects ?tenant_id= query param, request.state, or ctx.tenant_id.
    3. Resolves the Tenant database record to fetch real organization name.
    """
    req_tenant = getattr(request.state, "tenant_id", None)
    user_tenant = ctx.tenant_id if (ctx and getattr(ctx, "tenant_id", None) and ctx.tenant_id not in ("default_tenant", "system", "public", "platform")) else None

    is_devops = False
    if ctx:
        is_devops = (
            getattr(ctx, "is_devops", False)
            or getattr(ctx, "principal_id", "") in ("devops_admin", "master_admin", "system", "admin")
            or "super_admin" in getattr(ctx, "user_roles", [])
            or "devops_admin" in getattr(ctx, "user_roles", [])
        )

    # Scoping logic
    if not is_devops and user_tenant:
        active_slug = user_tenant
    elif req_tenant and req_tenant not in ("public", "default", "default_tenant"):
        active_slug = req_tenant
    elif user_tenant:
        active_slug = user_tenant
    else:
        active_slug = req_tenant or "public"

    # Query Tenant record from DB (supporting hyphen/underscore variants)
    tenant_obj = None
    org_name = getattr(settings, "ORGANIZATION_NAME", "Release100 Organization") or "Release100 Organization"
    try:
        from sqlalchemy import select
        from core_platform.app.db.manager import get_db_manager
        from core_platform.app.identity.models import Tenant
        db_mgr = get_db_manager()
        with db_mgr.get_session() as session:
            variants = list(dict.fromkeys([
                active_slug,
                active_slug.replace("-", "_"),
                active_slug.replace("_", "-"),
            ]))
            tenant_obj = session.scalar(select(Tenant).where(Tenant.id.in_(variants)))
            if not tenant_obj and active_slug != "public":
                tenant_obj = session.scalar(select(Tenant).where(Tenant.id == "public"))
            if tenant_obj and tenant_obj.name:
                org_name = tenant_obj.name
                active_slug = tenant_obj.id
    except Exception:
        pass

    return (active_slug, org_name, tenant_obj)

