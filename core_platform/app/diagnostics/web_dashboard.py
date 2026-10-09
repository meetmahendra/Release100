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
Web Configuration, Live Testing & Diagnostics Controller (`web_dashboard.py`).

Adheres strictly to Plan 07 v1.0 and GEES v1.0.
Provides:
- GET  /settings                    -> Responsive, offline-safe management web console
- GET  /api/diagnostics/status      -> Real-time system health & active apps JSON
- POST /api/diagnostics/verify      -> Live ping for Gemini, WhatsApp, Relay, or Ports
- POST /api/diagnostics/save        -> Non-destructive .env save with pre-save backup
- POST /api/diagnostics/restore     -> 1-click rollback to historical configuration snapshot
- POST /api/diagnostics/poller/toggle -> Verified Mail Poller start/stop with clean tree termination
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from core_platform.app.apps_registry import ApplicationRegistry
from core_platform.app.auth.models import SecurityContext
from core_platform.app.config import settings
from core_platform.app.rbac.permissions import get_web_security_context, require_devops
from core_platform.app.diagnostics.config_backup import (
    list_backups,
    read_env_dict,
    reload_settings_from_env,
    restore_backup,
    save_master_config,
)
from core_platform.app.diagnostics.verifier import (
    get_full_status,
    send_test_whatsapp_message,
    verify_cloud_relay,
    verify_gemini,
    verify_hmac_secret,
    verify_ports,
    verify_typesafe,
    verify_webhook_ingress,
    verify_whatsapp,
)
from core_platform.app.ui.templating import build_templates
from core_platform.app.ui.ui_context import Breadcrumb, build_ui_context

logger = logging.getLogger("core_platform.diagnostics_web")
router = APIRouter(tags=["diagnostics"])

ADMIN_SHELL_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "admin_shell" / "templates"
templates = build_templates([ADMIN_SHELL_TEMPLATES_DIR])


class VerifyRequest(BaseModel):
    """Schema for individual credential test requests."""

    service: str
    key: Optional[str] = None
    token: Optional[str] = None
    phone_id: Optional[str] = None
    relay_url: Optional[str] = None
    verify_token: Optional[str] = None
    app_secret: Optional[str] = None
    recipient_phone: Optional[str] = None
    message: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class SaveConfigRequest(BaseModel):
    """Schema for updating platform configuration parameters."""

    settings: Dict[str, str]


class RestoreRequest(BaseModel):
    """Schema for rolling back to a backup file."""

    filename: str


@router.get("/api/diagnostics/status", response_class=JSONResponse)
async def api_diagnostics_status(
    ctx: SecurityContext = Depends(require_devops),
) -> Dict[str, Any]:
    """Return real-time verification and system health status."""
    return get_full_status()


