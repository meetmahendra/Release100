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
FastAPI Routes for AI Mail and Calendar Organizer Admin Web Shell.

Provides endpoints for:
- Dashboard: KPI metrics, category breakdowns, pending PM task counts.
- Triage Simulator: Interactive email processing through the complete LangGraph pipeline.
- PM Action Queue: Human-in-the-Loop review, one-click Jira/Linear approval and sync.
- Rules Manager: Deterministic VIP whitelists and domain rules.
- Drafts Review: Staged contextual draft replies.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.state import MailOrganizerState
from apps.mail_organizer.graph.state_graph import MailOrganizerWorkflow
from apps.mail_organizer.pm.task_manager import PMTaskManager
from core_platform.app.common.timezone import to_local_ist, to_local_ist_full
from core_platform.app.config import settings
from core_platform.app.entitlements.dependencies import require_action
from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info
from core_platform.app.rbac.permissions import get_web_security_context, require_app
from core_platform.app.ui.templating import build_templates
from core_platform.app.ui.ui_context import Breadcrumb, build_ui_context

router = APIRouter(
    prefix="/admin/apps/mail-organizer",
    tags=["Mail Organizer Admin"],
    dependencies=[Depends(require_app("mail_organizer"))],
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = build_templates([_TEMPLATES_DIR])
templates.env.filters["to_local_ist"] = to_local_ist
templates.env.filters["to_local_ist_full"] = to_local_ist_full
templates.env.globals["to_local_ist"] = to_local_ist
templates.env.globals["to_local_ist_full"] = to_local_ist_full

# Service instances
_db_service = MailDatabaseService()
_pm_task_manager = PMTaskManager(db_service=_db_service)
_workflow = MailOrganizerWorkflow(db_service=_db_service)


class EmailSimulationRequest(BaseModel):
    """Payload for incoming email processing simulation."""
    sender: str = Field(..., description="Sender email address")
    recipients: List[str] = Field(default_factory=list, description="Recipient email addresses")
    cc: List[str] = Field(default_factory=list, description="CC email addresses")
    subject: str = Field(..., description="Email subject line")
    body: str = Field(..., description="Email plain text or HTML body")
    thread_id: Optional[str] = Field(default=None, description="Optional thread identifier")
    thread_history: List[str] = Field(default_factory=list, description="Prior thread snippets")


class TaskApprovalRequest(BaseModel):
    """Payload for approving a PM task for sync."""
    sync_to: str = Field(default="jira", description="Target PM tool: jira or linear")


@router.get("/", response_class=HTMLResponse)
async def mail_admin_root() -> RedirectResponse:
    """Redirect root to dashboard."""
    return RedirectResponse(url="/admin/apps/mail-organizer/dashboard")


@router.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_action("mail:inbox:view"))])
async def view_dashboard(request: Request) -> HTMLResponse:
    """Render interactive Mail Organizer Dashboard."""
    tenant_id, org_name, active_tenant = resolve_effective_tenant_info(request)
    metrics = _db_service.get_triage_metrics(tenant_id=tenant_id)
    pending_tasks = _db_service.get_pending_pm_tasks(tenant_id=tenant_id)
    drafts = _db_service.get_all_drafts(tenant_id=tenant_id)
    recent_emails = _db_service.get_recent_emails(limit=50, tenant_id=tenant_id)

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=None,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name=org_name or "",
        breadcrumbs=[
            Breadcrumb(label_key="apps.mail_organizer.name", path="/admin/apps/mail-organizer/dashboard"),
            Breadcrumb(label_key="apps.mail_organizer.nav.dashboard", path="/admin/apps/mail-organizer/dashboard"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "active_tab": "dashboard",
            "tenant_id": tenant_id,
            "organization": org_name,
            "tenant_name": org_name,
            "active_tenant": active_tenant,
            "metrics": metrics,
            "pending_tasks": pending_tasks,
            "drafts": drafts,
            "recent_emails": recent_emails,
            "ui": ui_ctx,
        },
    )


