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
Mail Organizer Application Cartridge Plugin.

Adheres strictly to Plan 04 v1.0 Section 2 and Core Platform Plugin Architecture.
"""

from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter
from pydantic import BaseModel, Field

from apps.mail_organizer.connectors.calendar_connector import GoogleCalendarConnector
from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.state_graph import MailOrganizerWorkflow
from apps.mail_organizer.mcp.tools import get_mail_organizer_mcp_tools
from apps.mail_organizer.pm.task_manager import PMTaskManager
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.telemetry.audit_engine import AuditEngine


class MailOrganizerConfig(BaseModel):
    """Configuration settings for Mail & Calendar Organizer."""

    sync_interval_seconds: int = Field(default=60)
    max_emails_per_batch: int = Field(default=25)
    auto_archive_promotions: bool = Field(default=True)
    confidence_review_threshold: float = Field(default=0.85)
    urgency_high_threshold: int = Field(default=8)
    vip_senders: List[str] = Field(
        default_factory=lambda: ["ceo@apex.com", "board@apex.com", "rajesh.pawar@apex.com"]
    )
    whitelisted_domains: List[str] = Field(
        default_factory=lambda: ["apex.com", "partner.apex.com"]
    )
    critical_keywords: List[str] = Field(
        default_factory=lambda: ["urgent", "escalation", "critical", "sev1", "outage", "hazard", "immediate"]
    )
    execution_mode: str = Field(default="assistive")  # "shadow" | "assistive" | "autonomous"
    pm_export_adapter: str = Field(default="sqlite_queue")  # "sqlite_queue" | "jira" | "linear"


class MailOrganizerApplication(BaseApplication):
    """Plugin cartridge instance representing the AI Mail & Calendar Organizer application."""

    app_id: str = "mail_organizer"
    name: str = "AI Email & Calendar Organizer"
    version: str = "1.0.0"
    description: str = "Email triage, meeting scheduling, and PM task extraction for executives."
    config_schema = MailOrganizerConfig
    required_roles: List[str] = ["manager", "executive", "admin"]
    supported_channels: List[str] = ["email", "whatsapp", "web_kiosk", "mcp_agent"]
    dashboard_url: str = "/admin/apps/mail-organizer/dashboard"
    has_poller: bool = True

    def __init__(
        self,
        engine: Optional[Any] = None,
        db_url: Optional[str] = None,
    ) -> None:
        """Initialize domain cartridge and assemble dependencies.

        Args:
            engine: Optional shared SQLAlchemy Engine (Core-Facilitated mode).
            db_url: Optional explicit DB connection URL override (standalone test mode).
        """
        self.db_service = MailDatabaseService(engine=engine, db_url=db_url)
        self.gmail_connector = GmailConnector()
        self.calendar_connector = GoogleCalendarConnector()
        self.pm_manager = PMTaskManager(db_service=self.db_service)
        self.audit_engine = AuditEngine.get_instance()

        self.workflow = MailOrganizerWorkflow(
            db_service=self.db_service,
            gmail_connector=self.gmail_connector,
            calendar_connector=self.calendar_connector,
            audit_engine=self.audit_engine,
        )

    def on_bind_engine(self, engine: Any) -> None:
        """Dynamically bind or update the database engine (Paradigm A)."""
        if engine is not None and hasattr(self, "db_service") and self.db_service is not None:
            self.db_service.bind_engine(engine)

    keywords: List[str] = [
        "mail", "email", "inbox", "draft", "reply", "forward",
        "meeting", "schedule", "calendar", "task", "jira", "linear",
        "approve", "reject", "summary", "digest",
    ]


    def get_workflow(self) -> MailOrganizerWorkflow:
        """Return the compiled LangGraph workflow orchestrator."""
        return self.workflow

    def get_ui_router(self) -> APIRouter:
        """Return the FastAPI router for Admin Web Shell."""
        from apps.mail_organizer.ui.routes import router
        return router

    def get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Return the domain tools exported to Core MCP Server."""
        return get_mail_organizer_mcp_tools()

    def get_metadata(self) -> Any:
        """Return SQLAlchemy MetaData so Alembic can discover mail organizer tables dynamically."""
        from apps.mail_organizer.database.models import Base
        return Base.metadata

    def get_whatsapp_handler(self) -> Any:
        """Return the domain-specific WhatsApp message handler for Mail Organizer."""
        from apps.mail_organizer.services.whatsapp_handler import MailOrganizerWhatsAppHandler
        return MailOrganizerWhatsAppHandler(
            db_service=self.db_service,
            pm_manager=self.pm_manager,
            workflow=self.workflow,
        )

    def get_convenience_routes(self) -> List[Any]:
        """Return /mail redirect shortcut for registration at the platform root."""
        from fastapi.responses import RedirectResponse

        async def mail_redirect() -> RedirectResponse:
            """Redirect shortcut /mail to mail organizer dashboard."""
            return RedirectResponse(url="/admin/apps/mail-organizer/dashboard")

        return [
            ("GET", "/mail", mail_redirect),
            ("GET", "/mail/", mail_redirect),
        ]

    def get_poller_status(self) -> Optional[str]:
        """Return the running status of the background email poller."""
        try:
            from apps.mail_organizer.services.poller_manager import MailPollerManager
            mgr = MailPollerManager.get_instance()
            return "RUNNING" if mgr.is_running() else "STOPPED"
        except Exception:
            return "UNAVAILABLE"

    def toggle_poller(self) -> Tuple[bool, str]:
        """Toggle the background email poller on/off."""
        from apps.mail_organizer.services.poller_manager import MailPollerManager
        mgr = MailPollerManager.get_instance()
        if mgr.is_running():
            mgr.stop()
            return False, "Mail Poller was stopped cleanly (0 zombies)."
        else:
            mgr.start()
            return True, "Mail Poller is now active."

    def get_outbox_transmitter(self) -> Any:
        """Return transmitter callable to retry pending or failed Gmail/PM tasks."""
        async def _transmitter(target: str, payload: Any) -> Tuple[bool, str]:
            if target == "gmail_api":
                action = payload.get("action")
                if action == "apply_labels":
                    gmail_id = payload.get("gmail_id")
                    add_labels = payload.get("add_labels", [])
                    rem_labels = payload.get("remove_labels", [])
                    res_labels: bool = await self.gmail_connector.apply_labels(
                        gmail_id=gmail_id,
                        add_labels=add_labels,
                        remove_labels=rem_labels,
                    )
                    return bool(res_labels), "Gmail labels applied"
                elif action == "create_draft":
                    res_draft: Dict[str, Any] = await self.gmail_connector.create_draft(
                        thread_id=payload.get("thread_id", ""),
                        recipient=payload.get("recipient", ""),
                        subject=payload.get("subject", ""),
                        body=payload.get("body", ""),
                    )
                    return bool(res_draft.get("draft_id")), f"Draft created: {res_draft.get('draft_id')}"
                else:
                    return True, f"Gmail action '{action or 'generic'}' acknowledged"
            elif target in ("jira", "linear", "pm_export"):
                task_id = payload.get("task_id")
                dest = payload.get("destination") or target
                if task_id:
                    res_pm: Dict[str, Any] = await self.pm_manager.approve_and_export(task_id, destination=dest)
                    return bool(res_pm.get("success", False)), f"Exported task {task_id} to {dest}"
                return True, f"PM action on {dest} acknowledged"
            return False, f"Unknown mail target: {target}"
        return _transmitter

    def get_pending_outbox_count(self) -> int:
        """Return pending unsynced outbox record count for platform /health."""
        try:
            from core_platform.app.outbox.queue import PlatformOutboxQueue
            queue = PlatformOutboxQueue()
            pending = queue.get_pending(app_id="mail_organizer", limit=100)
            return len(pending)
        except Exception:
            return 0


MailOrganizerPlugin = MailOrganizerApplication

