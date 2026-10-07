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
RBAC Entitlement Pruning Filter & FastAPI Dependencies.

Adheres strictly to Plan 02 v1.3 Section 3 (RBAC Engine).
Implements the RBAC Entitlement Formula:
    Candidate Apps = Tenant.EnabledApps ∩ Principal.PermittedApps

Routing cases:
    0 apps  → 403 Forbidden (zero LLM tokens consumed)
    1 app   → Direct dispatch (single-app bypass, zero routing cost)
    2+ apps → Advance to SemanticRouter for intent classification
"""

import logging
from typing import List, Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from core_platform.app.auth.models import SecurityContext
from core_platform.app.auth.strategies import AuthResolver
from core_platform.app.config import settings

logger = logging.getLogger("core_platform.rbac.permissions")


def _get_required_roles(app_id: str) -> List[str]:
    """Retrieve required roles for an app from the loaded cartridge.

    Uses a deferred import to avoid circular imports at module load time.
    Falls back to an empty list if the plugin loader is not yet initialised
    or the cartridge is not loaded (fail-open; the RBAC filter still enforces
    the tenant-enabled check).

    Args:
        app_id: Application cartridge identifier.

    Returns:
        List of role strings required to access this application.
    """
    try:
        from core_platform.main import plugin_loader  # deferred — avoids circular import
        app_instance = plugin_loader.get_application(app_id)
        if app_instance is not None:
            return list(app_instance.required_roles)
    except Exception:
        pass
    return []



class RBACFilter:
    """Entitlement pruning filter — resolves the candidate app list for a principal."""

    @classmethod
    def prune_candidate_apps(
        cls,
        context: SecurityContext,
        enabled_apps: Optional[List[str]] = None,
    ) -> List[str]:
        """Compute the intersection of tenant-enabled apps and principal-permitted apps.

        Also enforces role-level entitlements per app definition.

        Args:
            context: Authenticated principal SecurityContext.
            enabled_apps: Platform-enabled app list; defaults to settings.ENABLED_APPLICATIONS.

        Returns:
            Ordered list of apps this principal may access.
        """
        if enabled_apps is None:
            if settings.ENABLED_APPLICATIONS is not None:
                enabled_apps = list(settings.ENABLED_APPLICATIONS)
            else:
                try:
                    from core_platform.main import plugin_loader
                    enabled_apps = list(plugin_loader.get_all_applications().keys())
                except Exception:
                    enabled_apps = []

            # If principal is scoped to a customer tenant, constrain by tenant-allowed cartridges
            if context.tenant_id and context.tenant_id not in ("default_tenant", "system", "public", "platform"):
                try:
                    from sqlalchemy import select
                    from core_platform.app.db.manager import get_db_manager
                    from core_platform.app.identity.models import Tenant
                    db_mgr = get_db_manager()
                    with db_mgr.get_session() as session:
                        tenant_obj = session.scalar(select(Tenant).where(Tenant.id == context.tenant_id))
                        if tenant_obj and tenant_obj.allowed_cartridges is not None:
                            enabled_apps = [a for a in enabled_apps if a in tenant_obj.allowed_cartridges]
                except Exception:
                    pass

        if not context.is_authenticated:
            return []

        candidate_apps: List[str] = []
        for app_id in enabled_apps:
            # Check principal has at least one required role for this app.
            required_roles = _get_required_roles(app_id)
            has_role = (
                not required_roles  # No role restriction
                or any(r in context.user_roles for r in required_roles)
            )
            # Check principal's permitted_apps (from API key / JWT claims).
            in_permitted = not context.permitted_apps or app_id in context.permitted_apps

            if has_role and in_permitted:
                candidate_apps.append(app_id)

        if not candidate_apps:
            logger.warning(
                "[RBACFilter] Principal %s has no permitted apps. Roles=%s",
                context.principal_id,
                context.user_roles,
            )

        return candidate_apps

    @classmethod
    def assert_app_access(cls, context: SecurityContext, app_id: str) -> None:
        """Assert that a principal has access to a specific app.

        Args:
            context: Authenticated SecurityContext.
            app_id: Target application identifier.

        Raises:
            HTTPException: 403 if access is denied.
        """
        permitted = cls.prune_candidate_apps(context)
        if app_id not in permitted:
            logger.warning(
                "[RBACFilter] Access denied: principal=%s app=%s roles=%s",
                context.principal_id,
                app_id,
                context.user_roles,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to application '{app_id}'. "
                       f"Required role or tenant entitlement not held by principal '{context.principal_id}'.",
            )


# ── FastAPI Dependencies ──────────────────────────────────────────────────────

from typing import Callable, List, Optional


def get_web_security_context(
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> SecurityContext:
    """FastAPI dependency: extract SecurityContext from the admin JWT cookie, Bearer header, or X-API-Key.

    Used on all web admin routes to enforce authentication.

    Args:
        admin_token: JWT from the 'admin_token' cookie.
        authorization: Bearer token or API key from Authorization header.
        api_key: API key from X-API-Key header.

    Returns:
        Authenticated SecurityContext.

    Raises:
        HTTPException: 401 if credentials are missing or invalid.
    """
    ctx: Optional[SecurityContext] = None

    token_val = admin_token if isinstance(admin_token, str) and admin_token else None
    auth_val = authorization if isinstance(authorization, str) and authorization else None
    key_val = api_key if isinstance(api_key, str) and api_key else None

    if token_val:
        ctx = AuthResolver.resolve_web(token_val)

    if ctx is None and auth_val:
        raw_auth = auth_val.removeprefix("Bearer ").strip()
        if raw_auth.startswith("ak_live_"):
            ctx = AuthResolver.resolve_api_key(raw_auth)
        else:
            ctx = AuthResolver.resolve_web(raw_auth)

    if ctx is None and key_val:
        ctx = AuthResolver.resolve_api_key(key_val.strip())

    if not ctx or not ctx.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in at /admin/login.",
            headers={"Location": "/admin/login"},
        )
    return ctx


def is_devops_context(ctx: SecurityContext) -> bool:
    """Helper to determine if SecurityContext holds DevOps Super-Admin authority."""
    return (
        ctx.principal_id in ("devops_admin", "master_admin", "system")
        or (ctx.principal_id == "admin" and ctx.tenant_id in ("default_tenant", "public", "system", "platform", None))
        or "super_admin" in ctx.user_roles
        or "devops_admin" in ctx.user_roles
    )


def require_devops(
    request: Request,
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> SecurityContext:
    """FastAPI dependency: require DevOps Super-Admin / Platform Operator privileges."""
    # Guard: DevOps Control Plane is strictly barred on customer tenant domains/subdomains
    from core_platform.app.middleware.tenant_context import is_customer_subdomain
    host = request.headers.get("host", "").split(":")[0].strip().lower()
    if is_customer_subdomain(host):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DevOps Control Plane is not accessible on customer tenant domains.",
        )

    ctx = get_web_security_context(admin_token=admin_token, authorization=authorization, api_key=api_key)
    if not is_devops_context(ctx):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DevOps Super-Admin privileges required to access operational control plane or host settings.",
        )
    return ctx


def require_admin(
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> SecurityContext:
    """FastAPI dependency: require admin or devops role."""
    ctx = get_web_security_context(admin_token=admin_token, authorization=authorization, api_key=api_key)
    if not (ctx.is_admin or is_devops_context(ctx)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return ctx


def require_roles(*allowed_roles: str) -> Callable[..., SecurityContext]:
    """FastAPI dependency factory: require at least one of the specified roles (SEC-8)."""
    def _role_checker(
        admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ) -> SecurityContext:
        ctx = get_web_security_context(admin_token=admin_token, authorization=authorization, api_key=api_key)
        if not any(r in ctx.user_roles for r in allowed_roles) and not is_devops_context(ctx):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}",
            )
        return ctx
    return _role_checker


def require_app(app_id: str) -> Callable[..., SecurityContext]:
    """FastAPI dependency factory: assert access to a specific application cartridge (SEC-8)."""
    def _app_checker(
        admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ) -> SecurityContext:
        ctx = get_web_security_context(admin_token=admin_token, authorization=authorization, api_key=api_key)
        RBACFilter.assert_app_access(ctx, app_id)
        return ctx
    return _app_checker


def get_api_security_context(request: Request) -> SecurityContext:
    """FastAPI dependency: extract SecurityContext from Bearer API key header.

    Used on MCP and REST API endpoints.

    Args:
        request: FastAPI request object.

    Returns:
        Authenticated SecurityContext.

    Raises:
        HTTPException: 401 if key is missing or invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Use 'Authorization: Bearer ak_live_...' header.",
        )

    raw_key = auth_header.removeprefix("Bearer ").strip()
    ctx = AuthResolver.resolve_api_key(raw_key)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )
    return ctx
