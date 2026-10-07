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
Model Context Protocol (MCP) Tool Suite for Industrial Temperature & Attendance Marker.

Adheres strictly to Plan 03 v1.3 Section 7.
Exposes standardized MCP tools for external AI agents (Cursor, Claude Desktop, local LLMs):
- temperature_get_latest_reading: Query latest chiller reading & HACCP compliance.
- temperature_check_kiosk_health: Verify kiosk coordinates, safe limits, and online status.
- temperature_list_fleet_status: Full fleet overview of all KioskNode kiosks.
- temperature_list_pending_onboarding_approvals: Fetch pending operator enrollments.
- temperature_approve_operator: Approve operator onboarding for duty.
"""

from typing import Any, Callable, Dict, List, Optional

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService


class TemperatureMarkerMCPTools:
    """Tool provider class exporting KioskNode domain tools to the core platform MCP server."""

    def __init__(
        self,
        db_service: Optional[DatabaseService] = None,
        kg_service: Optional[KnowledgeGraphService] = None,
    ) -> None:
        """Initialize MCP tool handler with domain dependencies."""
        self.db_service = db_service or DatabaseService.get_instance()
        self.kg_service = kg_service or KnowledgeGraphService()

    async def temperature_get_latest_reading(
        self,
        kiosk_id: Optional[str] = None,
        emp_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query latest verified chiller temperature and attendance record.

        Args:
            kiosk_id: KioskNode kiosk identifier (e.g. 'NODE-PUNE-04').
            emp_code: Unique employee code (e.g. 'EMP-1042').

        Returns:
            Dictionary containing latest verified reading and compliance metrics.
        """
        records = self.db_service.get_recent_attendance(limit=20)
        filtered = records
        if kiosk_id:
            filtered = [r for r in filtered if r.kiosk_id == kiosk_id]
        if emp_code:
            filtered = [r for r in filtered if r.emp_code == emp_code]

        if not filtered:
            return {
                "found": False,
                "message": f"No attendance/temperature records found for kiosk='{kiosk_id}', emp='{emp_code}'",
            }

        latest = filtered[0]
        ts = getattr(latest, "checkin_time_utc", None) or getattr(latest, "created_at_utc", None) or getattr(latest, "created_at", None)
        return {
            "found": True,
            "correlation_id": latest.correlation_id,
            "kiosk_id": latest.kiosk_id,
            "emp_code": latest.emp_code,
            "chiller_temp_c": latest.chiller_temp_c,
            "haccp_compliant": latest.haccp_compliant,
            "haccp_status": latest.haccp_status,
            "face_confidence": latest.face_confidence,
            "geofence_verified": latest.geofence_verified,
            "timestamp": ts.isoformat() if ts else None,
        }

    async def temperature_check_kiosk_health(self, kiosk_id: str) -> Dict[str, Any]:
        """Inspect KioskNode kiosk configuration, HACCP limits, and assigned operators.

        Args:
            kiosk_id: KioskNode kiosk identifier (e.g. 'NODE-PUNE-04').

        Returns:
            Kiosk health metrics, permissible temperature bounds, and GPS coordinates.
        """
        kiosk = self.kg_service.get_kiosk_details(kiosk_id)
        if not kiosk:
            return {"found": False, "message": f"Kiosk '{kiosk_id}' not registered in Knowledge Graph."}

        haccp = self.kg_service.get_haccp_limits(kiosk_id)
        coords = self.kg_service.get_kiosk_coordinates(kiosk_id)

        return {
            "found": True,
            "kiosk_id": kiosk.get("kiosk_id", kiosk_id),
            "name": kiosk.get("name"),
            "location_name": kiosk.get("city", kiosk.get("name")),
            "machine_type": kiosk.get("machine_model", "ChillerNode-Pro"),
            "status": "ACTIVE" if kiosk.get("is_active", True) else "INACTIVE",
            "haccp_limits": {
                "min_safe_temp": haccp.min_safe_temp,
                "max_safe_temp": haccp.max_safe_temp,
                "critical_alert_temp": haccp.critical_alert_temp,
            },
            "coordinates": {
                "latitude": coords[0] if coords else None,
                "longitude": coords[1] if coords else None,
                "radius_meters": coords[2] if coords else None,
            },
        }

    async def temperature_list_fleet_status(self) -> List[Dict[str, Any]]:
        """List all active Industrial cold-chain kiosks across fleet locations."""
        return self.kg_service.list_all_kiosks()

    async def temperature_list_pending_onboarding_approvals(self) -> List[Dict[str, Any]]:
        """Fetch all operator self-onboarding profiles awaiting Admin approval."""
        pending = self.db_service.get_pending_approvals()
        return [
            {
                "emp_code": emp.emp_code,
                "full_name": emp.full_name,
                "phone_number": emp.phone_number,
                "assigned_kiosk_id": emp.assigned_kiosk_id,
                "status": emp.status,
            }
            for emp in pending
        ]

    async def temperature_approve_operator(self, emp_code: str) -> Dict[str, Any]:
        """Approve a pending operator self-registration for duty.

        Args:
            emp_code: Unique employee code (e.g. 'EMP-1042').

        Returns:
            Status confirmation dictionary.
        """
        success = self.db_service.approve_employee(emp_code)
        return {
            "emp_code": emp_code,
            "approved": success,
            "message": f"Operator '{emp_code}' approved for KioskNode duty." if success else f"Operator '{emp_code}' not found.",
        }


def get_temperature_marker_mcp_tools(
    db_service: Optional[DatabaseService] = None,
    kg_service: Optional[KnowledgeGraphService] = None,
) -> List[Dict[str, Any]]:
    """Export standardized MCP tool definitions with schemas and bound async handlers."""
    provider = TemperatureMarkerMCPTools(db_service=db_service, kg_service=kg_service)

    return [
        {
            "name": "temperature_get_latest_reading",
            "description": "Query latest verified KioskNode chiller temperature and attendance record.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kiosk_id": {"type": "string", "description": "Optional KioskNode machine ID (e.g. 'NODE-PUNE-04')"},
                    "emp_code": {"type": "string", "description": "Optional employee code (e.g. 'EMP-1042')"},
                },
            },
            "handler": provider.temperature_get_latest_reading,
        },
        {
            "name": "temperature_check_kiosk_health",
            "description": "Inspect KioskNode kiosk configuration, HACCP limits, and assigned operators.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kiosk_id": {"type": "string", "description": "KioskNode kiosk ID (e.g. 'NODE-PUNE-04')"},
                },
                "required": ["kiosk_id"],
            },
            "handler": provider.temperature_check_kiosk_health,
        },
        {
            "name": "temperature_list_fleet_status",
            "description": "List all active Industrial cold-chain kiosks across fleet locations.",
            "parameters": {"type": "object", "properties": {}},
            "handler": provider.temperature_list_fleet_status,
        },
        {
            "name": "temperature_list_pending_onboarding_approvals",
            "description": "Fetch all operator self-onboarding profiles awaiting Admin approval.",
            "parameters": {"type": "object", "properties": {}},
            "handler": provider.temperature_list_pending_onboarding_approvals,
        },
        {
            "name": "temperature_approve_operator",
            "description": "Approve a pending operator self-registration for duty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "emp_code": {"type": "string", "description": "Employee code to approve (e.g. 'EMP-1042')"},
                },
                "required": ["emp_code"],
            },
            "handler": provider.temperature_approve_operator,
        },
    ]
