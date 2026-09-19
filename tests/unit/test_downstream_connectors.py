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
Unit tests for all downstream connectors (Google Sheets, Direct Database, ERP).
Adheres strictly to GEES v1.0.
"""

from typing import Any, Dict
import pytest

from apps.temperature_marker.downstream.base_connector import (
    BaseDownstreamConnector,
    create_downstream_connector,
)
from apps.temperature_marker.downstream.direct_database import DirectDatabaseConnector
from apps.temperature_marker.downstream.erp_connector import ERPGatewayConnector
from apps.temperature_marker.downstream.google_sheets import GoogleSheetsConnector


@pytest.fixture
def sample_record() -> Dict[str, Any]:
    return {
        "timestamp_utc": "2026-09-16T06:00:00Z",
        "kiosk_id": "KIOSK-01",
        "operator_emp_code": "EMP-101",
        "operator_name": "Rajesh Kumar",
        "operator_status": "ACTIVE",
        "chiller_temp_c": 3.8,
        "haccp_status": "SAFE_RANGE",
        "face_confidence": 0.96,
        "audit_record_hash": "a1b2c3d4e5f6",
    }


@pytest.mark.anyio
async def test_google_sheets_connector_mock(sample_record: Dict[str, Any]) -> None:
    """Test GoogleSheetsConnector in mock mode."""
    connector = GoogleSheetsConnector(spreadsheet_id="", credentials_path="")
    assert connector._is_mock is True

    success, msg = await connector.dispatch(sample_record)
    assert success is True
    assert msg == "mock_ok"

    health = await connector.health_check()
    assert health["connector"] == "google_sheets"
    assert health["mock_mode"] is True

    row = GoogleSheetsConnector._record_to_row(sample_record)
    assert len(row) == 9
    assert row[2] == "EMP-101"


@pytest.mark.anyio
async def test_direct_database_connector(sample_record: Dict[str, Any]) -> None:
    """Test DirectDatabaseConnector in mock/memory mode."""
    connector = DirectDatabaseConnector(connection_string="sqlite:///:memory:", mock_mode=True)
    assert connector.mock_mode is True

    success, msg = await connector.dispatch(sample_record)
    assert success is True
    assert "simulated" in msg.lower() or "mock" in msg.lower()


@pytest.mark.anyio
async def test_erp_connector(sample_record: Dict[str, Any]) -> None:
    """Test ERPGatewayConnector across various erp types."""
    for erp in ("odoo", "sap", "zoho"):
        conn = ERPGatewayConnector(erp_type=erp, mock_mode=True)
        assert conn.mock_mode is True

        success, msg = await conn.dispatch(sample_record)
        assert success is True
        assert erp in msg.lower() or "mock" in msg.lower() or "simulated" in msg.lower()


def test_create_downstream_connector_factory() -> None:
    """Test factory resolution for all connector types."""
    c_inhouse = create_downstream_connector("in_house_rest")
    assert isinstance(c_inhouse, BaseDownstreamConnector)

    c_db = create_downstream_connector("direct_database")
    assert isinstance(c_db, DirectDatabaseConnector)

    c_erp = create_downstream_connector("erp_odoo")
    assert isinstance(c_erp, ERPGatewayConnector)

    c_sheets = create_downstream_connector("google_sheets")
    assert isinstance(c_sheets, GoogleSheetsConnector)
