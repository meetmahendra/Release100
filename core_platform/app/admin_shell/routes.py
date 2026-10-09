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
Central Web Administration Shell Routes.

Adheres strictly to Plan 02 v1.3 Section 11 (Admin Shell Navigation).
Provides:
  GET  /admin/login          — Login form
  POST /admin/login          — Credential validation → JWT cookie
  GET  /admin/logout         — Clear session cookie
  GET  /admin/               — Shell landing: health metrics + app navigation
  GET  /admin/api-keys       — API key management (list / create / revoke)
  POST /admin/api-keys       — Create a new scoped API key
  POST /admin/api-keys/revoke — Revoke an existing API key

Navigation sidebar is pruned to only show apps the authenticated principal
may access (SecurityContext.permitted_apps ∩ enabled_applications).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core_platform.app.auth.api_keys import get_api_key_manager
from core_platform.app.auth.csrf import generate_csrf_token, verify_csrf_token
from core_platform.app.auth.jwt_utils import create_jwt_token, revoke_jwt_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.auth.strategies import AuthResolver
from core_platform.app.config import settings
from core_platform.app.ingress.rate_limiter import get_platform_rate_limiter
from core_platform.app.llm.gateway import get_platform_llm_gateway
from core_platform.app.rbac.permissions import (get_web_security_context, is_devops_context, require_devops)
from core_platform.app.ui.templating import build_templates
from core_platform.app.ui.ui_context import Breadcrumb, build_ui_context

logger = logging.getLogger("core_platform.admin_shell")

router = APIRouter(prefix="/admin", tags=["Admin Shell"])
templates = build_templates([Path(__file__).parent / "templates"])


# ── Auth Routes ───────────────────────────────────────────────────────────────

def _render_login_view(
    request: Request,
    error: Optional[str] = None,
    status_code: int = 200,
    force_new_csrf: bool = False,
) -> HTMLResponse:
    """Helper to render login.html ensuring CSRF cookie and form token are always in sync."""
    if force_new_csrf:
        csrf_token = generate_csrf_token()
    else:
        csrf_token = request.cookies.get("csrf_token") or generate_csrf_token()

    tenant_info = getattr(request.state, "tenant_info", None)
    if not tenant_info:
        from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info
        tenant_id, tenant_name, _ = resolve_effective_tenant_info(request)
        if tenant_id and tenant_id not in ("public", "default", "default_tenant"):
            tenant_info = {"id": tenant_id, "name": tenant_name}

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=None,
        shell_mode="bare",
        tenant_name=tenant_info.get("name") if tenant_info else None,
    )

    resp = templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"title": "Admin Login", "error": error, "csrf_token": csrf_token, "tenant": tenant_info, "ui": ui_ctx},
        status_code=status_code,
    )
    resp.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        samesite="lax",
        secure=bool(settings.EXECUTION_MODE == "production" or getattr(settings, "COOKIE_SECURE", False)),
        max_age=8 * 3600,
    )
    return resp


@router.get("/login")
async def login_page(request: Request) -> Any:
    """Render the login page with anti-CSRF token, or auto-redirect if session is active."""
    token = request.cookies.get("admin_token")
    if token:
        try:
            ctx = AuthResolver.resolve_web(f"Bearer {token}")
            if ctx and ctx.is_authenticated:
                target_url = "/ops/tenants" if is_devops_context(ctx) else "/admin/"
                return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
        except Exception:
            pass
    return _render_login_view(request)


