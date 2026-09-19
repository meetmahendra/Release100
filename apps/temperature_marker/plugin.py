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

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.downstream.in_house_rest import InHouseRESTConnector
from apps.temperature_marker.downstream.outbox_manager import OutboxManager
from apps.temperature_marker.graph.state_graph import TemperatureMarkerWorkflow
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.telemetry.audit_engine import AuditEngine


class TemperatureMarkerConfig(BaseModel):
    """Configuration settings for CaneBot Temperature & Attendance Marker."""

    organization_name: str = Field(default="Canectar Foods Pvt Ltd")
    default_machine_type: str = Field(default="CaneBot Sugarcane Crushing Machine")
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
    name: str = "Canectar CaneBot Temperature & Attendance Marker"
    version: str = "1.3.0"
    config_schema = TemperatureMarkerConfig
    required_roles: List[str] = ["operator", "supervisor", "admin"]
    supported_channels: List[str] = ["whatsapp", "web_kiosk", "mcp_agent"]

    def __init__(self, db_url: str = "sqlite:///logs/temperature_marker.db") -> None:
        """Initialize domain cartridge and wire dependencies."""
        self.db_service = DatabaseService(db_url=db_url)
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

    def get_workflow(self) -> TemperatureMarkerWorkflow:
        """Return the workflow executor for processing inbound envelopes."""
        return self.workflow

    def get_ui_router(self) -> Any:
        """Return the FastAPI router for Admin Web Shell and Stepper Wizard."""
        from apps.temperature_marker.ui.routes import router
        return router

    def get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Return the domain tools exported to Core MCP Server."""
        from apps.temperature_marker.downstream.mcp_tools import get_temperature_marker_mcp_tools
        return get_temperature_marker_mcp_tools(db_service=self.db_service, kg_service=self.kg_service)

