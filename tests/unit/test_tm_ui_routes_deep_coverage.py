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

"""GEES v1.0 Deep Coverage Tests for Temperature Marker Admin Web Shell and APIs."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from starlette.testclient import TestClient

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.main import app

client = TestClient(app)
token = create_jwt_token("admin", ["admin"], ["all", "temperature_marker"])
client.cookies.set("admin_token", token)


def test_member_lifecycle_and_approval_apis() -> None:
    """Test full CRUD lifecycle for operator members and approval workflow via Admin API."""
    db = DatabaseService.get_instance()

    # 1. Create member via POST /api/members
    create_payload = {
        "full_name": "Deep Coverage Operator",
        "phone_number": "+919988112233",
        "assigned_kiosk_id": "CANEBOT-PUNE-04",
        "emp_code": "EMP-TEST-UI-100",
        "reporting_manager_emp_code": "MGR-01",
    }
    resp = client.post("/admin/apps/temperature-marker/api/members", json=create_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["emp_code"] == "EMP-TEST-UI-100"

    # 2. List members via GET /api/members
    resp_list = client.get("/admin/apps/temperature-marker/api/members")
    assert resp_list.status_code == 200
    members = resp_list.json()
    assert isinstance(members, list)
    assert any(m["emp_code"] == "EMP-TEST-UI-100" for m in members)

    # 3. Update member details
    update_payload = {
        "full_name": "Deep Coverage Operator Updated",
        "assigned_kiosk_id": "CANEBOT-BLR-02",
        "reporting_manager_emp_code": "MGR-02",
        "status": "PENDING_APPROVAL",
    }
    resp_up = client.post("/admin/apps/temperature-marker/api/members/EMP-TEST-UI-100/update", json=update_payload)
    assert resp_up.status_code == 200
    assert resp_up.json()["full_name"] == "Deep Coverage Operator Updated"

    # 4. Approvals queue and action
    resp_appr_list = client.get("/admin/apps/temperature-marker/api/approvals")
    assert resp_appr_list.status_code == 200

    resp_approve = client.post("/admin/apps/temperature-marker/api/approvals/EMP-TEST-UI-100/approve")
    assert resp_approve.status_code == 200
    assert resp_approve.json()["status"] == "success"

    # 5. Reassign member
    reassign_payload = {"kiosk_id": "CANEBOT-MUMBAI-08"}
    resp_re = client.post("/admin/apps/temperature-marker/api/members/EMP-TEST-UI-100/reassign", json=reassign_payload)
    assert resp_re.status_code == 200
    assert resp_re.json()["status"] == "SUCCESS"

    # 6. Forget photo
    resp_forget = client.post("/admin/apps/temperature-marker/api/members/EMP-TEST-UI-100/forget-photo")
    assert resp_forget.status_code in (200, 404)


def test_kiosk_calibration_and_config_api() -> None:
    """Test kiosk location calibration and config update endpoints."""
    kg = KnowledgeGraphService()

    # 1. Calibrate location
    cal_payload = {"latitude": 18.5621, "longitude": 73.9168}
    resp = client.post("/admin/apps/temperature-marker/api/kiosks/CANEBOT-PUNE-04/calibrate-location", json=cal_payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"

    # 2. Non-existent kiosk calibration
    resp_err = client.post("/admin/apps/temperature-marker/api/kiosks/CANEBOT-UNKNOWN/calibrate-location", json=cal_payload)
    assert resp_err.status_code == 404

    # 3. Kiosk config update
    cfg_payload = {"min_safe_temp": 1.0, "max_safe_temp": 4.0, "critical_temp": 7.5}
    resp_cfg = client.post("/admin/apps/temperature-marker/api/kiosks/CANEBOT-PUNE-04/config", json=cfg_payload)
    assert resp_cfg.status_code == 200

    # Clean up / ensure original coordinates are preserved
    kg.update_kiosk_coordinates("CANEBOT-PUNE-04", 18.5621, 73.9168)


def test_html_pages_and_views() -> None:
    """Test HTML monitoring, approvals, and verify-location views."""
    # 1. Monitoring dashboard
    resp_mon = client.get("/admin/apps/temperature-marker/monitoring")
    assert resp_mon.status_code == 200

    # 2. Approvals page
    resp_appr = client.get("/admin/apps/temperature-marker/approvals")
    assert resp_appr.status_code == 200

    # 3. Location verification page
    resp_loc = client.get("/admin/apps/temperature-marker/verify-location?kiosk=CANEBOT-PUNE-04")
    assert resp_loc.status_code == 200
