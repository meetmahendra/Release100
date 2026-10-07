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
Core Platform Bootstrap & Health Telemetry Gateway.

Adheres strictly to Plan 02 v1.3 (< 70 lines).
Exposes the /health heartbeat endpoint polled by Process Supervisor and Tray App.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any, AsyncGenerator, Callable, Dict
import uuid
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from core_platform.app.auth.models import SecurityContext
from core_platform.app.rbac.permissions import get_web_security_context

from core_platform.app.apps_registry import ApplicationRegistry
from core_platform.app.config import settings
from core_platform.app.ingress.relay_client import CloudRelayClient
from core_platform.app.skills.registry import SkillRegistry
from core_platform.app.telemetry.audit_engine import AuditEngine
from core_platform.app.telemetry.metrics import metrics_registry
from core_platform.app.telemetry.otel_tracer import tracer



from core_platform.app.telemetry.logging_config import (
    bind_log_context,
    clear_log_context,
    setup_platform_logging,
)

setup_platform_logging()

logger = logging.getLogger("core_platform.host")
_BOOT_TIME = time.time()
relay_client = CloudRelayClient.get_instance()

from core_platform.app.plugin_engine.loader import PluginLoader
from core_platform.app.outbox.synchronizer import OutboxSynchronizer
from core_platform.app.i18n.negotiation import LocaleMiddleware
from core_platform.app.middleware.tenant_context import TenantContextMiddleware

plugin_loader = PluginLoader(enabled_apps=settings.ENABLED_APPLICATIONS)
_platform_synchronizer = OutboxSynchronizer(drain_interval_seconds=float(settings.OUTBOX_DRAIN_INTERVAL_SECONDS))



@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and graceful shutdown."""
    print(f"[Release100] Booting Platform Host on port {settings.ORCHESTRATOR_PORT}...")
    from core_platform.app.db.manager import get_db_manager
    db_mgr = get_db_manager()
    db_mgr.init_tables()

    relay_client.start()
    sync_task = asyncio.create_task(_platform_synchronizer.run())
    yield
    print("[Release100] Shutting down Platform Host cleanly.")
    _platform_synchronizer.stop()
    try:
        await asyncio.wait_for(sync_task, timeout=2.0)
    except Exception:
        pass
    await relay_client.stop()
    plugin_loader.shutdown_all()
    # Cleanly dispose all primary and custom database connection pools
    db_mgr.shutdown()


app = FastAPI(
    title="Release100 Core Platform",
    version="1.3.0",
    lifespan=lifespan,
)

# Multi-Tenancy Dynamic Context Middleware (GEES v2.0 / Plan 09)
app.add_middleware(TenantContextMiddleware, default_tenant=settings.TENANT_ID)

# UI locale negotiation (Plan 11): query > cookie > Accept-Language > default
app.add_middleware(
    LocaleMiddleware,
    supported=settings.UI_SUPPORTED_LOCALES,
    default=settings.UI_DEFAULT_LOCALE,
    cookie_name=settings.UI_LOCALE_COOKIE_NAME,
)


# Mount media and biometric photo storage vaults for browser monitoring inspection
_media_vault = Path("logs/media")
_media_vault.mkdir(parents=True, exist_ok=True)
app.mount("/logs/media", StaticFiles(directory=str(_media_vault)), name="logs_media")

_photos_vault = Path("logs/photos")
_photos_vault.mkdir(parents=True, exist_ok=True)
app.mount("/logs/photos", StaticFiles(directory=str(_photos_vault)), name="logs_photos")



@app.middleware("http")
async def security_headers_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    """Inject standard HTTP security defense headers (SEC-6)."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=()"
    return response


@app.middleware("http")
async def distributed_tracing_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    """Propagate and record W3C traceparent headers across all inbound HTTP requests."""
    traceparent = request.headers.get("traceparent")
    endpoint_name = f"{request.method} {request.url.path}"
    async with tracer.async_trace_span(endpoint_name, parent_traceparent=traceparent) as span:
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", str(request.url))
        span.set_attribute("http.client_ip", request.client.host if request.client else "unknown")
        response: Response = await call_next(request)
        span.set_attribute("http.status_code", response.status_code)
        response.headers["traceparent"] = span.traceparent
        return response


