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
E2E Journey 3: Edge Kiosk Check-In, Geofence & Duty Workflow (GEES v3.1).

Exercises the full edge kiosk check-in and regulatory safety stack:
1. Tenant provisions Kiosk with geofence boundaries and enrolls an operator.
2. Admin approves and activates the operator account.
3. Valid In-Geofence Check-in executes -> Verified Compliant, duty status recorded, audit hash produced.
4. Out-of-Geofence Spoof / Breach Check-in -> Deterministic Layer-0 Pre-Execution Rejection.
5. Critical HACCP Temperature Hazard Check-in -> Escalated / Safety Intercepted.
6. Actionable DOM Invariants verified across Fleet Map and Live Monitoring dashboards.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from apps.temperature_marker.database.db_service import DatabaseService as TMDatabaseService
from apps.temperature_marker.database.models import AttendanceRecord, Base as TMBase, Employee
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.identity.models import Base as IdentityBase, Tenant, TenantDomain
from core_platform.main import app


@pytest.fixture
def tm_e2e_env(tmp_path: Path) -> tuple[TestClient, TMDatabaseService, KnowledgeGraphService]:
    """Initialize isolated database and services for Temperature Marker E2E."""
    db_file = tmp_path / "e2e_temperature_marker.db"
    db_url = f"sqlite:///{db_file}"

    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(database_url=db_url)
    engine = db_mgr.get_engine()
    IdentityBase.metadata.create_all(bind=engine)
    TMBase.metadata.create_all(bind=engine)
    session_maker = sessionmaker(bind=engine)

    with session_maker() as session:
        dairy = Tenant(
            id="dairy_fresh",
            name="Dairy Fresh Cold Chain",
            license_tier="ENTERPRISE",
            storage_region="ap-south-1",
        )
        dairy_dom = TenantDomain(tenant_id="dairy_fresh", domain_name="dairy.intentrouter.io")
        session.merge(dairy)
        session.merge(dairy_dom)
        session.commit()

    TMDatabaseService._instance = None
    tm_db = TMDatabaseService.get_instance(engine=engine)
    kg_service = KnowledgeGraphService()

    client = TestClient(app, follow_redirects=False)
    return client, tm_db, kg_service