@router.get("/triage", response_class=HTMLResponse, dependencies=[Depends(require_action("mail:inbox:view"))])
async def view_triage(request: Request) -> HTMLResponse:
    """Render Triage Simulator."""
    tenant_id, org_name, active_tenant = resolve_effective_tenant_info(request)
    emails = _db_service.get_recent_emails(limit=25, tenant_id=tenant_id)

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=None,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name=org_name or "",
        breadcrumbs=[
            Breadcrumb(label_key="apps.mail_organizer.name", path="/admin/apps/mail-organizer/dashboard"),
            Breadcrumb(label_key="apps.mail_organizer.nav.triage", path="/admin/apps/mail-organizer/triage"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="triage.html",
        context={
            "active_tab": "triage",
            "tenant_id": tenant_id,
            "organization": org_name,
            "tenant_name": org_name,
            "active_tenant": active_tenant,
            "emails": emails,
            "ui": ui_ctx,
        },
    )


@router.post("/api/simulate", dependencies=[Depends(require_action("mail:inbox:triage"))])
async def run_email_simulation(req: EmailSimulationRequest) -> Dict[str, Any]:
    """Execute email processing through the complete LangGraph workflow."""
    thread_id = req.thread_id or f"thread_{uuid.uuid4().hex[:8]}"
    email_id = f"msg_{uuid.uuid4().hex[:10]}"

    initial_state: MailOrganizerState = {
        "gmail_id": email_id,
        "thread_id": thread_id,
        "sender": req.sender,
        "to_recipients": req.recipients or ["user@company.com"],
        "cc_recipients": req.cc,
        "subject": req.subject,
        "body": req.body,
        "snippet": req.body[:120],
        "auto_reply_headers": {},
        "is_vip": False,
        "is_no_reply": False,
        "has_critical_subject": False,
        "category": "",
        "urgency_score": 5,
        "confidence_score": 0.0,
        "reasoning": "",
        "context_tags": [],
        "is_reply_necessary": False,
        "safety_override": False,
        "override_reason": None,
        "is_scheduling_request": False,
        "calendar_availability": None,
        "responsibility_role": "PRIMARY_ACTIONEE",
        "delegation_target": None,
        "suggested_reply": None,
        "pending_pm_tasks": [],
        "gmail_actions": [],
        "execution_mode": "shadow",
        "actions_taken": [],
        "error_message": None,
        "pipeline_trace": [],
        "correlation_id": email_id,
    }

    final_state = await _workflow.execute(initial_state)

    return {
        "success": not bool(final_state.get("error_message")),
        "email_id": email_id,
        "category": final_state.get("category"),
        "confidence": final_state.get("confidence_score"),
        "reasoning": final_state.get("reasoning"),
        "safety_override": final_state.get("safety_override"),
        "safety_divert_reason": final_state.get("override_reason"),
        "recipient_role": final_state.get("responsibility_role"),
        "draft_reply": final_state.get("suggested_reply"),
        "pm_task_extracted": len(final_state.get("pending_pm_tasks") or []) > 0,
        "pm_task_payload": final_state.get("pending_pm_tasks"),
        "planned_actions": final_state.get("actions_taken") or final_state.get("gmail_actions"),
        "audit_record_hash": final_state.get("audit_record_hash"),
        "errors": [final_state.get("error_message")] if final_state.get("error_message") else [],
    }


@router.get("/pm-queue", response_class=HTMLResponse, dependencies=[Depends(require_action("mail:pm_task:view"))])
async def view_pm_queue(request: Request) -> HTMLResponse:
    """Render Human-in-the-Loop PM Action Queue."""
    tenant_id, org_name, active_tenant = resolve_effective_tenant_info(request)
    pending_tasks = _db_service.get_pending_pm_tasks(tenant_id=tenant_id)

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=None,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name=org_name or "",
        breadcrumbs=[
            Breadcrumb(label_key="apps.mail_organizer.name", path="/admin/apps/mail-organizer/dashboard"),
            Breadcrumb(label_key="apps.mail_organizer.nav.pm_queue", path="/admin/apps/mail-organizer/pm-queue"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="pm_queue.html",
        context={
            "active_tab": "pm-queue",
            "tenant_id": tenant_id,
            "organization": org_name,
            "tenant_name": org_name,
            "active_tenant": active_tenant,
            "tasks": pending_tasks,
            "ui": ui_ctx,
        },
    )


@router.post("/api/pm-tasks/{task_id}/approve", dependencies=[Depends(require_action("mail:pm_task:approve"))])
async def approve_task_api(task_id: int, req: TaskApprovalRequest) -> Dict[str, Any]:
    """Approve and sync a staged PM task to Jira or Linear."""
    result = await _pm_task_manager.approve_and_export(task_id=str(task_id), destination=req.sync_to)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Approval failed"))
    return result


@router.post("/api/pm-tasks/{task_id}/reject", dependencies=[Depends(require_action("mail:pm_task:reject"))])
async def reject_task_api(task_id: int) -> Dict[str, Any]:
    """Reject/dismiss a staged PM task."""
    success = _db_service.reject_pm_task(task_id=task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or already processed")
    return {"success": True, "task_id": task_id, "status": "rejected"}


@router.get("/rules", response_class=HTMLResponse, dependencies=[Depends(require_action("mail:rules:view"))])
async def view_rules(request: Request) -> HTMLResponse:
    """Render VIP and Whitelist Rules Management."""
    tenant_id, org_name, active_tenant = resolve_effective_tenant_info(request)
    rules = _db_service.get_all_rules(rule_type=None)
    if tenant_id and tenant_id not in ("platform", "*"):
        rules = [r for r in rules if getattr(r, "tenant_id", "public") == tenant_id]

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=None,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name=org_name or "",
        breadcrumbs=[
            Breadcrumb(label_key="apps.mail_organizer.name", path="/admin/apps/mail-organizer/dashboard"),
            Breadcrumb(label_key="apps.mail_organizer.nav.rules", path="/admin/apps/mail-organizer/rules"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="rules.html",
        context={
            "active_tab": "rules",
            "tenant_id": tenant_id,
            "organization": org_name,
            "tenant_name": org_name,
            "active_tenant": active_tenant,
            "rules": rules,
            "ui": ui_ctx,
        },
    )


@router.get("/drafts", response_class=HTMLResponse, dependencies=[Depends(require_action("mail:inbox:view"))])
async def view_drafts(request: Request) -> HTMLResponse:
    """Render Contextual Draft Replies."""
    tenant_id, org_name, active_tenant = resolve_effective_tenant_info(request)
    drafts = _db_service.get_all_drafts(tenant_id=tenant_id)

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=None,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name=org_name or "",
        breadcrumbs=[
            Breadcrumb(label_key="apps.mail_organizer.name", path="/admin/apps/mail-organizer/dashboard"),
            Breadcrumb(label_key="apps.mail_organizer.nav.drafts", path="/admin/apps/mail-organizer/drafts"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="drafts.html",
        context={
            "active_tab": "drafts",
            "tenant_id": tenant_id,
            "organization": org_name,
            "tenant_name": org_name,
            "active_tenant": active_tenant,
            "drafts": drafts,
            "ui": ui_ctx,
        },
    )


# ── GAP-019: OAuth Accounts Management ───────────────────────────────────────

@router.get("/accounts", response_class=HTMLResponse, dependencies=[Depends(require_action("mail:inbox:view"))])
async def view_accounts(request: Request) -> HTMLResponse:
    """Display Google Account OAuth2 status and re-authorisation controls.

    Shows:
    - Current OAuth token status (valid / expired / not configured)
    - One-click re-auth button
    - Configurable sync interval

    Args:
        request: FastAPI request.

    Returns:
        Rendered accounts.html template.
    """
    tenant_id, org_name, active_tenant = resolve_effective_tenant_info(request)
    oauth_status: str = "not_configured"
    oauth_email: str = ""
    sync_interval: int = 60

    try:
        from apps.mail_organizer.connectors.gmail_connector import GmailConnector
        connector = GmailConnector()
        if hasattr(connector, "get_oauth_status"):
            status_info = connector.get_oauth_status()
            oauth_status = status_info.get("status", "unknown")
            oauth_email = status_info.get("email", "")
        else:
            # Try to probe with a lightweight credentials check.
            from pathlib import Path as _Path
            import os as _os
            token_path = _os.environ.get("GMAIL_TOKEN_PATH", "config/gmail_token.json")
            if _Path(token_path).exists():
                oauth_status = "token_present"
    except Exception:
        oauth_status = "connector_error"

    ui_ctx = build_ui_context(
        locale=str(getattr(request.state, "locale", settings.UI_DEFAULT_LOCALE)),
        ctx=None,
        allowed_apps=["temperature_marker", "mail_organizer"],
        tenant_name=org_name or "",
        breadcrumbs=[
            Breadcrumb(label_key="apps.mail_organizer.name", path="/admin/apps/mail-organizer/dashboard"),
            Breadcrumb(label_key="apps.mail_organizer.nav.accounts", path="/admin/apps/mail-organizer/accounts"),
        ],
    )

    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "active_tab": "accounts",
            "tenant_id": tenant_id,
            "organization": org_name,
            "tenant_name": org_name,
            "active_tenant": active_tenant,
            "oauth_status": oauth_status,
            "oauth_email": oauth_email,
            "sync_interval": sync_interval,
            "ui": ui_ctx,
        },
    )


@router.get("/accounts/reauth", dependencies=[Depends(require_action("mail:account:connect"))])
async def initiate_reauth(request: Request) -> RedirectResponse:
    """Initiate Google OAuth2 re-authorisation flow by redirecting to Google's consent screen."""
    try:
        from apps.mail_organizer.connectors.gmail_connector import GmailConnector
        connector = GmailConnector()
        base_url = str(request.base_url).rstrip("/")
        callback_uri = f"{base_url}/admin/apps/mail-organizer/accounts/callback"
        auth_url = connector.initiate_oauth_flow(redirect_uri=callback_uri)
        if auth_url:
            return RedirectResponse(url=auth_url)
    except Exception:
        pass

    return RedirectResponse(url="/admin/apps/mail-organizer/accounts?reauth=failed")


@router.get("/accounts/callback", dependencies=[Depends(require_action("mail:account:connect"))])
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    """Handle OAuth2 redirect callback from Google and persist encrypted tokens."""
    if error or not code:
        err_msg = error or "missing_authorization_code"
        return RedirectResponse(url=f"/admin/apps/mail-organizer/accounts?error={err_msg}")

    import json
    import urllib.parse
    import urllib.request
    from datetime import datetime, timedelta, timezone
    from apps.mail_organizer.connectors.auth_manager import GoogleAuthManager, find_client_credentials

    creds = find_client_credentials()
    if not creds:
        return RedirectResponse(url="/admin/apps/mail-organizer/accounts?error=credentials_not_found")

    client_id = creds.get("client_id")
    client_secret = creds.get("client_secret")
    redirect_uri = str(request.url).split("?")[0]

    token_params = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(token_params).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            token_response: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))

        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        expires_in = token_response.get("expires_in", 3600)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

        token_payload: Dict[str, Any] = {
            "token": access_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": [
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/calendar.readonly",
            ],
            "expiry": expiry.isoformat(),
        }
        GoogleAuthManager().encrypt_and_save_token(token_payload)
        return RedirectResponse(url="/admin/apps/mail-organizer/accounts?reauth=success")
    except Exception:
        return RedirectResponse(url="/admin/apps/mail-organizer/accounts?error=token_exchange_failed")