@router.post("/api/diagnostics/verify", response_class=JSONResponse)
async def api_diagnostics_verify(
    req: VerifyRequest,
    ctx: SecurityContext = Depends(require_devops),
) -> Dict[str, Any]:
    """Test a single credential or service endpoint without modifying disk."""
    svc = req.service.lower().strip()

    if svc in ("typesafe", "jev"):
        return verify_typesafe(api_key=req.key, base_url=req.base_url, model=req.model)
    elif svc == "gemini":
        return verify_gemini(api_key=req.key)
    elif svc == "whatsapp":
        return verify_whatsapp(access_token=req.token, phone_number_id=req.phone_id)
    elif svc == "cloud_relay":
        return verify_cloud_relay(relay_url=req.relay_url)
    elif svc == "webhook":
        return verify_webhook_ingress(verify_token=req.verify_token)
    elif svc == "hmac":
        return verify_hmac_secret(app_secret=req.app_secret)
    elif svc == "ports":
        return verify_ports()
    elif svc == "whatsapp_send":
        if not req.recipient_phone:
            raise HTTPException(status_code=400, detail="recipient_phone is required")
        return send_test_whatsapp_message(
            recipient_phone=req.recipient_phone,
            message=req.message,
            access_token=req.token,
            phone_number_id=req.phone_id,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown verification service: '{svc}'")


@router.post("/api/diagnostics/save", response_class=JSONResponse)
async def api_diagnostics_save(
    req: SaveConfigRequest,
    ctx: SecurityContext = Depends(require_devops),
) -> Dict[str, Any]:
    """Non-destructively save configuration parameters with pre-save backup."""
    success, msg = save_master_config(req.settings)
    if not success:
        raise HTTPException(status_code=500, detail=msg)

    # Dynamically restart Cloud Relay if URL or Kiosk ID changed
    try:
        from core_platform.app.ingress.relay_client import CloudRelayClient
        relay = CloudRelayClient.get_instance()
        asyncio.create_task(relay.reconfigure_and_restart())
    except Exception as exc:
        logger.warning("[Diagnostics] Failed to trigger live relay reconnect: %s", exc)

    return {"success": True, "message": msg}


@router.post("/api/diagnostics/restore", response_class=JSONResponse)
async def api_diagnostics_restore(
    req: RestoreRequest,
    ctx: SecurityContext = Depends(require_devops),
) -> Dict[str, Any]:
    """Restore configuration from historical backup snapshot."""
    success, msg = restore_backup(req.filename)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@router.post("/api/diagnostics/poller/toggle", response_class=JSONResponse)
async def api_diagnostics_poller_toggle(
    app_name: Optional[str] = None,
    ctx: SecurityContext = Depends(require_devops),
) -> Dict[str, Any]:
    """Toggle background poller worker for an application cartridge with verified clean termination."""
    try:
        from core_platform.main import plugin_loader
        loaded = plugin_loader.get_all_applications()
    except Exception:
        loaded = {}

    target_app = None
    if app_name and app_name in loaded:
        target_app = loaded[app_name]
    else:
        for app_inst in loaded.values():
            if getattr(app_inst, "has_poller", False):
                target_app = app_inst
                break

    if target_app is None:
        return {
            "success": False,
            "is_running": False,
            "status": "NOT_INSTALLED",
            "message": "No active cartridge with a background poller was found.",
        }

    is_now_running, msg = target_app.toggle_poller()
    return {
        "success": True,
        "is_running": is_now_running,
        "status": "RUNNING" if is_now_running else "STOPPED",
        "message": msg,
    }


@router.post("/api/diagnostics/apps/{app_name}/toggle", response_class=JSONResponse)
async def api_diagnostics_app_toggle(
    app_name: str,
    ctx: SecurityContext = Depends(require_devops),
) -> Dict[str, Any]:
    """Dynamically toggle an application between active and inactive state."""
    registry = ApplicationRegistry.get_instance()
    if registry.is_app_active(app_name):
        registry.disable_application(app_name)
        active = False
    else:
        registry.enable_application(app_name)
        active = True

    # Persist updated ENABLED_APPLICATIONS
    save_master_config({"ENABLED_APPLICATIONS": json.dumps(settings.ENABLED_APPLICATIONS)})

    return {
        "success": True,
        "app_name": app_name,
        "is_active": active,
        "enabled_apps": settings.ENABLED_APPLICATIONS,
    }


@router.get("/settings", response_class=HTMLResponse)
async def view_settings_dashboard(
    request: Request,
    ctx: SecurityContext = Depends(require_devops),
) -> HTMLResponse:
    """Render responsive, offline-safe Live Configuration & Testing Console."""
    registry = ApplicationRegistry.get_instance()
    apps = registry.get_installed_applications()
    backups = list_backups()

    # Read live on-disk values so nothing is lost
    env_data = read_env_dict()
    typesafe_key = env_data.get("TYPESAFE_API_KEY", getattr(settings, "TYPESAFE_API_KEY", "") or "")
    typesafe_url = env_data.get("TYPESAFE_BASE_URL", getattr(settings, "TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1") or "https://api.typesafe.ai/v1")
    typesafe_model = env_data.get("TYPESAFE_MODEL", getattr(settings, "TYPESAFE_MODEL", "jev-1") or "jev-1")
    default_decision = env_data.get("DEFAULT_DECISION_PROVIDER", getattr(settings, "DEFAULT_DECISION_PROVIDER", "typesafe") or "typesafe")
    gemini_key = env_data.get("GEMINI_API_KEY", settings.GEMINI_API_KEY or "")
    gemini_model = env_data.get("GEMINI_MODEL", settings.GEMINI_MODEL or "gemini-2.5-flash")
    wa_phone = env_data.get("WHATSAPP_PHONE_NUMBER_ID", settings.WHATSAPP_PHONE_NUMBER_ID or "")
    wa_token = env_data.get("WHATSAPP_ACCESS_TOKEN", settings.WHATSAPP_ACCESS_TOKEN or "")
    wa_secret = env_data.get("WHATSAPP_APP_SECRET", settings.WHATSAPP_APP_SECRET or "")
    wa_verify = env_data.get("WHATSAPP_VERIFY_TOKEN", settings.WHATSAPP_VERIFY_TOKEN or "release100_verify_token")
    relay_url = env_data.get("RELAY_WS_URL", settings.RELAY_WS_URL or "")
    station_name = env_data.get("STATION_NAME", settings.STATION_NAME or "Release100 Node #01")
    node_id = env_data.get("NODE_ID", env_data.get("KIOSK_ID", settings.NODE_ID or "NODE-01"))
    org_name = env_data.get("ORGANIZATION_NAME", settings.ORGANIZATION_NAME or "Release100 Organization")
    tenant_id = env_data.get("TENANT_ID", settings.TENANT_ID or "default_tenant")
    exec_mode = env_data.get("EXECUTION_MODE", settings.EXECUTION_MODE or "shadow")
    dry_run_val = env_data.get("DRY_RUN", str(settings.DRY_RUN)).lower() == "true"

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=ctx,
        allowed_apps=[a.app_name for a in apps if a.is_active],
        tenant_name=str(org_name),
        breadcrumbs=[
            Breadcrumb(label_key="core.nav.platform_dashboard", path="/admin/"),
            Breadcrumb(label_key="core.nav.settings"),
        ],
        node_id=str(node_id),
        station_name=str(station_name),
    )

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "title": "Master Settings & Diagnostics",
            "principal": ctx.principal_id,
            "is_admin": ctx.is_admin,
            "is_devops": ctx.is_devops,
            "apps": apps,
            "backups": backups,
            "gemini_key": gemini_key,
            "gemini_model": gemini_model,
            "typesafe_key": typesafe_key,
            "typesafe_url": typesafe_url,
            "typesafe_model": typesafe_model,
            "default_decision": default_decision,
            "wa_phone": wa_phone,
            "wa_token": wa_token,
            "wa_secret": wa_secret,
            "wa_verify": wa_verify,
            "relay_url": relay_url,
            "station_name": station_name,
            "node_id": node_id,
            "org_name": org_name,
            "tenant_id": tenant_id,
            "exec_mode": exec_mode,
            "dry_run_val": dry_run_val,
            "port": settings.ORCHESTRATOR_PORT,
            "mcp_port": settings.MCP_SERVER_PORT,
            "ui": ui_ctx,
        },
    )