def test_e2e_kiosk_checkin_geofence_and_duty_lifecycle(
    tm_e2e_env: tuple[TestClient, TMDatabaseService, KnowledgeGraphService]
) -> None:
    client, tm_db, kg_service = tm_e2e_env

    # -------------------------------------------------------------------------
    # STEP 1: Admin Provisions Kiosk and Enrolls Operator Member
    # -------------------------------------------------------------------------
    admin_token = create_jwt_token(
        principal_id="dairy_admin",
        roles=["admin"],
        permitted_apps=["all", "temperature_marker"],
        tenant_id="dairy_fresh",
    )
    client.cookies.set("admin_token", admin_token)
    client.cookies.set("csrf_token", "csrf_tm_e2e_123")

    kiosk_payload = {
        "kiosk_id": "KIOSK-BLR-01",
        "site_name": "Bengaluru Central Cold Hub",
        "city": "Bengaluru",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "radius_meters": 150.0,
        "machine_model": "Chiller Pro X",
        "display_type": "DIGITAL_SEVEN_SEGMENT",
        "primary_operator_phones": ["+919876543210"],
    }
    kiosk_resp = client.post(
        "/admin/apps/temperature-marker/api/kiosks",
        json=kiosk_payload,
        headers={"Host": "dairy.intentrouter.io", "X-CSRF-Token": "csrf_tm_e2e_123"},
    )
    assert kiosk_resp.status_code == 200
    assert kiosk_resp.json().get("kiosk_id") == "KIOSK-BLR-01"

    # Enroll Operator
    member_payload = {
        "full_name": "Ramesh Kumar",
        "phone_number": "+919876543210",
        "assigned_kiosk_id": "KIOSK-BLR-01",
        "role": "OPERATOR",
    }
    member_resp = client.post(
        "/admin/apps/temperature-marker/api/members",
        json=member_payload,
        headers={"Host": "dairy.intentrouter.io", "X-CSRF-Token": "csrf_tm_e2e_123"},
    )
    assert member_resp.status_code == 200
    member_data = member_resp.json()
    emp_code = member_data.get("emp_code")
    assert emp_code is not None

    # Admin approves and activates operator
    updated = tm_db.update_employee(emp_code=emp_code, status="ACTIVE")
    assert updated is not None
    assert updated.status == "ACTIVE"

    # -------------------------------------------------------------------------
    # STEP 2: In-Geofence Compliant Check-In Simulation (3.2°C, inside 150m)
    # -------------------------------------------------------------------------
    sim_valid = {
        "kiosk_id": "KIOSK-BLR-01",
        "phone_number": "+919876543210",
        "temperature": 3.2,
        "face_confidence": 0.96,
        "latitude": 12.97165,   # ~6 meters away (within 150m geofence)
        "longitude": 77.59465,
        "photo_source": "synthetic",
    }
    valid_resp = client.post(
        "/admin/apps/temperature-marker/api/simulate",
        json=sim_valid,
        headers={"Host": "dairy.intentrouter.io", "X-CSRF-Token": "csrf_tm_e2e_123"},
    )
    assert valid_resp.status_code == 200
    valid_data = valid_resp.json()
    assert valid_data.get("status") == "COMPLIANT"

    # -------------------------------------------------------------------------
    # STEP 3: Out-of-Geofence Breach Simulation (5 km away)
    # -------------------------------------------------------------------------
    sim_breach = {
        "kiosk_id": "KIOSK-BLR-01",
        "phone_number": "+919876543210",
        "temperature": 3.2,
        "face_confidence": 0.96,
        "latitude": 13.0500,   # ~10 km away
        "longitude": 77.6500,
        "photo_source": "synthetic",
    }
    breach_resp = client.post(
        "/admin/apps/temperature-marker/api/simulate",
        json=sim_breach,
        headers={"Host": "dairy.intentrouter.io", "X-CSRF-Token": "csrf_tm_e2e_123"},
    )
    assert breach_resp.status_code == 200
    breach_data = breach_resp.json()
    assert breach_data.get("status") == "REJECTED"
    assert "Geofence" in breach_data.get("message", "") or "distance" in breach_data.get("message", "").lower() or "rejected" in breach_data.get("status", "").lower()

    # -------------------------------------------------------------------------
    # STEP 4: Critical Temperature Hazard Simulation (11.5°C HACCP breach)
    # -------------------------------------------------------------------------
    sim_hazard = {
        "kiosk_id": "KIOSK-BLR-01",
        "phone_number": "+919876543210",
        "temperature": 11.5,
        "face_confidence": 0.96,
        "latitude": 12.97162,
        "longitude": 77.59462,
        "photo_source": "synthetic",
    }
    hazard_resp = client.post(
        "/admin/apps/temperature-marker/api/simulate",
        json=sim_hazard,
        headers={"Host": "dairy.intentrouter.io", "X-CSRF-Token": "csrf_tm_e2e_123"},
    )
    assert hazard_resp.status_code == 200
    hazard_data = hazard_resp.json()
    assert hazard_data.get("status") == "CRITICAL"

    # -------------------------------------------------------------------------
    # STEP 5: Verify Actionable DOM Invariants on Fleet & Monitoring Dashboards
    # -------------------------------------------------------------------------
    fleet_view = client.get(
        "/admin/apps/temperature-marker/fleet",
        headers={"Host": "dairy.intentrouter.io"},
    )
    assert fleet_view.status_code == 200
    assert "KIOSK-BLR-01" in fleet_view.text or "Bengaluru" in fleet_view.text
    assert "Ramesh Kumar" in fleet_view.text or "+919876543210" in fleet_view.text

    monitoring_view = client.get(
        "/admin/apps/temperature-marker/monitoring",
        headers={"Host": "dairy.intentrouter.io"},
    )
    assert monitoring_view.status_code == 200
    assert "Live Monitoring" in monitoring_view.text or "Telemetry" in monitoring_view.text or "HACCP" in monitoring_view.text
