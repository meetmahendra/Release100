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

logger = logging.getLogger("core_platform.diagnostics_web")
router = APIRouter(tags=["diagnostics"])


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

    # App cards HTML
    app_cards_html = ""
    for app in apps:
        status_color = "#10b981" if app.is_active else "#6b7280"
        status_badge = "ACTIVE" if app.is_active else "INACTIVE"
        btn_action = "Disable" if app.is_active else "Enable"
        btn_class = "btn-danger" if app.is_active else "btn-primary"

        poller_widget = ""
        if app.has_poller:
            poller_running = (app.poller_status == "RUNNING")
            p_color = "#10b981" if poller_running else "#ef4444"
            p_badge = "RUNNING" if poller_running else "STOPPED"
            p_btn_label = "Stop Poller" if poller_running else "Start Poller"
            poller_widget = f"""
            <div style="margin-top: 14px; padding: 12px; background: rgba(0,0,0,0.2); border-radius: 8px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="font-size: 13px; font-weight: 600;">Background Email Poller:</span>
                    <span style="display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: bold; background: {p_color}; color: white;">{p_badge}</span>
                    <p style="margin: 4px 0 0 0; font-size: 11px; color: #9ca3af;">Cooperative sentinel-based shutdown (Resolving ISSUE-005).</p>
                </div>
                <button class="btn btn-sm" onclick="togglePoller('{app.app_name}')" style="background: {'#ef4444' if poller_running else '#10b981'}; color: white; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">{p_btn_label}</button>
            </div>
            """

        app_cards_html += f"""
        <div class="card" style="border-left: 4px solid {status_color}; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div>
                    <h3 style="margin: 0 0 6px 0; font-size: 18px; color: #f3f4f6;">{app.title}</h3>
                    <p style="margin: 0; font-size: 13px; color: #9ca3af;">{app.description}</p>
                </div>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <span style="padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: bold; background: {status_color}; color: white;">{status_badge}</span>
                    <a href="{app.dashboard_url}" target="_blank" class="btn btn-sm btn-outline" style="text-decoration: none; padding: 6px 12px; font-size: 12px;">Open Dashboard</a>
                    <button class="btn btn-sm {btn_class}" onclick="toggleApp('{app.app_name}')" style="padding: 6px 12px; font-size: 12px;">{btn_action}</button>
                </div>
            </div>
            {poller_widget}
        </div>
        """

    backup_rows_html = ""
    for b in backups[:12]:
        backup_rows_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #374151; font-family: monospace; font-size: 12px;">{b['filename']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #374151; font-size: 12px; color: #9ca3af;">{b['modified_utc'][:19]}</td>
            <td style="padding: 10px; border-bottom: 1px solid #374151; font-size: 12px; color: #9ca3af;">{round(b['size_bytes']/1024, 1)} KB</td>
            <td style="padding: 10px; border-bottom: 1px solid #374151; text-align: right;">
                <button class="btn btn-sm btn-outline" onclick="restoreBackup('{b['filename']}')" style="padding: 4px 10px; font-size: 11px;">Restore</button>
            </td>
        </tr>
        """
    if not backup_rows_html:
        backup_rows_html = "<tr><td colspan='4' style='padding: 16px; text-align: center; color: #9ca3af;'>No configuration backups created yet.</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Release100 — Live Settings & Diagnostics</title>
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #273548;
            --accent: #10b981;
            --accent-hover: #059669;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border: #334155;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --blue: #3b82f6;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1050px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .tabs {{
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border);
        }}
        .tab-btn {{
            padding: 10px 18px;
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
            color: var(--text-muted);
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }}
        .tab-btn.active {{
            color: var(--accent);
            border-bottom-color: var(--accent);
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        .card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 18px;
            margin-bottom: 16px;
        }}
        .btn {{
            padding: 8px 16px;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            border: 1px solid transparent;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            text-decoration: none;
            font-size: 13px;
        }}
        .btn-primary {{ background: var(--accent); color: white; }}
        .btn-primary:hover {{ background: var(--accent-hover); }}
        .btn-blue {{ background: var(--blue); color: white; }}
        .btn-danger {{ background: var(--danger); color: white; }}
        .btn-outline {{ background: transparent; border-color: var(--border); color: var(--text-main); }}
        .btn-outline:hover {{ background: var(--bg-card); }}
        .input-group {{
            margin-bottom: 14px;
        }}
        .input-group label {{
            display: block;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 6px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .input-group p {{
            margin: 2px 0 6px 0;
            font-size: 11px;
            color: var(--text-muted);
        }}
        .input-control {{
            width: 100%;
            box-sizing: border-box;
            background: var(--bg-primary);
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 10px 12px;
            border-radius: 6px;
            font-size: 14px;
            font-family: inherit;
        }}
        .input-control:focus {{
            outline: none;
            border-color: var(--accent);
        }}
        .diag-result {{
            margin-top: 10px;
            padding: 10px 14px;
            border-radius: 6px;
            font-size: 13px;
            display: none;
            word-break: break-word;
        }}
        .diag-ok {{ background: rgba(16, 185, 129, 0.15); border: 1px solid var(--success); color: #34d399; }}
        .diag-warn {{ background: rgba(245, 158, 11, 0.15); border: 1px solid var(--warning); color: #fbbf24; }}
        .diag-err {{ background: rgba(239, 68, 68, 0.15); border: 1px solid var(--danger); color: #f87171; }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .field-row {{
            display: flex;
            gap: 12px;
            align-items: center;
        }}
        .field-flex {{
            flex: 1;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 9999px;
            font-size: 11px;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>⚙️ Release100 — Live Settings & Diagnostics</h1>
                <p style="margin: 4px 0 0 0; color: #94a3b8; font-size: 13px;">
                    Node: <strong>{node_id}</strong> ({station_name}) &bull; Tenant: {tenant_id}
                </p>
            </div>
            <div style="display: flex; gap: 8px;">
                <a href="/admin/" class="btn btn-outline">← Back to Admin Shell</a>
                <a href="/health" target="_blank" class="btn btn-outline">Heartbeat JSON</a>
            </div>
        </div>

        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('tab-diag')">Live Diagnostics & Testing</button>
            <button class="tab-btn" onclick="switchTab('tab-config')">Configuration & Backups</button>
            <button class="tab-btn" onclick="switchTab('tab-apps')">Active Applications</button>
        </div>

        <!-- TAB 1: LIVE DIAGNOSTICS & TESTING -->
        <div id="tab-diag" class="tab-content active">
            <p style="color: #94a3b8; font-size: 14px; margin-bottom: 16px;">
                Test real credentials and endpoints on the fly. You can paste keys here to verify them before saving to disk.
            </p>

            <!-- 1. TypeSafe AI / Jev System 1 Decision Engine -->
            <div class="card" style="border-left: 4px solid #38bdf8;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                    <div>
                        <h4 style="margin: 0; font-size: 16px; color: #38bdf8;">⚡ TypeSafe AI / Jev System 1 Decision Engine</h4>
                        <p style="margin: 4px 0 0 0; font-size: 12px; color: #94a3b8;">
                            Non-autoregressive decision engine delivering sub-100ms email triage, intent routing, and cognitive skill parsing.
                        </p>
                    </div>
                    <span class="badge" style="background: {'rgba(16,185,129,0.2); color:#34d399;' if typesafe_key else 'rgba(239,68,68,0.2); color:#f87171;'}">
                        {'KEY CONFIGURED' if typesafe_key else 'NO KEY'}
                    </span>
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;">TypeSafe API Key (TYPESAFE_API_KEY)</label>
                    <div style="display: flex; gap: 8px; margin-top: 4px;">
                        <input type="password" id="test-typesafe-key" value="{typesafe_key}" placeholder="Paste TypeSafe AI / Jev API Key" class="input-control field-flex">
                        <button class="btn btn-outline" type="button" onclick="toggleVisibility('test-typesafe-key')">👁️</button>
                    </div>
                </div>
                <div class="field-row" style="margin-bottom: 10px;">
                    <div class="field-flex">
                        <label style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;">Base URL (TYPESAFE_BASE_URL)</label>
                        <input type="text" id="test-typesafe-url" value="{typesafe_url}" placeholder="https://api.typesafe.ai/v1" class="input-control">
                    </div>
                    <div class="field-flex">
                        <label style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;">Decision Model (TYPESAFE_MODEL)</label>
                        <input type="text" id="test-typesafe-model" value="{typesafe_model}" placeholder="jev-1" class="input-control">
                    </div>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-primary" onclick="runVerifyTypeSafe()">⚡ Test Jev Decision</button>
                    <button class="btn btn-blue" onclick="quickSaveTypeSafe()">💾 Save to .env</button>
                </div>
                <div id="res-typesafe" class="diag-result"></div>
            </div>

            <!-- 2. Gemini Ping -->
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                    <div>
                        <h4 style="margin: 0; font-size: 16px;">🧠 Google Gemini API Ping</h4>
                        <p style="margin: 4px 0 0 0; font-size: 12px; color: #94a3b8;">
                            Issues a minimal live 2-token generation request to Google AI Studio.
                        </p>
                    </div>
                    <span class="badge" style="background: {'rgba(16,185,129,0.2); color:#34d399;' if gemini_key else 'rgba(239,68,68,0.2); color:#f87171;'}">
                        {'KEY CONFIGURED' if gemini_key else 'NO KEY'}
                    </span>
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;">Gemini API Key</label>
                    <div style="display: flex; gap: 8px; margin-top: 4px;">
                        <input type="password" id="test-gemini-key" value="{gemini_key}" placeholder="Paste Google AI Studio API Key (AIzaSy...)" class="input-control field-flex">
                        <button class="btn btn-outline" type="button" onclick="toggleVisibility('test-gemini-key')">👁️</button>
                        <button class="btn btn-primary" onclick="runVerifyGemini()">Test Key</button>
                        <button class="btn btn-blue" onclick="quickSaveGemini()">💾 Save to .env</button>
                    </div>
                </div>
                <div id="res-gemini" class="diag-result"></div>
            </div>

            <!-- 2. Meta WhatsApp Cloud API -->
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                    <div>
                        <h4 style="margin: 0; font-size: 16px;">💬 Meta WhatsApp Cloud API</h4>
                        <p style="margin: 4px 0 0 0; font-size: 12px; color: #94a3b8;">
                            Queries Meta Graph API (v19.0) to verify registered phone number name and system token.
                        </p>
                    </div>
                    <span class="badge" style="background: {'rgba(16,185,129,0.2); color:#34d399;' if wa_token and wa_phone else 'rgba(239,68,68,0.2); color:#f87171;'}">
                        {'CONFIGURED' if wa_token and wa_phone else 'INCOMPLETE'}
                    </span>
                </div>
                <div class="field-row" style="margin-bottom: 8px;">
                    <div class="field-flex">
                        <label style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;">Phone Number ID</label>
                        <input type="text" id="test-wa-phone" value="{wa_phone}" placeholder="Phone Number ID (e.g. 105948392019485)" class="input-control">
                    </div>
                    <div class="field-flex">
                        <label style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;">Access Token</label>
                        <div style="display: flex; gap: 6px;">
                            <input type="password" id="test-wa-token" value="{wa_token}" placeholder="Permanent or 24h User Token (EAA...)" class="input-control">
                            <button class="btn btn-outline" type="button" onclick="toggleVisibility('test-wa-token')">👁️</button>
                        </div>
                    </div>
                </div>
                <div style="display: flex; gap: 8px; margin-top: 8px;">
                    <button class="btn btn-primary" onclick="runVerifyWhatsApp()">Test WhatsApp Profile</button>
                    <button class="btn btn-blue" onclick="quickSaveWhatsApp()">💾 Save to .env</button>
                </div>
                <div id="res-whatsapp" class="diag-result"></div>
            </div>

            <!-- 3. Webhook Ingress Challenge -->
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                    <div>
                        <h4 style="margin: 0; font-size: 16px;">📥 Webhook Ingress Challenge (GET /webhook)</h4>
                        <p style="margin: 4px 0 0 0; font-size: 12px; color: #94a3b8;">
                            Simulates Meta's webhook handshake against local port {settings.ORCHESTRATOR_PORT} using your verify token.
                        </p>
                    </div>
                </div>
                <div style="display: flex; gap: 8px;">
                    <input type="text" id="test-wa-verify" value="{wa_verify}" placeholder="Verify Token (e.g. apex_verify_token_2026)" class="input-control field-flex">
                    <button class="btn btn-primary" onclick="runVerifyWebhook()">Test Webhook Challenge</button>
                </div>
                <div id="res-webhook" class="diag-result"></div>
            </div>

            <!-- 4. HMAC App Secret -->
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                    <div>
                        <h4 style="margin: 0; font-size: 16px;">🔐 Meta App Secret (HMAC-SHA256 Signature Verification)</h4>
                        <p style="margin: 4px 0 0 0; font-size: 12px; color: #94a3b8;">
                            Validates that the Meta App Secret can sign incoming POST webhook payloads.
                        </p>
                    </div>
                </div>
                <div style="display: flex; gap: 8px;">
                    <input type="password" id="test-wa-secret" value="{wa_secret}" placeholder="Meta App Secret from Meta Developer Dashboard" class="input-control field-flex">
                    <button class="btn btn-outline" type="button" onclick="toggleVisibility('test-wa-secret')">👁️</button>
                    <button class="btn btn-primary" onclick="runVerifyHMAC()">Verify HMAC Secret</button>
                </div>
                <div id="res-hmac" class="diag-result"></div>
            </div>

            <!-- 5. Outbound Cloud Relay -->
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
                    <div>
                        <h4 style="margin: 0; font-size: 16px;">🌐 Outbound Zero-Inbound Cloud Relay</h4>
                        <p style="margin: 4px 0 0 0; font-size: 12px; color: #94a3b8;">
                            Bypasses factory firewalls by connecting outbound to a Cloudflare Worker or Render edge relay.
                        </p>
                    </div>
                </div>
                <div style="background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.25); border-radius: 8px; padding: 10px; margin-bottom: 10px; font-size: 12px; color: #93c5fd;">
                    💡 <strong>Cloudflare Worker tip:</strong> Paste your Cloudflare Worker URL directly (e.g. <code>https://release100-relay.your-name.workers.dev</code>). The system automatically transforms it into <code>wss://.../ws/{node_id}</code>!
                </div>
                <div style="display: flex; gap: 8px;">
                    <input type="text" id="test-relay-url" value="{relay_url}" placeholder="e.g. https://release100-relay.xyz.workers.dev" class="input-control field-flex" oninput="updateRelayPreview()">
                    <button class="btn btn-primary" onclick="runVerifyRelay()">Test Cloud Relay</button>
                    <button class="btn btn-blue" onclick="quickSaveRelay()">💾 Save</button>
                </div>
                <div id="relay-preview" style="font-size: 11px; font-family: monospace; color: #38bdf8; margin-top: 6px;"></div>
                <div id="res-cloud_relay" class="diag-result"></div>
            </div>

            <!-- 6. Outbound WhatsApp Message -->
            <div class="card">
                <h4 style="margin: 0 0 6px 0; font-size: 16px;">📱 Live Outbound WhatsApp Test Dispatch</h4>
                <p style="margin: 0 0 10px 0; font-size: 12px; color: #94a3b8;">
                    Send an actual test notification message to a field operator's phone.
                </p>
                <div class="field-row">
                    <input type="text" id="test-phone" placeholder="Recipient Phone (e.g. 919876543210)" class="input-control" style="flex: 1;">
                    <input type="text" id="test-msg-body" value="Hello from Release100! Your platform node connection is operational." class="input-control" style="flex: 2;">
                    <button class="btn btn-primary" onclick="sendTestMsg()">Send Message</button>
                </div>
                <div id="res-whatsapp_send" class="diag-result"></div>
            </div>
        </div>

        <!-- TAB 2: CONFIGURATION & DISK SETTINGS -->
        <div id="tab-config" class="tab-content">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                <p style="color: #94a3b8; font-size: 14px; margin: 0;">
                    All settings saved here write directly to <code>.env</code> with an automatic pre-save backup in <code>config_backups/</code>.
                </p>
                <button class="btn btn-primary" onclick="saveAllConfig()">💾 Save All Settings to .env</button>
            </div>

            <!-- 1. AI, LLM & Decision Engines -->
            <div class="card">
                <h3 style="margin-top: 0; font-size: 17px; border-bottom: 1px solid var(--border); padding-bottom: 8px; color: #38bdf8;">
                    🧠 AI, LLM & Decision Engines
                </h3>
                <div class="input-group">
                    <label>⚡ TypeSafe AI / Jev API Key (TYPESAFE_API_KEY)</label>
                    <p>Obtained from TypeSafe AI. Used for sub-100ms System 1 email triage and intent routing.</p>
                    <div style="display: flex; gap: 8px;">
                        <input type="password" id="cfg-typesafe-key" value="{typesafe_key}" placeholder="Paste TypeSafe API Key" class="input-control field-flex">
                        <button class="btn btn-outline" type="button" onclick="toggleVisibility('cfg-typesafe-key')">👁️</button>
                    </div>
                </div>
                <div class="field-row">
                    <div class="input-group field-flex">
                        <label>TypeSafe Base URL (TYPESAFE_BASE_URL)</label>
                        <input type="text" id="cfg-typesafe-url" value="{typesafe_url}" placeholder="https://api.typesafe.ai/v1" class="input-control">
                    </div>
                    <div class="input-group field-flex">
                        <label>TypeSafe Model (TYPESAFE_MODEL)</label>
                        <input type="text" id="cfg-typesafe-model" value="{typesafe_model}" placeholder="jev-1" class="input-control">
                    </div>
                    <div class="input-group field-flex">
                        <label>Decision Provider</label>
                        <select id="cfg-decision-provider" class="input-control">
                            <option value="typesafe" {'selected' if default_decision == 'typesafe' else ''}>TypeSafe / Jev (Fast System 1)</option>
                            <option value="gemini" {'selected' if default_decision == 'gemini' else ''}>Gemini (System 2 Fallback)</option>
                        </select>
                    </div>
                </div>
                <div class="input-group">
                    <label>Google Gemini API Key (GEMINI_API_KEY)</label>
                    <p>Obtained from Google AI Studio. Used for Display OCR and generative System 2 reasoning.</p>
                    <div style="display: flex; gap: 8px;">
                        <input type="password" id="cfg-gemini-key" value="{gemini_key}" placeholder="AIzaSy..." class="input-control field-flex">
                        <button class="btn btn-outline" type="button" onclick="toggleVisibility('cfg-gemini-key')">👁️</button>
                    </div>
                </div>
                <div class="field-row">
                    <div class="input-group field-flex">
                        <label>Gemini Model (GEMINI_MODEL)</label>
                        <input type="text" id="cfg-model" value="{gemini_model}" class="input-control">
                    </div>
                    <div class="input-group field-flex">
                        <label>Execution Mode</label>
                        <select id="cfg-mode" class="input-control">
                            <option value="shadow" {'selected' if exec_mode == 'shadow' else ''}>Shadow (Simulation / Dry Run)</option>
                            <option value="assistive" {'selected' if exec_mode == 'assistive' else ''}>Assistive (Human Approval Required)</option>
                            <option value="autonomous" {'selected' if exec_mode == 'autonomous' else ''}>Autonomous (Fully Automated)</option>
                        </select>
                    </div>
                    <div class="input-group" style="width: 140px;">
                        <label>DRY_RUN</label>
                        <select id="cfg-dry-run" class="input-control">
                            <option value="True" {'selected' if dry_run_val else ''}>True (Safe)</option>
                            <option value="False" {'selected' if not dry_run_val else ''}>False (Live)</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- 2. WhatsApp -->
            <div class="card">
                <h3 style="margin-top: 0; font-size: 17px; border-bottom: 1px solid var(--border); padding-bottom: 8px; color: #34d399;">
                    💬 Meta WhatsApp Cloud API & Ingress
                </h3>
                <div class="field-row">
                    <div class="input-group field-flex">
                        <label>Phone Number ID (WHATSAPP_PHONE_NUMBER_ID)</label>
                        <input type="text" id="cfg-wa-phone" value="{wa_phone}" placeholder="e.g. 105948392019485" class="input-control">
                    </div>
                    <div class="input-group field-flex">
                        <label>Webhook Verify Token (WHATSAPP_VERIFY_TOKEN)</label>
                        <input type="text" id="cfg-wa-verify" value="{wa_verify}" placeholder="e.g. apex_verify_token_2026" class="input-control">
                    </div>
                </div>
                <div class="input-group">
                    <label>WhatsApp Access Token (WHATSAPP_ACCESS_TOKEN)</label>
                    <div style="display: flex; gap: 8px;">
                        <input type="password" id="cfg-wa-token" value="{wa_token}" placeholder="EAA..." class="input-control field-flex">
                        <button class="btn btn-outline" type="button" onclick="toggleVisibility('cfg-wa-token')">👁️</button>
                    </div>
                </div>
                <div class="input-group">
                    <label>Meta App Secret (WHATSAPP_APP_SECRET)</label>
                    <div style="display: flex; gap: 8px;">
                        <input type="password" id="cfg-wa-secret" value="{wa_secret}" placeholder="32-char hex secret from Meta App Dashboard" class="input-control field-flex">
                        <button class="btn btn-outline" type="button" onclick="toggleVisibility('cfg-wa-secret')">👁️</button>
                    </div>
                </div>
            </div>

            <!-- 3. Cloud Relay & Identity -->
            <div class="card">
                <h3 style="margin-top: 0; font-size: 17px; border-bottom: 1px solid var(--border); padding-bottom: 8px; color: #a78bfa;">
                    🌐 Outbound Cloud Relay & Platform Node Identity
                </h3>
                <div class="input-group">
                    <label>Outbound Cloud Relay URL (RELAY_WS_URL)</label>
                    <p>Paste Cloudflare Worker base URL (e.g. <code>https://release100-relay.xyz.workers.dev</code>).</p>
                    <input type="text" id="cfg-relay" value="{relay_url}" class="input-control">
                </div>
                <div class="field-row">
                    <div class="input-group field-flex">
                        <label>Station / Facility Name (STATION_NAME)</label>
                        <input type="text" id="cfg-station" value="{station_name}" class="input-control">
                    </div>
                    <div class="input-group field-flex">
                        <label>Platform Node / Host ID (NODE_ID)</label>
                        <input type="text" id="cfg-node" value="{node_id}" class="input-control">
                    </div>
                </div>
                <div class="field-row">
                    <div class="input-group field-flex">
                        <label>Organization Name (ORGANIZATION_NAME)</label>
                        <input type="text" id="cfg-org" value="{org_name}" class="input-control">
                    </div>
                    <div class="input-group field-flex">
                        <label>Tenant ID (TENANT_ID)</label>
                        <input type="text" id="cfg-tenant" value="{tenant_id}" class="input-control">
                    </div>
                </div>
            </div>

            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 24px;">
                <button class="btn btn-primary" style="font-size: 15px; padding: 10px 24px;" onclick="saveAllConfig()">💾 Save All Settings (With Backup)</button>
                <span id="save-status" style="font-size: 13px; font-weight: 600;"></span>
            </div>

            <!-- Historical Backups -->
            <div class="card">
                <h3 style="margin-top: 0; font-size: 17px; border-bottom: 1px solid var(--border); padding-bottom: 8px;">
                    🗂️ Historical Configuration Snapshots & 1-Click Rollback
                </h3>
                <table>
                    <thead>
                        <tr>
                            <th style="text-align: left; padding: 8px; color: #94a3b8; font-size: 12px;">Backup Filename</th>
                            <th style="text-align: left; padding: 8px; color: #94a3b8; font-size: 12px;">Date & Time (UTC)</th>
                            <th style="text-align: left; padding: 8px; color: #94a3b8; font-size: 12px;">Size</th>
                            <th style="text-align: right; padding: 8px; color: #94a3b8; font-size: 12px;">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {backup_rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- TAB 3: ACTIVE APPLICATIONS -->
        <div id="tab-apps" class="tab-content">
            <p style="color: #94a3b8; font-size: 14px; margin-bottom: 16px;">
                Installed domain cartridges dynamically discovered in the <code>apps/</code> directory.
            </p>
            {app_cards_html}
        </div>
    </div>

    <script>
        function switchTab(tabId) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }}

        function toggleVisibility(inputId) {{
            const el = document.getElementById(inputId);
            if (el.type === 'password') {{
                el.type = 'text';
            }} else {{
                el.type = 'password';
            }}
        }}

        function updateRelayPreview() {{
            const raw = document.getElementById('test-relay-url').value.trim();
            const node = document.getElementById('cfg-node') ? document.getElementById('cfg-node').value.trim() : '{node_id}';
            const prev = document.getElementById('relay-preview');
            if (!raw) {{
                prev.innerText = 'Relay not configured (running in local simulator mode).';
                return;
            }}
            let formatted = raw.startsWith('https://') ? 'wss://' + raw.slice(8) : (raw.startsWith('http://') ? 'ws://' + raw.slice(7) : raw);
            if (formatted.includes('{{node_id}}') || formatted.includes('{{kiosk_id}}')) {{
                formatted = formatted.replace('{{node_id}}', node).replace('{{kiosk_id}}', node);
            }} else if (formatted.includes('/ws/')) {{
                // already has /ws/
            }} else if (formatted.endsWith('/ws')) {{
                formatted = formatted + '/' + node;
            }} else {{
                const cleanBase = formatted.endsWith('/') ? formatted.slice(0, -1) : formatted;
                formatted = cleanBase + '/ws/' + node;
            }}
            prev.innerText = 'Effective WebSocket: ' + formatted;
        }}
        updateRelayPreview();

        async function runVerifyTypeSafe() {{
            const key = document.getElementById('test-typesafe-key').value.trim();
            const url = document.getElementById('test-typesafe-url').value.trim();
            const model = document.getElementById('test-typesafe-model').value.trim();
            const el = document.getElementById('res-typesafe');
            el.style.display = 'block';
            el.className = 'diag-result';
            el.innerText = 'Testing TypeSafe AI / Jev decision probe...';
            try {{
                const res = await fetch('/api/diagnostics/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ service: 'typesafe', key: key, base_url: url, model: model }})
                }});
                const data = await res.json();
                el.className = data.status === 'ok' ? 'diag-result diag-ok' : (data.status === 'warning' ? 'diag-result diag-warn' : 'diag-result diag-err');
                el.innerText = data.message;
            }} catch (err) {{
                el.className = 'diag-result diag-err';
                el.innerText = 'TypeSafe test failed: ' + err;
            }}
        }}

        async function quickSaveTypeSafe() {{
            const key = document.getElementById('test-typesafe-key').value.trim();
            const url = document.getElementById('test-typesafe-url').value.trim();
            const model = document.getElementById('test-typesafe-model').value.trim();
            if (!key && !url.includes('localhost') && !url.includes('127.0.0.1')) {{
                alert('Please enter a TypeSafe API Key first.');
                return;
            }}
            await saveMultiSettings({{
                TYPESAFE_API_KEY: key,
                TYPESAFE_BASE_URL: url,
                TYPESAFE_MODEL: model,
                DEFAULT_DECISION_PROVIDER: 'typesafe'
            }}, 'TypeSafe AI / Jev settings saved to .env!');
        }}

        async function runVerifyGemini() {{
            const key = document.getElementById('test-gemini-key').value.trim();
            const el = document.getElementById('res-gemini');
            el.style.display = 'block';
            el.className = 'diag-result';
            el.innerText = 'Testing Gemini API with provided key...';
            try {{
                const res = await fetch('/api/diagnostics/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ service: 'gemini', key: key }})
                }});
                const data = await res.json();
                el.className = data.status === 'ok' ? 'diag-result diag-ok' : (data.status === 'warning' ? 'diag-result diag-warn' : 'diag-result diag-err');
                el.innerText = data.message;
            }} catch (err) {{
                el.className = 'diag-result diag-err';
                el.innerText = 'Gemini test failed: ' + err;
            }}
        }}

        async function quickSaveGemini() {{
            const key = document.getElementById('test-gemini-key').value.trim();
            if (!key) {{ alert('Please enter a Gemini API Key first.'); return; }}
            await saveSingleSetting('GEMINI_API_KEY', key, 'Gemini API Key saved to .env!');
        }}

        async function runVerifyWhatsApp() {{
            const phone = document.getElementById('test-wa-phone').value.trim();
            const token = document.getElementById('test-wa-token').value.trim();
            const el = document.getElementById('res-whatsapp');
            el.style.display = 'block';
            el.className = 'diag-result';
            el.innerText = 'Testing Meta WhatsApp Graph API...';
            try {{
                const res = await fetch('/api/diagnostics/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ service: 'whatsapp', phone_id: phone, token: token }})
                }});
                const data = await res.json();
                el.className = data.status === 'ok' ? 'diag-result diag-ok' : 'diag-result diag-err';
                el.innerText = data.message;
            }} catch (err) {{
                el.className = 'diag-result diag-err';
                el.innerText = 'WhatsApp verification failed: ' + err;
            }}
        }}

        async function quickSaveWhatsApp() {{
            const phone = document.getElementById('test-wa-phone').value.trim();
            const token = document.getElementById('test-wa-token').value.trim();
            await saveMultiSettings({{
                WHATSAPP_PHONE_NUMBER_ID: phone,
                WHATSAPP_ACCESS_TOKEN: token
            }}, 'WhatsApp credentials saved to .env!');
        }}

        async function runVerifyWebhook() {{
            const tok = document.getElementById('test-wa-verify').value.trim();
            const el = document.getElementById('res-webhook');
            el.style.display = 'block';
            el.className = 'diag-result';
            el.innerText = 'Simulating Meta Webhook Challenge...';
            try {{
                const res = await fetch('/api/diagnostics/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ service: 'webhook', verify_token: tok }})
                }});
                const data = await res.json();
                el.className = data.status === 'ok' ? 'diag-result diag-ok' : 'diag-result diag-err';
                el.innerText = data.message;
            }} catch (err) {{
                el.className = 'diag-result diag-err';
                el.innerText = 'Webhook test failed: ' + err;
            }}
        }}

        async function runVerifyHMAC() {{
            const sec = document.getElementById('test-wa-secret').value.trim();
            const el = document.getElementById('res-hmac');
            el.style.display = 'block';
            el.className = 'diag-result';
            el.innerText = 'Verifying HMAC Secret...';
            try {{
                const res = await fetch('/api/diagnostics/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ service: 'hmac', app_secret: sec }})
                }});
                const data = await res.json();
                el.className = data.status === 'ok' ? 'diag-result diag-ok' : 'diag-result diag-err';
                el.innerText = data.message;
            }} catch (err) {{
                el.className = 'diag-result diag-err';
                el.innerText = 'HMAC verification failed: ' + err;
            }}
        }}

        async function runVerifyRelay() {{
            const url = document.getElementById('test-relay-url').value.trim();
            const el = document.getElementById('res-cloud_relay');
            el.style.display = 'block';
            el.className = 'diag-result';
            el.innerText = 'Pinging Cloud Relay endpoint...';
            try {{
                const res = await fetch('/api/diagnostics/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ service: 'cloud_relay', relay_url: url }})
                }});
                const data = await res.json();
                el.className = data.status === 'ok' ? 'diag-result diag-ok' : (data.status === 'warning' ? 'diag-result diag-warn' : 'diag-result diag-err');
                el.innerText = data.message;
            }} catch (err) {{
                el.className = 'diag-result diag-err';
                el.innerText = 'Relay test failed: ' + err;
            }}
        }}

        async function quickSaveRelay() {{
            const url = document.getElementById('test-relay-url').value.trim().replace(/^["']|["']$/g, '');
            await saveSingleSetting('RELAY_WS_URL', url, 'Relay URL saved to .env!');
        }}

        async function sendTestMsg() {{
            const phone = document.getElementById('test-phone').value.trim();
            const msg = document.getElementById('test-msg-body').value.trim();
            const el = document.getElementById('res-whatsapp_send');
            if (!phone) {{ alert('Please enter a recipient phone number.'); return; }}
            el.style.display = 'block';
            el.className = 'diag-result';
            el.innerText = 'Sending test WhatsApp message to ' + phone + '...';
            try {{
                const res = await fetch('/api/diagnostics/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        service: 'whatsapp_send',
                        recipient_phone: phone,
                        message: msg,
                        token: document.getElementById('test-wa-token').value.trim(),
                        phone_id: document.getElementById('test-wa-phone').value.trim()
                    }})
                }});
                const data = await res.json();
                el.className = data.status === 'ok' ? 'diag-result diag-ok' : 'diag-result diag-err';
                el.innerText = data.message;
            }} catch (err) {{
                el.className = 'diag-result diag-err';
                el.innerText = 'Send failed: ' + err;
            }}
        }}

        async function saveSingleSetting(key, val, successMsg) {{
            const payload = {{ settings: {{ [key]: val }} }};
            const res = await fetch('/api/diagnostics/save', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }});
            const data = await res.json();
            alert(successMsg || data.message);
            window.location.reload();
        }}

        async function saveMultiSettings(dict, successMsg) {{
            const payload = {{ settings: dict }};
            const res = await fetch('/api/diagnostics/save', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }});
            const data = await res.json();
            alert(successMsg || data.message);
            window.location.reload();
        }}

        async function saveAllConfig() {{
            const payload = {{
                settings: {{
                    TYPESAFE_API_KEY: document.getElementById('cfg-typesafe-key').value.trim(),
                    TYPESAFE_BASE_URL: document.getElementById('cfg-typesafe-url').value.trim(),
                    TYPESAFE_MODEL: document.getElementById('cfg-typesafe-model').value.trim(),
                    DEFAULT_DECISION_PROVIDER: document.getElementById('cfg-decision-provider').value,
                    GEMINI_API_KEY: document.getElementById('cfg-gemini-key').value.trim(),
                    GEMINI_MODEL: document.getElementById('cfg-model').value.trim(),
                    WHATSAPP_PHONE_NUMBER_ID: document.getElementById('cfg-wa-phone').value.trim(),
                    WHATSAPP_ACCESS_TOKEN: document.getElementById('cfg-wa-token').value.trim(),
                    WHATSAPP_APP_SECRET: document.getElementById('cfg-wa-secret').value.trim(),
                    WHATSAPP_VERIFY_TOKEN: document.getElementById('cfg-wa-verify').value.trim(),
                    RELAY_WS_URL: document.getElementById('cfg-relay').value.trim().replace(/^["']|["']$/g, ''),
                    STATION_NAME: document.getElementById('cfg-station').value.trim(),
                    NODE_ID: document.getElementById('cfg-node').value.trim(),
                    KIOSK_ID: document.getElementById('cfg-node').value.trim(),
                    ORGANIZATION_NAME: document.getElementById('cfg-org').value.trim(),
                    TENANT_ID: document.getElementById('cfg-tenant').value.trim(),
                    EXECUTION_MODE: document.getElementById('cfg-mode').value,
                    DRY_RUN: document.getElementById('cfg-dry-run').value
                }}
            }};
            const st = document.getElementById('save-status');
            st.style.color = '#38bdf8';
            st.innerText = 'Saving all settings...';

            try {{
                const res = await fetch('/api/diagnostics/save', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                const data = await res.json();
                st.style.color = '#34d399';
                st.innerText = '✅ Saved! Snapshot created.';
                setTimeout(() => window.location.reload(), 1200);
            }} catch (err) {{
                st.style.color = '#f87171';
                st.innerText = '❌ Error saving: ' + err;
            }}
        }}

        async function restoreBackup(filename) {{
            if (!confirm('Rollback configuration to snapshot: ' + filename + '?')) return;
            try {{
                const res = await fetch('/api/diagnostics/restore', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ filename: filename }})
                }});
                const data = await res.json();
                alert(data.message);
                window.location.reload();
            }} catch (err) {{
                alert('Error restoring backup: ' + err);
            }}
        }}

        async function togglePoller(appName) {{
            try {{
                const url = appName ? '/api/diagnostics/poller/toggle?app_name=' + encodeURIComponent(appName) : '/api/diagnostics/poller/toggle';
                const res = await fetch(url, {{ method: 'POST' }});
                const data = await res.json();
                alert(data.message);
                window.location.reload();
            }} catch (err) {{
                alert('Error toggling poller: ' + err);
            }}
        }}

        async function toggleApp(appName) {{
            try {{
                const res = await fetch('/api/diagnostics/apps/' + appName + '/toggle', {{ method: 'POST' }});
                const data = await res.json();
                window.location.reload();
            }} catch (err) {{
                alert('Error toggling application: ' + err);
            }}
        }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html, status_code=200)
