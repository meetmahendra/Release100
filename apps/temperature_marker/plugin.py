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
Application Plugin Implementation Manifest.

Adheres strictly to Plan 03 v1.3 and Core Platform Plugin Architecture.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.downstream.in_house_rest import InHouseRESTConnector
from apps.temperature_marker.downstream.outbox_manager import OutboxManager
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.telemetry.audit_engine import AuditEngine
from core_platform.app.ui.contracts import NavItem, StatusInfo


class TemperatureMarkerConfig(BaseModel):
    """Configuration settings for Industrial Temperature & Attendance Marker."""

    organization_name: str = Field(default="Apex Cold-Chain Logistics Ltd")
    default_machine_type: str = Field(default="Industrial Cold-Storage Chiller Unit")
    safe_min_temp: float = Field(default=2.0)
    safe_max_temp: float = Field(default=4.0)
    critical_alert_temp: float = Field(default=7.0)
    default_geofence_radius_meters: float = Field(default=50.0)
    indoor_tolerance_radius_meters: float = Field(default=100.0)
    location_verification_method: str = Field(default="web_geolocation")
    downstream_target_type: str = Field(default="in_house_rest")
    downstream_endpoint_url: Optional[str] = None
    require_admin_approval_for_onboarding: bool = True


class TemperatureMarkerApplication(BaseApplication):
    """Plugin cartridge instance representing the Temperature Marker application."""

    app_id: str = "temperature_marker"
    name: str = "Apex Industrial Temperature & Attendance Marker"
    version: str = "1.3.0"
    description: str = "Factory floor attendance and chiller temperature recording via selfie photo and OCR."
    config_schema = TemperatureMarkerConfig
    required_roles: List[str] = ["operator", "supervisor", "admin"]
    supported_channels: List[str] = ["whatsapp", "web_kiosk", "mcp_agent"]
    dashboard_url: str = "/admin/apps/temperature-marker/fleet"
    has_poller: bool = False

    def __init__(
        self,
        engine: Optional[Any] = None,
        db_url: Optional[str] = None,
    ) -> None:
        """Initialize domain cartridge and wire dependencies.

        Args:
            engine: Optional shared SQLAlchemy Engine (Core-Facilitated mode).
            db_url: Optional explicit DB connection URL override (standalone test mode).
        """
        self.db_service = DatabaseService(engine=engine, db_url=db_url)
        self.kg_service = KnowledgeGraphService()
        self.audit_engine = AuditEngine.get_instance()
        from apps.temperature_marker.downstream.base_connector import create_downstream_connector
        self.downstream_connector = create_downstream_connector(
            target_type="in_house_rest",
        )
        self.outbox_manager = OutboxManager(
            db_service=self.db_service,
            connector=self.downstream_connector,
        )
        self.workflow = TemperatureMarkerWorkflow(
            db_service=self.db_service,
            kg_service=self.kg_service,
            audit_engine=self.audit_engine,
        )

    def on_bind_engine(self, engine: Any) -> None:
        """Dynamically bind or update the database engine (Paradigm A)."""
        if engine is not None and hasattr(self, "db_service") and self.db_service is not None:
            self.db_service.bind_engine(engine)

    keywords: List[str] = [
        "attendance", "check-in", "checkin", "punch", "kiosk", "duty",
        "chiller", "temperature", "temp", "kiosk", "selfie", "photo", "face",
        "hello", "hi", "namaste", "register", "status", "start", "help",
        "station", "cups", "supply", "fleet",
    ]


    def get_workflow(self) -> TemperatureMarkerWorkflow:
        """Return the workflow executor for processing inbound envelopes."""
        return self.workflow

    def get_ui_router(self) -> Any:
        """Return the FastAPI router for Admin Web Shell and Stepper Wizard."""
        from apps.temperature_marker.ui.routes import router
        return router

    def get_locale_dir(self) -> Optional[Path]:
        """Return the directory holding this cartridge's locales."""
        d = Path(__file__).parent / "locales"
        return d if d.is_dir() else None

    def get_ui_nav(self) -> List[NavItem]:
        """Return sidebar navigation items for Temperature Marker."""
        return [
            NavItem(label_key="apps.temperature_marker.nav.monitoring", path="/admin/apps/temperature-marker/monitoring", group_key="apps.temperature_marker.name"),
            NavItem(label_key="apps.temperature_marker.nav.fleet", path="/admin/apps/temperature-marker/fleet", group_key="apps.temperature_marker.name"),
            NavItem(label_key="apps.temperature_marker.nav.wizard", path="/admin/apps/temperature-marker/wizard", group_key="apps.temperature_marker.name"),
            NavItem(label_key="apps.temperature_marker.nav.approvals", path="/admin/apps/temperature-marker/approvals", group_key="apps.temperature_marker.name"),
        ]

    def get_ui_statuses(self) -> Dict[str, StatusInfo]:
        """Return status display mappings for Temperature Marker."""
        return {
            "TEMP_NORMAL": StatusInfo(code="TEMP_NORMAL", tone="success", icon="check", label_key="apps.temperature_marker.status.normal"),
            "TEMP_WARNING": StatusInfo(code="TEMP_WARNING", tone="warning", icon="alert", label_key="apps.temperature_marker.status.warning"),
            "TEMP_CRITICAL": StatusInfo(code="TEMP_CRITICAL", tone="danger", icon="alert", label_key="apps.temperature_marker.status.critical"),
        }

    def get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Return the domain tools exported to Core MCP Server."""
        from apps.temperature_marker.downstream.mcp_tools import get_temperature_marker_mcp_tools
        return get_temperature_marker_mcp_tools(db_service=self.db_service, kg_service=self.kg_service)

    def get_metadata(self) -> Any:
        """Return SQLAlchemy MetaData so Alembic can discover TM tables dynamically."""
        from apps.temperature_marker.database.models import Base
        return Base.metadata

    def get_outbox_transmitter(self) -> Any:
        """Return the async sync callback for the platform OutboxSynchronizer."""
        async def _transmitter(target: str, payload: Any) -> Any:
            from apps.temperature_marker.downstream.base_connector import create_downstream_connector
            connector = create_downstream_connector(target_type=target)
            return await connector.dispatch(payload)
        return _transmitter

    def get_pending_outbox_count(self) -> int:
        """Return pending unsynced outbox record count for platform /health."""
        try:
            return len(self.db_service.get_pending_outbox_items(limit=100))
        except Exception:
            return 0

    def has_active_session(self, sender_id: str) -> bool:
        """Check if manager or operator has an active interactive triage session in queue."""
        try:
            from apps.temperature_marker.services.internal_dispatch import ManagerTriageSessionManager
            mgr = ManagerTriageSessionManager.get_instance()
            return mgr.get_active_message_id(sender_id) is not None
        except Exception:
            return False

    def get_whatsapp_handler(self) -> Any:
        """Return the domain-specific WhatsApp message handler for Temperature Marker."""
        from apps.temperature_marker.services.whatsapp_handler import TemperatureMarkerWhatsAppHandler
        return TemperatureMarkerWhatsAppHandler(
            db_service=self.db_service,
            kg_service=self.kg_service,
            workflow=self.workflow,
        )

    def get_convenience_routes(self) -> List[Any]:
        """Return /loc shortcut routes for registration at the platform root."""
        from apps.temperature_marker.ui.routes import view_verify_location, verify_location_api
        return [
            ("GET", "/loc", view_verify_location),
            ("POST", "/api/verify-location", verify_location_api),
        ]

    def get_health_status(self) -> Dict[str, Any]:
        """Return enriched health dict including live DB connectivity check."""
        base = super().get_health_status()
        try:
            db_ok = self.db_service.health_check() if hasattr(self.db_service, "health_check") else True
            base["db_status"] = "ok" if db_ok else "degraded"
        except Exception:
            base["db_status"] = "error"
        return base

    async def resolve_or_generate_employee_code(
        self,
        phone_number: str,
        full_name: str,
        explicit_code: Optional[str] = None,
    ) -> str:
        """Resolve or generate employee code for enrollment."""
        from apps.temperature_marker.downstream.hr_connector import resolve_or_generate_employee_code
        return await resolve_or_generate_employee_code(
            phone_number=phone_number,
            full_name=full_name,
            explicit_code=explicit_code,
        )


TemperatureMarkerPlugin = TemperatureMarkerApplication


