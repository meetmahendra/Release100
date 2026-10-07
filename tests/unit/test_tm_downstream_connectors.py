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

"""GEES v1.0 Unit Tests for Temperature Marker Downstream Connectors and MCP Tools."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from apps.temperature_marker.downstream.hr_connector import resolve_or_generate_employee_code
from apps.temperature_marker.downstream.google_sheets import GoogleSheetsConnector
from apps.temperature_marker.downstream.mcp_tools import (
    TemperatureMarkerMCPTools,
    get_temperature_marker_mcp_tools,
)
from apps.temperature_marker.downstream.direct_database import DirectDatabaseConnector
from apps.temperature_marker.downstream.erp_connector import ERPGatewayConnector
from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService


@pytest.fixture
def db_service(tmp_path: Path) -> DatabaseService:
    """Create isolated SQLite database service instance."""
    db_file = tmp_path / "test_marker.db"
    return DatabaseService(db_url=f"sqlite:///{db_file}")


# ============================================================================
# 1. HR Connector Tests
# ============================================================================

@pytest.mark.asyncio
async def test_hr_connector_explicit_and_fallback(db_service: DatabaseService) -> None:
    """Test HR connector explicit code return and fallback sequential generation."""
    # 1. Explicit code provided
    code = await resolve_or_generate_employee_code(
        phone_number="+919876543210",
        full_name="Rajesh Kumar",
        explicit_code="EMP-9999",
    )
    assert code == "EMP-9999"

    # 2. Sequential generation fallback
    with patch("apps.temperature_marker.downstream.hr_connector.DatabaseService.get_instance", return_value=db_service):
        gen_code = await resolve_or_generate_employee_code(
            phone_number="+919876543210",
            full_name="Rajesh Kumar",
        )
        assert gen_code.startswith("EMP-")


@pytest.mark.asyncio
async def test_hr_connector_external_service_mock(db_service: DatabaseService) -> None:
    """Test external HR service HTTP resolution when configured."""
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"employee_id": "EMP-EXT-456"}

    with patch("apps.temperature_marker.downstream.hr_connector.getattr", return_value="https://hr.example.com"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        code = await resolve_or_generate_employee_code(
            phone_number="+919876543210",
            full_name="Suresh Patil",
        )
        assert code == "EMP-EXT-456"


# ============================================================================
# 2. Google Sheets Connector Tests
# ============================================================================

@pytest.mark.asyncio
async def test_google_sheets_mock_mode() -> None:
    """Test Google Sheets connector in mock mode without credentials."""
    connector = GoogleSheetsConnector(spreadsheet_id="", credentials_path="")
    assert connector._is_mock is True

    record = {
        "emp_code": "EMP-1001",
        "full_name": "Test Operator",
        "kiosk_id": "NODE-PUNE-04",
        "chiller_temp_c": 3.5,
        "haccp_status": "COMPLIANT",
        "checkin_time_utc": "2026-09-30T04:00:00Z",
    }

    ok, msg = await connector.send_attendance_record(record)
    assert ok is True
    assert "mock" in msg.lower()

    health = await connector.health_check()
    assert health["status"] in ("ok", "mock", "healthy", "configured", "mock_unconfigured")


# ============================================================================
# 3. Direct Database & ERP Connector Tests
# ============================================================================

@pytest.mark.asyncio
async def test_direct_database_and_erp_connectors() -> None:
    """Test DirectDatabaseConnector and ERPConnector dispatch logic."""
    db_conn = DirectDatabaseConnector()
    erp_conn = ERPGatewayConnector()

    record = {
        "emp_code": "EMP-1001",
        "kiosk_id": "NODE-PUNE-04",
        "chiller_temp_c": 4.0,
        "haccp_compliant": True,
    }

    ok_db, msg_db = await db_conn.dispatch(record)
    assert isinstance(ok_db, bool)

    ok_erp, msg_erp = await erp_conn.dispatch(record)
    assert isinstance(ok_erp, bool)


# ============================================================================
# 4. Temperature Marker MCP Tools Tests
# ============================================================================

@pytest.mark.asyncio
async def test_temperature_marker_mcp_tools(db_service: DatabaseService) -> None:
    """Test MCP tool queries for KioskNode fleet, health, and approvals."""
    kg_service = KnowledgeGraphService()
    tools = TemperatureMarkerMCPTools(db_service=db_service, kg_service=kg_service)

    # 1. Latest reading query (empty)
    reading_res = await tools.temperature_get_latest_reading(kiosk_id="NODE-NONEXISTENT")
    assert reading_res["found"] is False

    # 2. Check kiosk health for valid kiosk
    health_res = await tools.temperature_check_kiosk_health("NODE-PUNE-04")
    assert health_res["found"] is True
    assert health_res["kiosk_id"] == "NODE-PUNE-04"

    # 3. List fleet status
    fleet_res = await tools.temperature_list_fleet_status()
    assert isinstance(fleet_res, list)
    assert len(fleet_res) > 0

    # 4. Pending onboarding approvals
    pending_res = await tools.temperature_list_pending_onboarding_approvals()
    assert isinstance(pending_res, list) or "pending_operators" in pending_res

    # 5. Approve operator tool call
    approve_res = await tools.temperature_approve_operator("EMP-NONEXISTENT")
    assert isinstance(approve_res, dict)

    # 6. Tool exporter registration list
    exported_tools = get_temperature_marker_mcp_tools(db_service, kg_service)
    assert len(exported_tools) >= 5