@router.post("/login")
async def login_submit(
    response: Response,
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: Optional[str] = Form(default=None),
) -> Any:
    """Process login form with Brute-Force Rate Limiting (SEC-4) & Anti-CSRF (SEC-3).

    Args:
        response: FastAPI response.
        request: FastAPI request.
        username: Form field.
        password: Form field.
        csrf_token: Form field token.

    Returns:
        Redirect to /admin/ on success, re-rendered login page on failure.
    """
    # 1. Anti-CSRF verification (SEC-3)
    if not verify_csrf_token(request, submitted_token=csrf_token):
        logger.warning("[AdminShell] CSRF validation failed during login attempt.")
        return _render_login_view(
            request=request,
            error="Invalid session token. Please try again.",
            status_code=403,
            force_new_csrf=True,
        )

    # 2. Brute-Force Rate Limiting (SEC-4)
    client_ip = request.client.host if request.client else "unknown_ip"
    rate_limiter = get_platform_rate_limiter()
    ip_allowed, _ = rate_limiter.check_and_consume(f"login_ip:{client_ip}")
    user_allowed, _ = rate_limiter.check_and_consume(f"login_user:{username.strip().lower()}")

    if not ip_allowed or not user_allowed:
        logger.warning("[AdminShell] Brute-force protection triggered for IP=%s user=%s", client_ip, username)
        return _render_login_view(
            request=request,
            error="Too many failed login attempts. Please wait 60 seconds and try again.",
            status_code=429,
        )

    # 3. Credential validation (SEC-1)
    from core_platform.app.middleware.tenant_context import get_current_tenant_id
    req_tenant = get_current_tenant_id()
    ctx = AuthResolver.resolve_credentials(username, password, tenant_id=req_tenant)
    if not ctx:
        return _render_login_view(
            request=request,
            error="Invalid credentials.",
            status_code=401,
        )

    # 4. Token creation & Cookie hardening (SEC-2, SEC-5)
    token = create_jwt_token(
        principal_id=ctx.principal_id,
        roles=ctx.user_roles,
        permitted_apps=ctx.permitted_apps,
        tenant_id=ctx.tenant_id,
    )
    # Determine target redirect URL based on host domain and role
    host = request.headers.get("host", "").split(":")[0].strip().lower()
    is_customer_domain = False
    if "." in host and not host.replace(".", "").isdigit() and "localhost" not in host:
        parts = host.split(".")
        if len(parts) >= 3 and parts[0] not in ("www", "api", "app", "public", "ops", "ops-admin", "admin"):
            is_customer_domain = True
    if req_tenant not in ("public", "default", "default_tenant", "platform", "system", "ops"):
        is_customer_domain = True

    if ("devops_admin" in ctx.user_roles or "super_admin" in ctx.user_roles) and not is_customer_domain:
        target_url = "/ops/tenants"
    else:
        target_url = "/admin/"

    redirect = RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=bool(settings.EXECUTION_MODE == "production" or getattr(settings, "COOKIE_SECURE", False)),
        max_age=8 * 3600,
    )
    logger.info("[AdminShell] Login success: principal=%s tenant=%s target=%s", ctx.principal_id, ctx.tenant_id, target_url)
    return redirect


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Revoke session token and clear cookies (SEC-2, SEC-5).

    Returns:
        Redirect to /admin/login with cookie cleared and token blacklisted.
    """
    token = request.cookies.get("admin_token")
    if token:
        revoke_jwt_token(token)

    redirect = RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie("admin_token")
    redirect.delete_cookie("csrf_token")
    return redirect


# ── Shell Dashboard ───────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
) -> HTMLResponse:
    """Render the admin shell landing page with health metrics.

    Args:
        request: FastAPI request.
        ctx: Authenticated SecurityContext.

    Returns:
        Rendered shell.html template.
    """
    gateway = get_platform_llm_gateway()
    llm_health = gateway.get_health()

    # Determine active tenant context
    from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info
    eff_tenant, tenant_name, active_tenant = resolve_effective_tenant_info(request, ctx)
    active_tenant_slug = eff_tenant

    is_devops = (
        ctx.principal_id in ("devops_admin", "master_admin", "system", "admin")
        or "super_admin" in ctx.user_roles
        or "devops_admin" in ctx.user_roles
    )

    from sqlalchemy import func, select
    from core_platform.app.db.manager import get_db_manager
    from core_platform.app.identity.models import PlatformUser

    db_mgr = get_db_manager()
    total_tenant_users = 0
    try:
        with db_mgr.get_session() as session:
            total_tenant_users = session.scalar(
                select(func.count(PlatformUser.id)).where(PlatformUser.tenant_id == active_tenant_slug)
            ) or 0
    except Exception:
        total_tenant_users = 0

    nav_apps = _build_nav_apps(ctx, active_tenant)

    from core_platform.app.diagnostics.config_backup import read_env_dict
    from core_platform.app.telemetry.audit_engine import AuditEngine

    env_data = read_env_dict()
    gemini_key = env_data.get("GEMINI_API_KEY", settings.GEMINI_API_KEY or "")
    wa_token = env_data.get("WHATSAPP_ACCESS_TOKEN", settings.WHATSAPP_ACCESS_TOKEN or "")
    wa_phone = env_data.get("WHATSAPP_PHONE_NUMBER_ID", settings.WHATSAPP_PHONE_NUMBER_ID or "")
    relay_url = env_data.get("RELAY_WS_URL", settings.RELAY_WS_URL or "")

    audit_engine = AuditEngine.get_instance()
    recent_audits = []
    if hasattr(audit_engine, "_active_records"):
        recent_audits = list(reversed(audit_engine._active_records[-5:]))

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=[a["id"] for a in nav_apps],
        tenant_name=str(tenant_name),
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.overview", path="/admin/"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="shell.html",
        context={
            "title": f"Workspace Admin — {tenant_name}",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "is_devops": is_devops,
            "active_tenant": active_tenant,
            "tenant_id": active_tenant_slug,
            "tenant_name": tenant_name,
            "total_tenant_users": total_tenant_users,
            "nav_apps": nav_apps,
            "enabled_applications": list(settings.ENABLED_APPLICATIONS) if settings.ENABLED_APPLICATIONS is not None else [a["id"] for a in nav_apps],
            "dry_run": settings.DRY_RUN,
            "execution_mode": settings.EXECUTION_MODE,
            "organization": tenant_name,
            "station": settings.STATION_NAME,
            "kiosk_id": settings.KIOSK_ID,
            "llm_providers": llm_health,
            "gemini_configured": bool(gemini_key and len(gemini_key) > 8),
            "whatsapp_configured": bool(wa_token and wa_phone),
            "relay_configured": bool(relay_url),
            "relay_url": relay_url,
            "last_audit_sequence": audit_engine._sequence_counter,
            "last_audit_hash": audit_engine._last_hash,
            "recent_audits": recent_audits,
            "ui": ui_ctx,
        },
    )


# ── API Key Management ────────────────────────────────────────────────────────

@router.get("/api-keys", response_class=HTMLResponse)
async def view_api_keys(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
) -> HTMLResponse:
    """List all API keys.

    Args:
        request: FastAPI request.
        ctx: Authenticated SecurityContext.

    Returns:
        Shell page with API key list.
    """
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required.")

    from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info
    eff_tenant, tenant_name, active_tenant = resolve_effective_tenant_info(request, ctx)
    manager = get_api_key_manager()
    keys = manager.list_keys()
    nav_apps = _build_nav_apps(ctx, active_tenant)

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=[a["id"] for a in nav_apps],
        tenant_name=str(tenant_name),
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.platform_dashboard", path="/admin/"),
            Breadcrumb(label_key="core.nav.api_keys"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="shell.html",
        context={
            "title": f"API Keys — {tenant_name}",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "nav_apps": nav_apps,
            "api_keys": keys,
            "section": "api_keys",
            "tenant_id": eff_tenant,
            "tenant_name": tenant_name,
            "organization": tenant_name,
            "active_tenant": active_tenant,
            "ui": ui_ctx,
        },
    )


@router.post("/api-keys")
async def create_api_key(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    label: str = Form(...),
    permitted_apps_csv: str = Form(default=""),
    roles_csv: str = Form(default="admin"),
    max_rpm: int = Form(default=60),
    expiry_days: Optional[int] = Form(default=None),
) -> Any:
    """Create a new scoped API key.

    Args:
        request: FastAPI request.
        ctx: Authenticated SecurityContext (must be admin).
        label: Human-readable key label.
        permitted_apps_csv: Comma-separated app IDs.
        roles_csv: Comma-separated roles.
        max_rpm: Max requests per minute.
        expiry_days: Expiry in days (None = no expiry).

    Returns:
        JSON with the raw key (shown ONCE) and key hash.
    """
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")

    permitted_apps = [a.strip() for a in permitted_apps_csv.split(",") if a.strip()]
    roles = [r.strip() for r in roles_csv.split(",") if r.strip()]

    is_devops = is_devops_context(ctx)
    if not is_devops:
        # Prevent customer admins from creating DevOps/Super-Admin API keys
        roles = [r for r in roles if r not in ("devops_admin", "super_admin")]
        if not roles:
            roles = ["admin"]
        # Limit permitted apps to the tenant's actual allowed cartridges
        valid_apps = [a["id"] for a in _build_nav_apps(ctx)]
        if permitted_apps:
            permitted_apps = [a for a in permitted_apps if a in valid_apps]
        if not permitted_apps:
            permitted_apps = valid_apps

    manager = get_api_key_manager()
    raw_key, key_hash = manager.create_key(
        label=label,
        principal_id=ctx.principal_id,
        roles=roles,
        permitted_apps=permitted_apps or (list(settings.ENABLED_APPLICATIONS) if settings.ENABLED_APPLICATIONS is not None else []),
        max_rpm=max_rpm,
        tenant_id=ctx.tenant_id,
        expiry_days=expiry_days,
    )

    logger.info("[AdminShell] API key created: label=%s by=%s", label, ctx.principal_id)
    return JSONResponse(
        content={
            "raw_key": raw_key,
            "key_hash": key_hash,
            "label": label,
            "warning": "This raw key is shown ONCE. Copy it now — it cannot be retrieved again.",
        }
    )


@router.post("/api-keys/revoke")
async def revoke_api_key(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    key_hash: str = Form(...),
) -> JSONResponse:
    """Revoke an API key by its hash.

    Args:
        request: FastAPI request.
        ctx: Authenticated SecurityContext.
        key_hash: SHA-256 hash of the key to revoke.

    Returns:
        JSON confirmation.
    """
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")

    manager = get_api_key_manager()
    revoked = manager.revoke_key(key_hash)
    return JSONResponse(content={"revoked": revoked, "key_hash": key_hash})


# ── Multi-Tenant User Management ──────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
async def view_users(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    tenant_id: Optional[str] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> HTMLResponse:
    """List all registered platform users within the active scoped tenant."""
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required.")

    from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info
    eff_tenant, tenant_name, tenant_obj = resolve_effective_tenant_info(request, ctx)

    # Only super-admins can view or switch to cross-tenant user listings
    is_super = ctx.principal_id in ("devops_admin", "master_admin", "system") or "super_admin" in ctx.user_roles or "devops_admin" in ctx.user_roles
    effective_tenant = tenant_id if (tenant_id and is_super) else eff_tenant

    from core_platform.app.identity.service import get_user_identity_service
    user_service = get_user_identity_service()
    users = user_service.list_users(tenant_id=effective_tenant if effective_tenant != "*" else None)
    nav_apps = _build_nav_apps(ctx, tenant_obj)
    csrf_token = request.cookies.get("csrf_token") or generate_csrf_token()

    installed_app_ids = [a["id"] for a in nav_apps]
    if tenant_obj and hasattr(tenant_obj, "allowed_cartridges") and tenant_obj.allowed_cartridges is not None:
        tenant_cartridges = [c for c in tenant_obj.allowed_cartridges if c in installed_app_ids or c == "*"]
    else:
        tenant_cartridges = installed_app_ids

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=[a["id"] for a in nav_apps],
        tenant_name=str(tenant_name),
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.platform_dashboard", path="/admin/"),
            Breadcrumb(label_key="core.nav.users"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context={
            "title": f"User Registry — {tenant_name}",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "nav_apps": nav_apps,
            "users": users,
            "active_tenant": effective_tenant,
            "default_tenant_id": effective_tenant,
            "tenant_id": effective_tenant,
            "tenant_name": tenant_name,
            "organization": tenant_name,
            "tenant_cartridges": tenant_cartridges,
            "available_cartridges": nav_apps,
            "section": "users",
            "csrf_token": csrf_token,
            "message": message,
            "error": error,
            "ui": ui_ctx,
        },
    )


@router.post("/users")
async def create_user(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    phone_number: str = Form(...),
    full_name: str = Form(...),
    tenant_id: Optional[str] = Form(None),
    role: str = Form("user"),
    timezone: str = Form("UTC"),
    password: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    cartridges: Optional[List[str]] = Form(None),
    cartridge_mail: Optional[str] = Form(None),
    cartridge_temp: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """Register a new platform user automatically scoped to the active tenant."""
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required.")
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")

    from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info
    eff_tenant, tenant_name, tenant_obj = resolve_effective_tenant_info(request, ctx)

    is_super = ctx.principal_id in ("devops_admin", "master_admin", "system") or "super_admin" in ctx.user_roles or "devops_admin" in ctx.user_roles
    effective_tenant = tenant_id if (tenant_id and is_super) else eff_tenant

    allowed: List[str] = []
    if cartridges:
        allowed.extend(cartridges)
    if cartridge_mail and cartridge_mail not in allowed:
        allowed.append(cartridge_mail)
    if cartridge_temp and cartridge_temp not in allowed:
        allowed.append(cartridge_temp)

    # Scoping guard: restrict user cartridges strictly to tenant's allowed cartridges unless super-admin
    if tenant_obj and hasattr(tenant_obj, "allowed_cartridges") and not is_super:
        allowed = [c for c in allowed if c in tenant_obj.allowed_cartridges]
    if not allowed and tenant_obj and hasattr(tenant_obj, "allowed_cartridges"):
        allowed = list(tenant_obj.allowed_cartridges)

    from core_platform.app.identity.service import get_user_identity_service
    user_service = get_user_identity_service()
    try:
        user_service.register_user(
            phone_number=phone_number,
            full_name=full_name,
            tenant_id=effective_tenant,
            role=role,
            allowed_cartridges=allowed,
            timezone=timezone,
            password=password,
            email=email,
        )
        return RedirectResponse(url="/admin/users?message=User+registered+successfully", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        logger.error("[AdminShell] Failed to register user: %s", exc)
        return RedirectResponse(url=f"/admin/users?error={exc}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/status")
async def toggle_user_status(
    user_id: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    new_status: str = Form(..., alias="status"),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """Update user status with strict tenant boundary isolation."""
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    from core_platform.app.identity.service import get_user_identity_service
    user_service = get_user_identity_service()
    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    req_tenant = getattr(request.state, "tenant_id", None)
    user_tenant = ctx.tenant_id if ctx.tenant_id and ctx.tenant_id not in ("default_tenant", "system", "public") else None
    if req_tenant and req_tenant not in ("public", "default", "default_tenant"):
        active_tenant = req_tenant
    elif user_tenant:
        active_tenant = user_tenant
    else:
        active_tenant = req_tenant or "public"

    is_super = ctx.principal_id in ("devops_admin", "master_admin", "system") or "super_admin" in ctx.user_roles or "devops_admin" in ctx.user_roles

    if not is_super and user.tenant_id != active_tenant:
        raise HTTPException(status_code=403, detail="Unauthorized: User does not belong to your tenant context.")

    user_service.update_user_status(user_id=user_id, status=new_status)
    return RedirectResponse(url="/admin/users?message=Status+updated", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/delete")
async def delete_user_route(
    user_id: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """Delete a user record with tenant boundary enforcement."""
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    from core_platform.app.identity.service import get_user_identity_service
    user_service = get_user_identity_service()
    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    req_tenant = getattr(request.state, "tenant_id", None)
    user_tenant = ctx.tenant_id if ctx.tenant_id and ctx.tenant_id not in ("default_tenant", "system", "public") else None
    if req_tenant and req_tenant not in ("public", "default", "default_tenant"):
        active_tenant = req_tenant
    elif user_tenant:
        active_tenant = user_tenant
    else:
        active_tenant = req_tenant or "public"

    is_super = ctx.principal_id in ("devops_admin", "master_admin", "system") or "super_admin" in ctx.user_roles or "devops_admin" in ctx.user_roles

    if not is_super and user.tenant_id != active_tenant:
        raise HTTPException(status_code=403, detail="Unauthorized: User does not belong to your tenant context.")

    user_service.delete_user(user_id=user_id)
    return RedirectResponse(url="/admin/users?message=User+deleted", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users/{user_id}/magic-link", response_class=JSONResponse)
async def generate_user_magic_link(
    user_id: str,
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
) -> JSONResponse:
    """Generate ephemeral signed Magic Link URL with tenant boundary enforcement."""
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")

    from core_platform.app.identity.magic_link import build_magic_link_url
    from core_platform.app.identity.service import get_user_identity_service

    user_service = get_user_identity_service()
    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    req_tenant = getattr(request.state, "tenant_id", None)
    user_tenant = ctx.tenant_id if ctx.tenant_id and ctx.tenant_id not in ("default_tenant", "system", "public") else None
    if req_tenant and req_tenant not in ("public", "default", "default_tenant"):
        active_tenant = req_tenant
    elif user_tenant:
        active_tenant = user_tenant
    else:
        active_tenant = req_tenant or "public"

    is_super = ctx.principal_id in ("devops_admin", "master_admin", "system") or "super_admin" in ctx.user_roles or "devops_admin" in ctx.user_roles

    if not is_super and user.tenant_id != active_tenant:
        raise HTTPException(status_code=403, detail="Unauthorized: User does not belong to your tenant context.")

    base_url = (
        settings.ORCHESTRATOR_BASE_URL
        if settings.ORCHESTRATOR_BASE_URL
        else str(request.base_url).rstrip("/")
    )
    link = build_magic_link_url(
        user_id=str(user.id),
        phone_number=user.phone_number,
        tenant_id=user.tenant_id,
        base_url=base_url,
    )
    return JSONResponse(
        content={
            "magic_link": link,
            "user_id": str(user.id),
            "phone_number": user.phone_number,
            "tenant_id": user.tenant_id,
            "expires_in_minutes": settings.MAGIC_LINK_EXPIRY_MINUTES,
        }
    )


# ── Tenant Provisioning ───────────────────────────────────────────────────────

@router.get("/tenants", response_class=HTMLResponse)
async def view_tenants(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> HTMLResponse:
    """Display scoped company profile and plan settings for Customer Admin."""
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")

    from sqlalchemy import func, select
    from core_platform.app.db.manager import get_db_manager
    from core_platform.app.identity.models import PlatformUser, TenantConfig, TenantDomain
    from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info

    # Determine active tenant
    eff_tenant, tenant_name, active_tenant = resolve_effective_tenant_info(request, ctx)
    active_tenant_slug = eff_tenant

    is_devops = (
        ctx.principal_id in ("devops_admin", "master_admin", "system", "admin")
        or "super_admin" in ctx.user_roles
        or "devops_admin" in ctx.user_roles
    )

    db_mgr = get_db_manager()
    with db_mgr.get_session() as session:
        config = session.scalar(select(TenantConfig).where(TenantConfig.tenant_id == active_tenant_slug))
        custom_domains = list(session.scalars(select(TenantDomain).where(TenantDomain.tenant_id == active_tenant_slug)).all())
        total_users = session.scalar(
            select(func.count(PlatformUser.id)).where(PlatformUser.tenant_id == active_tenant_slug)
        ) or 0

    nav_apps = _build_nav_apps(ctx, active_tenant)
    csrf_token = request.cookies.get("csrf_token") or generate_csrf_token()

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=[a["id"] for a in nav_apps],
        tenant_name=str(tenant_name),
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.platform_dashboard", path="/admin/"),
            Breadcrumb(label_key="core.nav.tenants"),
        ],
    )

    has_platform_gemini = bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip())
    has_platform_whatsapp = bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_ACCESS_TOKEN.strip())
    has_byok_gemini = bool(config and config.encrypted_gemini_key)
    has_byok_whatsapp = bool(config and config.encrypted_waba_token)

    return templates.TemplateResponse(
        request=request,
        name="tenants.html",
        context={
            "title": f"Company Profile & Settings — {tenant_name}",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "is_devops": is_devops,
            "nav_apps": nav_apps,
            "active_tenant": active_tenant,
            "tenant_id": active_tenant_slug,
            "tenant_name": tenant_name,
            "config": config,
            "custom_domains": custom_domains,
            "total_users": total_users,
            "has_platform_gemini": has_platform_gemini,
            "has_platform_whatsapp": has_platform_whatsapp,
            "has_byok_gemini": has_byok_gemini,
            "has_byok_whatsapp": has_byok_whatsapp,
            "section": "tenants",
            "csrf_token": csrf_token,
            "message": message,
            "error": error,
            "organization": tenant_name,
            "ui": ui_ctx,
        },
    )


@router.post("/tenants/save-byok")
async def save_customer_byok_keys(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    gemini_api_key: Optional[str] = Form(None),
    waba_token: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """Save customer-provided BYOK keys securely into AES-256-GCM vault."""
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    from ops_control_plane.devops_vault import DevOpsKeyVault
    req_tenant = getattr(request.state, "tenant_id", None)
    user_tenant = ctx.tenant_id if ctx.tenant_id and ctx.tenant_id not in ("default_tenant", "system", "public") else None
    active_tenant_slug = req_tenant or user_tenant or "public"

    vault = DevOpsKeyVault()
    try:
        vault.configure_tenant_credentials(
            tenant_id=active_tenant_slug,
            credential_mode="CUSTOMER_BYOK",
            gemini_api_key=gemini_api_key.strip() if gemini_api_key else None,
            waba_access_token=waba_token.strip() if waba_token else None,
        )
        return RedirectResponse(
            url="/admin/tenants?message=Company+BYOK+credentials+updated+securely",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("[AdminShell] Failed to save BYOK keys: %s", exc)
        return RedirectResponse(
            url=f"/admin/tenants?error={exc}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/tenants/provision")
async def provision_tenant_route(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
    tenant_id: str = Form(...),
    db_dialect: str = Form("sqlite"),
    cartridge_mail: Optional[str] = Form(None),
    cartridge_temp: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None),
) -> Any:
    """Provision a new tenant database (DevOps Super-Admin only)."""
    if not is_devops_context(ctx):
        raise HTTPException(
            status_code=403,
            detail="DevOps Super-Admin privileges required to provision new tenant databases.",
        )
    if not verify_csrf_token(request, submitted_token=csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")

    from core_platform.app.db.tenant_provisioner import provision_tenant

    cartridges: List[str] = []
    if cartridge_mail:
        cartridges.append(cartridge_mail)
    if cartridge_temp:
        cartridges.append(cartridge_temp)

    try:
        provision_tenant(tenant_id=tenant_id, db_dialect=db_dialect, cartridges=cartridges)
        return RedirectResponse(url="/admin/tenants?message=Tenant+provisioned+successfully", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        logger.error("[AdminShell] Failed to provision tenant %s: %s", tenant_id, exc)
        return RedirectResponse(url=f"/admin/tenants?error={exc}", status_code=status.HTTP_303_SEE_OTHER)



# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_nav_apps(ctx: SecurityContext, tenant: Optional[Any] = None) -> List[Dict[str, str]]:
    """Build the sidebar navigation app links for the shell template dynamically.

    Args:
        ctx: Authenticated SecurityContext.
        tenant: Optional active Tenant entity to filter tenant-entitled cartridges.

    Returns:
        List of nav app dicts with 'id', 'label', 'description', and 'url'.
    """
    try:
        from core_platform.main import plugin_loader
        all_apps = plugin_loader.get_all_applications()
    except Exception:
        all_apps = {}

    enabled = set(settings.ENABLED_APPLICATIONS) if settings.ENABLED_APPLICATIONS is not None else set(all_apps.keys())
    if tenant and hasattr(tenant, "allowed_cartridges") and tenant.allowed_cartridges is not None:
        enabled = enabled.intersection(set(tenant.allowed_cartridges))

    # If principal is scoped to a customer tenant and tenant entity wasn't passed directly, resolve from DB
    if not tenant and ctx.tenant_id and ctx.tenant_id not in ("default_tenant", "system", "public", "platform"):
        try:
            from sqlalchemy import select
            from core_platform.app.db.manager import get_db_manager
            from core_platform.app.identity.models import Tenant
            db_mgr = get_db_manager()
            with db_mgr.get_session() as session:
                t_obj = session.scalar(select(Tenant).where(Tenant.id == ctx.tenant_id))
                if t_obj and t_obj.allowed_cartridges is not None:
                    enabled = enabled.intersection(set(t_obj.allowed_cartridges))
        except Exception:
            pass

    permitted = set(ctx.permitted_apps) if ctx.permitted_apps else enabled
    if "*" not in permitted and "all" not in permitted:
        permitted = permitted.intersection(enabled)
    else:
        permitted = enabled

    nav_apps = []
    for app_id, app_inst in all_apps.items():
        if app_id in permitted:
            nav_apps.append({
                "id": app_id,
                "label": getattr(app_inst, "name", app_id),
                "description": getattr(app_inst, "description", "Active domain cartridge."),
                "url": getattr(app_inst, "dashboard_url", "") or f"/admin/apps/{app_id.replace('_', '-')}/",
            })
    return nav_apps


# ── Live Logs & Observability ─────────────────────────────────────────────────

@router.get("/logs", response_class=HTMLResponse)
async def view_logs(
    request: Request,
    ctx: SecurityContext = Depends(require_devops),
) -> HTMLResponse:
    """Render the live log observability console."""
    nav_apps = _build_nav_apps(ctx)
    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=[a["id"] for a in nav_apps],
        tenant_name=settings.ORGANIZATION_NAME or "",
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.platform_dashboard", path="/admin/"),
            Breadcrumb(label_key="core.nav.logs"),
        ],
    )
    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            "title": "Live System Logs",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "nav_apps": nav_apps,
            "organization": settings.ORGANIZATION_NAME,
            "kiosk_id": settings.KIOSK_ID,
            "section": "logs",
            "ui": ui_ctx,
        },
    )


@router.get("/api/logs/tail", response_class=JSONResponse)
async def tail_logs(
    request: Request,
    lines: int = 250,
    ctx: SecurityContext = Depends(require_devops),
) -> JSONResponse:
    """Return the last N lines from logs/platform.log."""
    log_path = Path("logs") / "platform.log"
    if not log_path.exists():
        return JSONResponse(content={"lines": ["No logs recorded yet."]})

    try:
        max_lines = min(max(lines, 10), 2000)
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            tail_slice = [line.rstrip("\r\n") for line in all_lines[-max_lines:]]
        return JSONResponse(content={"lines": tail_slice})
    except Exception as exc:
        return JSONResponse(content={"lines": [f"Error reading log file: {exc}"]})


@router.get("/api/logs/download")
async def download_logs(
    format: str = "log",
    ctx: SecurityContext = Depends(require_devops),
) -> Response:
    """Download the complete platform log file (.log or .jsonl)."""
    filename = "platform.jsonl" if format == "jsonl" else "platform.log"
    target_path = Path("logs") / filename
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found.")

    media_type = "application/x-ndjson" if format == "jsonl" else "text/plain"
    return FileResponse(
        path=str(target_path),
        filename=filename,
        media_type=media_type,
    )


# ── LLM Cost & Telemetry Dashboard ──────────────────────────────────────────

@router.get("/llm-costs", response_class=HTMLResponse)
async def llm_costs_page(
    request: Request,
    ctx: SecurityContext = Depends(require_devops),
) -> HTMLResponse:
    """Render the LLM Token Consumption and Cost Monitoring console."""
    from core_platform.app.llm.cost_tracker import get_llm_cost_tracker
    tracker = get_llm_cost_tracker()
    summary = tracker.get_summary()
    operations = tracker.get_operations_report(limit=100)

    # Determine nav_apps for the sidebar
    nav_apps = _build_nav_apps(ctx)
    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=[a["id"] for a in nav_apps],
        tenant_name=settings.ORGANIZATION_NAME or "",
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.platform_dashboard", path="/admin/"),
            Breadcrumb(label_key="core.nav.llm_costs"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="llm_costs.html",
        context={
            "title": "LLM Token & Cost Consumption",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "nav_apps": nav_apps,
            "organization": settings.ORGANIZATION_NAME,
            "kiosk_id": settings.KIOSK_ID,
            "section": "llm_costs",
            "summary": summary,
            "operations": operations,
            "ui": ui_ctx,
        },
    )


@router.get("/api/llm-costs", response_class=JSONResponse)
async def get_llm_costs_api(
    ctx: SecurityContext = Depends(require_devops),
) -> JSONResponse:
    """Return JSON payload of aggregated LLM costs and operations breakdown."""
    from core_platform.app.llm.cost_tracker import get_llm_cost_tracker
    tracker = get_llm_cost_tracker()
    return JSONResponse(
        content={
            "summary": tracker.get_summary(),
            "operations": tracker.get_operations_report(limit=100),
        }
    )


# ── Live WebSocket Fleet Telemetry Stream (Phase 4) ──────────────────────────

class FleetEventBroadcaster:
    """Thread-safe WebSocket broadcaster for real-time admin shell telemetry."""

    _instance: Optional["FleetEventBroadcaster"] = None

    @classmethod
    def get_instance(cls) -> "FleetEventBroadcaster":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("[FleetEventBroadcaster] WebSocket connected (total: %d)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("[FleetEventBroadcaster] WebSocket disconnected (total: %d)", len(self.active_connections))

    async def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Broadcast an event payload to all connected admin clients."""
        msg = {"event": event_type, "data": payload}
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(msg)
            except Exception:
                disconnected.append(connection)
        for dead in disconnected:
            self.disconnect(dead)


def get_fleet_broadcaster() -> FleetEventBroadcaster:
    return FleetEventBroadcaster.get_instance()


@router.websocket("/ws/fleet-events")
async def fleet_events_websocket(websocket: WebSocket) -> None:
    """Live streaming WebSocket feed of station check-ins, temperature violations, and alerts."""
    broadcaster = get_fleet_broadcaster()
    await broadcaster.connect(websocket)
    try:
        while True:
            # Keep-alive heartbeat receiver
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception as exc:
        logger.debug("[FleetEventBroadcaster] WebSocket stream ended: %s", exc)
        broadcaster.disconnect(websocket)