@app.middleware("http")
async def correlation_context_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    """Inject and propagate correlation_id across all request logging."""
    corr_id = request.headers.get("X-Correlation-ID") or f"req-{uuid.uuid4().hex[:8]}"
    bind_log_context(correlation_id=corr_id)
    try:
        response: Response = await call_next(request)
        response.headers["X-Correlation-ID"] = corr_id
        return response
    finally:
        clear_log_context()


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> PlainTextResponse:
    """Prometheus text exposition format endpoint for scraping operational metrics."""
    return PlainTextResponse(
        content=metrics_registry.format_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/health", response_class=JSONResponse)
async def health_check() -> Dict[str, Any]:

    """Operational health heartbeat API for Process Supervisor and external probes."""
    uptime_sec = round(time.time() - _BOOT_TIME, 2)
    audit_engine = AuditEngine.get_instance()
    skill_statuses = SkillRegistry.get_instance().get_all_health_statuses()

    # Aggregate pending outbox count from all loaded cartridges — no app-specific imports.
    pending_outbox = sum(
        app_inst.get_pending_outbox_count()
        for app_inst in plugin_loader.get_all_applications().values()
    )

    return {
        "status": "healthy",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": uptime_sec,
        "version": "1.3.0",
        "execution_mode": settings.EXECUTION_MODE,
        "tenant_id": settings.TENANT_ID,
        "kiosk_id": settings.KIOSK_ID,
        "organization_name": settings.ORGANIZATION_NAME,
        "station_name": settings.STATION_NAME,
        "enabled_apps": settings.ENABLED_APPLICATIONS,
        "applications": ApplicationRegistry.get_instance().get_summary(),
        "cloud_relay": {
            "enabled": bool(settings.RELAY_WS_URL),
            "connected": relay_client.is_connected,
            "messages_received": relay_client.messages_received,
            "connection_attempts": relay_client.connection_attempts,
            "last_connected_at": relay_client.last_connected_at.isoformat() if relay_client.last_connected_at else None,
        },
        "skills": skill_statuses,
        "outbox_pending_records": pending_outbox,
        "audit_engine": {
            "last_sequence_number": audit_engine._sequence_counter,
            "last_record_hash": audit_engine._last_hash,
            "active_records_count": len(audit_engine._active_records),
        },
    }


@app.get("/admin/api/health-metrics", response_class=JSONResponse)
async def admin_health_metrics(
    ctx: SecurityContext = Depends(get_web_security_context),
) -> Dict[str, Any]:
    """Detailed administrative diagnostic telemetry (SEC-5)."""
    base = await health_check()
    base["cloud_relay"]["relay_url"] = relay_client.relay_url if settings.RELAY_WS_URL else None
    return base


# ── Dynamic Application Cartridge Discovery & Mounting via PluginLoader ──
from core_platform.app.routing.semantic_router import register_app_descriptor

loaded_apps = plugin_loader.load_all()
plugin_loader.mount_all(app)

# -- Decentralized Entitlement Architecture (Plan 10): registry, repository, gate --
# Failures here must never block boot; with no gate installed everything behaves as mode "off".
try:
    from core_platform.app.admin_shell.entitlements_routes import emit_startup_audits
    from core_platform.app.entitlements import dependencies as _ent_deps
    from core_platform.app.entitlements.audit import EntitlementAuditor as _EntAuditor
    from core_platform.app.entitlements.evaluator import EntitlementEvaluator as _EntEvaluator
    from core_platform.app.entitlements.gate import EntitlementGate as _EntGate

    _ent_registry = _ent_deps.get_registry()
    plugin_loader.register_entitlements(_ent_registry)
    _ent_repo = _ent_deps.get_repository()
    _ent_auditor = _EntAuditor()
    _ent_deps.set_gate(
        _EntGate(
            _EntEvaluator(_ent_repo, _ent_registry),
            _ent_repo,
            _ent_auditor,
            _ent_registry,
            lambda: settings.ENTITLEMENT_ENFORCEMENT_MODE,
        )
    )
    emit_startup_audits(_ent_registry, _ent_repo, _ent_auditor)
except Exception as _ent_exc:  # noqa: BLE001
    logger.error("[Main] Entitlement subsystem failed to initialise (mode off): %s", _ent_exc)
# Register semantic descriptors dynamically from loaded cartridges
for app_id, app_instance in loaded_apps.items():
    desc = getattr(app_instance, "description", "") or app_instance.name
    register_app_descriptor(app_id, desc)

# Mount application-declared convenience shortcut routes at the platform root.
# Each cartridge advertises its own shortcuts via get_convenience_routes() —
# no hardcoded app IDs or route paths in this file.
_METHOD_DECORATOR_MAP = {
    "GET": app.get,
    "POST": app.post,
    "PUT": app.put,
    "DELETE": app.delete,
}
for _app_instance in loaded_apps.values():
    for _method, _path, _handler in _app_instance.get_convenience_routes():
        _decorator = _METHOD_DECORATOR_MAP.get(_method.upper())
        if _decorator is not None:
            _decorator(_path)(_handler)
        else:
            logger.warning("[Main] Unknown HTTP method '%s' in convenience route %s", _method, _path)

# Mount Live Diagnostics & Settings Web Console
from core_platform.app.diagnostics.web_dashboard import router as diag_router
app.include_router(diag_router)


@app.get("/admin/settings", response_class=RedirectResponse)
async def admin_settings_redirect() -> RedirectResponse:
    """Redirect shortcut /admin/settings to diagnostics and configuration console."""
    return RedirectResponse(url="/settings")


@app.get("/ui-gallery", response_class=HTMLResponse)
async def ui_gallery_preview() -> HTMLResponse:
    """Interactive visual screenshot catalog and design system preview for mobile and desktop."""
    art_path = Path(r"C:\Users\depali Gurav\.gemini\antigravity\brain\5dcee49a-51c8-4a1f-aa91-489aba7c34ba\ui_design_system_preview.html")
    if art_path.exists():
        return HTMLResponse(content=art_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>UI Gallery not found</h1>", status_code=404)

# Mount WhatsApp Cloud API Ingress Webhook
from core_platform.app.ingress.whatsapp_router import router as wa_router
app.include_router(wa_router)

# Mount Google OAuth Magic Link Public Ingress Gateway
from core_platform.app.ingress.oauth_router import router as oauth_router
app.include_router(oauth_router)


# Mount MCP Server Host (port-multiplexed on same app, /mcp/ prefix)
from core_platform.app.mcp_server.server import router as mcp_router
from core_platform.app.mcp_server.tool_aggregator import register_app_tools

app.include_router(mcp_router)

# Register MCP tools dynamically from loaded cartridges via PluginLoader
mcp_tools = plugin_loader.get_all_mcp_tools()
if mcp_tools:
    register_app_tools(mcp_tools)

# Mount Central Admin Shell (login, logout, dashboard, API key management)
from core_platform.app.admin_shell.routes import router as admin_router
app.include_router(admin_router)
from core_platform.app.admin_shell.entitlements_routes import router as entitlements_router
app.include_router(entitlements_router)

# Mount Edge-to-Cloud State Sync Router (Plan 09 / Phase 4)
from core_platform.app.ingress.sync_router import sync_router
app.include_router(sync_router)

# Mount DevOps Super-Admin Control Plane
try:
    from ops_control_plane.super_admin.routes import router as ops_router
    app.include_router(ops_router)
    
    # Aliases for super-admin / devops routes
    @app.get("/super-admin/tenants", response_class=RedirectResponse, include_in_schema=False)
    @app.get("/super-admin", response_class=RedirectResponse, include_in_schema=False)
    @app.get("/devops/tenants", response_class=RedirectResponse, include_in_schema=False)
    @app.get("/devops", response_class=RedirectResponse, include_in_schema=False)
    async def super_admin_tenants_alias() -> RedirectResponse:
        return RedirectResponse(url="/ops/tenants", status_code=302)

    @app.get("/super-admin/audit", response_class=RedirectResponse, include_in_schema=False)
    @app.get("/devops/audit", response_class=RedirectResponse, include_in_schema=False)
    async def super_admin_audit_alias() -> RedirectResponse:
        return RedirectResponse(url="/ops/audit", status_code=302)
except ImportError:
    pass



@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Lightweight 204 No Content for browser favicon requests."""
    return Response(status_code=204)


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Handle HTTPExceptions gracefully: redirect unauthenticated browser requests to /admin/login."""
    if exc.status_code in (401, 403):
        accept = request.headers.get("accept", "")
        is_browser_page = "text/html" in accept or request.headers.get("sec-fetch-dest") == "document"
        if is_browser_page and not request.url.path.startswith("/admin/login"):
            redirect = RedirectResponse(url="/admin/login", status_code=302)
            if exc.status_code == 401:
                redirect.delete_cookie("admin_token")
            return redirect
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.get("/", response_class=RedirectResponse)
async def root_redirect(request: Request) -> RedirectResponse:
    """Redirect platform root dynamically to DevOps control plane or customer workspace."""
    token = request.cookies.get("admin_token")
    if not token:
        return RedirectResponse(url="/admin/login", status_code=302)

    host = request.headers.get("host", "").split(":")[0].strip().lower()
    req_tenant = getattr(request.state, "tenant_id", "public")
    is_customer_domain = False
    if "." in host and not host.replace(".", "").isdigit() and "localhost" not in host:
        parts = host.split(".")
        if len(parts) >= 3 and parts[0] not in ("www", "api", "app", "public", "ops", "ops-admin", "admin"):
            is_customer_domain = True
    if req_tenant not in ("public", "default", "default_tenant", "platform", "system", "ops"):
        is_customer_domain = True

    from core_platform.app.auth.jwt_utils import verify_jwt_token
    ctx = verify_jwt_token(token)
    if ctx and not is_customer_domain and (
        ctx.principal_id in ("devops_admin", "master_admin", "system")
        or (ctx.principal_id == "admin" and ctx.tenant_id in ("default_tenant", "public", "system", None))
        or "super_admin" in ctx.user_roles
        or "devops_admin" in ctx.user_roles
    ):
        return RedirectResponse(url="/ops/tenants", status_code=302)

    return RedirectResponse(url="/admin/", status_code=302)


if __name__ == "__main__":
    import uvicorn
    port = int(settings.ORCHESTRATOR_PORT)
    print(f"[Release100] Starting web server on http://127.0.0.1:{port}")
    uvicorn.run("core_platform.main:app", host="127.0.0.1", port=port, reload=True)

