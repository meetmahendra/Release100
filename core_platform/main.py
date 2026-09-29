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
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time
from typing import Any, AsyncGenerator, Callable, Dict
import uuid
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from core_platform.app.apps_registry import ApplicationRegistry
from core_platform.app.config import settings
from core_platform.app.ingress.relay_client import CloudRelayClient
from core_platform.app.skills.registry import SkillRegistry
from core_platform.app.telemetry.audit_engine import AuditEngine


from core_platform.app.telemetry.logging_config import (
    bind_log_context,
    clear_log_context,
    setup_platform_logging,
)

setup_platform_logging()

logger = logging.getLogger("core_platform.host")
_BOOT_TIME = time.time()
relay_client = CloudRelayClient.get_instance()


async def _outbox_sync_worker(stop_event: asyncio.Event) -> None:
    """Resilient background worker periodically draining offline outbox records to downstream."""
    while not stop_event.is_set():
        if "temperature_marker" in settings.ENABLED_APPLICATIONS:
            try:
                from apps.temperature_marker.database.db_service import DatabaseService
                from apps.temperature_marker.downstream.in_house_rest import InHouseRESTConnector
                from apps.temperature_marker.downstream.outbox_manager import OutboxManager

                db_service = DatabaseService.get_instance()
                connector = InHouseRESTConnector(endpoint_url=settings.DOWNSTREAM_REST_URL)
                manager = OutboxManager(db_service=db_service, connector=connector)
                synced, failed = await manager.sync_pending_outbox(max_batch=20)
                if synced > 0:
                    logger.info("[OutboxSync] Drained %d pending attendance telemetry records.", synced)
            except Exception as exc:
                logger.debug("[OutboxSync] Periodic drain cycle error: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(settings.OUTBOX_DRAIN_INTERVAL_SECONDS))
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and graceful shutdown."""
    print(f"[Release100] Booting Platform Host on port {settings.ORCHESTRATOR_PORT}...")
    relay_client.start()
    outbox_stop = asyncio.Event()
    outbox_task = asyncio.create_task(_outbox_sync_worker(outbox_stop))
    yield
    print("[Release100] Shutting down Platform Host cleanly.")
    outbox_stop.set()
    try:
        await asyncio.wait_for(outbox_task, timeout=2.0)
    except Exception:
        pass
    await relay_client.stop()


app = FastAPI(
    title="Release100 Core Platform",
    version="1.3.0",
    lifespan=lifespan,
)

# Mount media and biometric photo storage vaults for browser monitoring inspection
_media_vault = Path("logs/media")
_media_vault.mkdir(parents=True, exist_ok=True)
app.mount("/logs/media", StaticFiles(directory=str(_media_vault)), name="logs_media")

_photos_vault = Path("logs/photos")
_photos_vault.mkdir(parents=True, exist_ok=True)
app.mount("/logs/photos", StaticFiles(directory=str(_photos_vault)), name="logs_photos")



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


@app.get("/health", response_class=JSONResponse)
async def health_check() -> Dict[str, Any]:
    """Comprehensive health heartbeat API for Process Supervisor and Tray App."""
    uptime_sec = round(time.time() - _BOOT_TIME, 2)
    audit_engine = AuditEngine.get_instance()
    skill_statuses = SkillRegistry.get_instance().get_all_health_statuses()

    pending_outbox = 0
    if "temperature_marker" in settings.ENABLED_APPLICATIONS:
        try:
            from apps.temperature_marker.database.db_service import DatabaseService
            pending_outbox = len(DatabaseService.get_instance().get_pending_outbox_items(limit=100))
        except Exception:
            pass

    return {
        "status": "healthy",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": uptime_sec,
        "tenant_id": settings.TENANT_ID,
        "kiosk_id": settings.KIOSK_ID,
        "organization_name": settings.ORGANIZATION_NAME,
        "station_name": settings.STATION_NAME,
        "enabled_apps": settings.ENABLED_APPLICATIONS,
        "applications": ApplicationRegistry.get_instance().get_summary(),
        "cloud_relay": {
            "enabled": bool(settings.RELAY_WS_URL),
            "relay_url": relay_client.relay_url if settings.RELAY_WS_URL else None,
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


# Mount enabled application UI routers
if "temperature_marker" in settings.ENABLED_APPLICATIONS:
    from apps.temperature_marker.ui.routes import router as tm_router, view_verify_location, verify_location_api

    app.include_router(tm_router)
    app.get("/loc", response_class=HTMLResponse)(view_verify_location)
    app.post("/api/verify-location")(verify_location_api)

if "mail_organizer" in settings.ENABLED_APPLICATIONS:
    try:
        from apps.mail_organizer.ui.routes import router as mail_router

        app.include_router(mail_router)

        @app.get("/mail", response_class=RedirectResponse)
        @app.get("/mail/", response_class=RedirectResponse)
        async def mail_redirect() -> RedirectResponse:
            """Redirect shortcut /mail to mail organizer dashboard."""
            return RedirectResponse(url="/admin/apps/mail-organizer/dashboard")
    except ModuleNotFoundError:
        pass

# Mount Live Diagnostics & Settings Web Console
from core_platform.app.diagnostics.web_dashboard import router as diag_router
app.include_router(diag_router)


@app.get("/admin/settings", response_class=RedirectResponse)
async def admin_settings_redirect() -> RedirectResponse:
    """Redirect shortcut /admin/settings to diagnostics and configuration console."""
    return RedirectResponse(url="/settings")

# Mount WhatsApp Cloud API Ingress Webhook
from core_platform.app.ingress.whatsapp_router import router as wa_router
app.include_router(wa_router)

# Mount MCP Server Host (port-multiplexed on same app, /mcp/ prefix)
from core_platform.app.mcp_server.server import router as mcp_router
from core_platform.app.mcp_server.tool_aggregator import register_app_tools

app.include_router(mcp_router)

# Register MCP tools from enabled cartridges
if "temperature_marker" in settings.ENABLED_APPLICATIONS:
    try:
        from apps.temperature_marker.downstream.mcp_tools import get_temperature_marker_mcp_tools
        from apps.temperature_marker.database.db_service import DatabaseService as _TMDB
        from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService as _TMKG
        register_app_tools(get_temperature_marker_mcp_tools(_TMDB.get_instance(), _TMKG()))
    except Exception as _exc:
        logger.warning("[MCP] Failed to register temperature_marker tools: %s", _exc)

if "mail_organizer" in settings.ENABLED_APPLICATIONS:
    try:
        from apps.mail_organizer.mcp.tools import get_mail_organizer_mcp_tools
        register_app_tools(get_mail_organizer_mcp_tools())
    except Exception as _exc:
        logger.warning("[MCP] Failed to register mail_organizer tools: %s", _exc)

# Mount Central Admin Shell (login, logout, dashboard, API key management)
from core_platform.app.admin_shell.routes import router as admin_router
app.include_router(admin_router)

# Register semantic router app descriptors
from core_platform.app.routing.semantic_router import register_app_descriptor
if "temperature_marker" in settings.ENABLED_APPLICATIONS:
    register_app_descriptor(
        "temperature_marker",
        "Factory floor attendance and chiller temperature recording via selfie photo and OCR.",
    )
if "mail_organizer" in settings.ENABLED_APPLICATIONS:
    register_app_descriptor(
        "mail_organizer",
        "Email triage, meeting scheduling, and PM task extraction for executives.",
    )


@app.get("/", response_class=RedirectResponse)
async def root_redirect() -> RedirectResponse:
    """Redirect platform root to default active application dashboard."""
    return RedirectResponse(url="/admin/apps/temperature-marker/fleet")
