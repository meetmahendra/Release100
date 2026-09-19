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

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core_platform.app.auth.api_keys import get_api_key_manager
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.auth.strategies import AuthResolver
from core_platform.app.config import settings
from core_platform.app.llm.gateway import get_platform_llm_gateway
from core_platform.app.rbac.permissions import get_web_security_context

logger = logging.getLogger("core_platform.admin_shell")

router = APIRouter(prefix="/admin", tags=["Admin Shell"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ── Auth Routes ───────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render the login page.

    Args:
        request: FastAPI request.

    Returns:
        Rendered login.html template.
    """
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"title": "Admin Login", "error": None},
    )


@router.post("/login")
async def login_submit(
    response: Response,
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Any:
    """Process login form, set JWT cookie, redirect to dashboard.

    Args:
        response: FastAPI response (cookie will be set here).
        request: FastAPI request.
        username: Form field.
        password: Form field.

    Returns:
        Redirect to /admin/ on success, re-rendered login page on failure.
    """
    ctx = AuthResolver.resolve_credentials(username, password)
    if not ctx:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"title": "Admin Login", "error": "Invalid credentials."},
            status_code=401,
        )

    token = create_jwt_token(
        principal_id=ctx.principal_id,
        roles=ctx.user_roles,
        permitted_apps=ctx.permitted_apps,
        tenant_id=ctx.tenant_id,
    )
    redirect = RedirectResponse(url="/admin/", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=8 * 3600,
    )
    logger.info("[AdminShell] Login success: principal=%s", ctx.principal_id)
    return redirect


@router.get("/logout")
async def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to login.

    Returns:
        Redirect to /admin/login with cookie cleared.
    """
    redirect = RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie("admin_token")
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

    nav_apps = _build_nav_apps(ctx)

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

    return templates.TemplateResponse(
        request=request,
        name="shell.html",
        context={
            "title": "Platform Admin",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "nav_apps": nav_apps,
            "enabled_applications": settings.ENABLED_APPLICATIONS,
            "dry_run": settings.DRY_RUN,
            "execution_mode": settings.EXECUTION_MODE,
            "organization": settings.ORGANIZATION_NAME,
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

    manager = get_api_key_manager()
    keys = manager.list_keys()
    nav_apps = _build_nav_apps(ctx)

    return templates.TemplateResponse(
        request=request,
        name="shell.html",
        context={
            "title": "API Keys",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "nav_apps": nav_apps,
            "api_keys": keys,
            "section": "api_keys",
            "organization": settings.ORGANIZATION_NAME,
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

    manager = get_api_key_manager()
    raw_key, key_hash = manager.create_key(
        label=label,
        principal_id=ctx.principal_id,
        roles=roles,
        permitted_apps=permitted_apps or list(settings.ENABLED_APPLICATIONS),
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_nav_apps(ctx: SecurityContext) -> List[Dict[str, str]]:
    """Build the sidebar navigation app links for the shell template.

    Args:
        ctx: Authenticated SecurityContext.

    Returns:
        List of nav app dicts with 'id', 'label', and 'url'.
    """
    _APP_NAV: Dict[str, Dict[str, str]] = {
        "temperature_marker": {
            "label": "🌡️ Temperature Marker",
            "url": "/admin/apps/temperature-marker/",
        },
        "mail_organizer": {
            "label": "📧 Mail Organizer",
            "url": "/admin/apps/mail-organizer/",
        },
    }

    enabled = set(settings.ENABLED_APPLICATIONS)
    permitted = set(ctx.permitted_apps) if ctx.permitted_apps else enabled

    nav_apps = []
    for app_id, nav in _APP_NAV.items():
        if app_id in enabled and app_id in permitted:
            nav_apps.append({"id": app_id, **nav})
    return nav_apps


# ── Live Logs & Observability ─────────────────────────────────────────────────

@router.get("/logs", response_class=HTMLResponse)
async def view_logs(
    request: Request,
    ctx: SecurityContext = Depends(get_web_security_context),
) -> HTMLResponse:
    """Render the live log observability console."""
    nav_apps = _build_nav_apps(ctx)
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
        },
    )


@router.get("/api/logs/tail", response_class=JSONResponse)
async def tail_logs(
    request: Request,
    lines: int = 250,
    ctx: SecurityContext = Depends(get_web_security_context),
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
    ctx: SecurityContext = Depends(get_web_security_context),
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
    ctx: SecurityContext = Depends(get_web_security_context),
) -> HTMLResponse:
    """Render the LLM Token Consumption and Cost Monitoring console."""
    from core_platform.app.llm.cost_tracker import get_llm_cost_tracker
    tracker = get_llm_cost_tracker()
    summary = tracker.get_summary()
    operations = tracker.get_operations_report(limit=100)

    # Determine nav_apps for the sidebar
    nav_apps = _build_nav_apps(ctx)

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
        },
    )


@router.get("/api/llm-costs", response_class=JSONResponse)
async def get_llm_costs_api(
    ctx: SecurityContext = Depends(get_web_security_context),
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


