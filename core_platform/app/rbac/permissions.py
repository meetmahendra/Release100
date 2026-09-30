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

from fastapi import Cookie, HTTPException, Request, status

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
            enabled_apps = list(settings.ENABLED_APPLICATIONS)

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
                       f"Required role not held by principal '{context.principal_id}'.",
            )


# ── FastAPI Dependencies ──────────────────────────────────────────────────────

def get_web_security_context(
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
) -> SecurityContext:
    """FastAPI dependency: extract SecurityContext from the admin JWT cookie.

    Used on all web admin routes to enforce authentication.

    Args:
        admin_token: JWT from the 'admin_token' cookie (injected by FastAPI).

    Returns:
        Authenticated SecurityContext.

    Raises:
        HTTPException: 401 if the token is missing or invalid.
    """
    if not admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in at /admin/login.",
            headers={"Location": "/admin/login"},
        )

    ctx = AuthResolver.resolve_web(admin_token)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
            headers={"Location": "/admin/login"},
        )
    return ctx


def require_admin(
    admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
) -> SecurityContext:
    """FastAPI dependency: require admin role.

    Args:
        admin_token: JWT from cookie.

    Returns:
        SecurityContext with admin role confirmed.

    Raises:
        HTTPException: 401 if not authenticated, 403 if not admin.
    """
    ctx = get_web_security_context(admin_token)
    if "admin" not in ctx.user_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return ctx


from typing import Callable, List, Optional

def require_roles(*allowed_roles: str) -> Callable[[Optional[str]], SecurityContext]:
    """FastAPI dependency factory: require at least one of the specified roles (SEC-8)."""
    def _role_checker(
        admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    ) -> SecurityContext:
        ctx = get_web_security_context(admin_token)
        if not any(r in ctx.user_roles for r in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}",
            )
        return ctx
    return _role_checker


def require_app(app_id: str) -> Callable[[Optional[str]], SecurityContext]:
    """FastAPI dependency factory: assert access to a specific application cartridge (SEC-8)."""
    def _app_checker(
        admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
    ) -> SecurityContext:
        ctx = get_web_security_context(admin_token)
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
