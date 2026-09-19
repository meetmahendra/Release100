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

from typing import Any, Dict, List, Optional
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
        default_factory=lambda: ["ceo@canectar.com", "board@canectar.com", "rajesh.pawar@canectar.com"]
    )
    whitelisted_domains: List[str] = Field(
        default_factory=lambda: ["canectar.com", "partner.canectar.com"]
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
    config_schema = MailOrganizerConfig
    required_roles: List[str] = ["manager", "executive", "admin"]
    supported_channels: List[str] = ["email", "whatsapp", "web_kiosk", "mcp_agent"]

    def __init__(self, db_url: str = "sqlite:///logs/mail_organizer.db") -> None:
        """Initialize domain cartridge and assemble dependencies."""
        self.db_service = MailDatabaseService(db_url=db_url)
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
