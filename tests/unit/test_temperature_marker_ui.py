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

"""Synthetic Unit Tests for Temperature Marker Admin Web Shell and Stepper Wizard."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.temperature_marker.database.db_service import DatabaseService
from core_platform.main import app

client = TestClient(app)


def test_ui_root_redirect() -> None:
    """Root redirect must redirect to fleet dashboard."""
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/admin/apps/temperature-marker/fleet"


def test_fleet_html_view() -> None:
    """Fleet HTML view must render 200 OK and contain CaneBot station names."""
    resp = client.get("/admin/apps/temperature-marker/fleet")
    assert resp.status_code == 200
    assert "Multi-Kiosk Fleet Overview" in resp.text
    assert "CANEBOT-PUNE-04" in resp.text
    assert "Phoenix Marketcity Food Court" in resp.text


def test_fleet_json_api() -> None:
    """Fleet JSON API must return all registered kiosks."""
    resp = client.get("/admin/apps/temperature-marker/api/fleet")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 3
    kiosk_ids = [k["kiosk_id"] for k in data]
    assert "CANEBOT-PUNE-04" in kiosk_ids
    assert "CANEBOT-MUMBAI-08" in kiosk_ids


def test_wizard_html_view() -> None:
    """Stepper Wizard HTML view must render 200 OK."""
    resp = client.get("/admin/apps/temperature-marker/wizard")
    assert resp.status_code == 200
    assert "Progressive Stepper Check-in Simulator" in resp.text
    assert "Run Verification Workflow" in resp.text


def test_simulation_api_safe() -> None:
    """Simulation API must evaluate through safety gates and return COMPLIANT."""
    # Ensure active employee exists
    db = DatabaseService()
    db.register_employee(
        emp_code="EMP-SIM-TEST",
        full_name="Sim Worker",
        phone_number="+919800011122",
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="ACTIVE",
    )
    db.approve_employee("EMP-SIM-TEST")

    payload = {
        "kiosk_id": "CANEBOT-PUNE-04",
        "phone_number": "+919800011122",
        "temperature": 3.2,
        "face_confidence": 0.95,
        "latitude": 18.5621,
        "longitude": 73.9168,
    }
    resp = client.post("/admin/apps/temperature-marker/api/simulate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLIANT"
    assert data["geofence_status"] == "VERIFIED"
    assert data["haccp_status"] == "COMPLIANT"
    assert "audit_hash" in data


def test_simulation_api_critical_hazard() -> None:
    """Simulation API must flag temperatures above 7.0°C as CRITICAL."""
    payload = {
        "kiosk_id": "CANEBOT-PUNE-04",
        "phone_number": "+919800011122",
        "temperature": 8.5,
        "face_confidence": 0.95,
        "latitude": 18.5621,
        "longitude": 73.9168,
    }
    resp = client.post("/admin/apps/temperature-marker/api/simulate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "CRITICAL"
    assert data["haccp_status"] == "CRITICAL_HAZARD"


def test_approvals_views_and_actions() -> None:
    """Approvals HTML and API must list and approve pending operators."""
    db = DatabaseService()
    db.register_employee(
        emp_code="EMP-PENDING-UI",
        full_name="Pending Operator",
        phone_number="+919999000011",
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="PENDING_APPROVAL",
    )

    # View approvals page
    resp = client.get("/admin/apps/temperature-marker/approvals")
    assert resp.status_code == 200
    assert "Operator Onboarding Approvals" in resp.text

    # View API
    api_resp = client.get("/admin/apps/temperature-marker/api/approvals")
    assert api_resp.status_code == 200
    pending_ids = [p["emp_code"] for p in api_resp.json()]
    assert "EMP-PENDING-UI" in pending_ids

    # Approve
    approve_resp = client.post("/admin/apps/temperature-marker/api/approvals/EMP-PENDING-UI/approve")
    assert approve_resp.status_code == 200
    assert approve_resp.json()["new_state"] == "ACTIVE"


def test_location_verification() -> None:
    """1-Click mobile geolocation check must compute distance and verify perimeter."""
    # Test HTML view
    resp = client.get("/loc?kiosk_id=CANEBOT-PUNE-04")
    assert resp.status_code == 200
    assert "Kiosk Geolocation Check" in resp.text

    # Test API valid inside perimeter
    valid_resp = client.post(
        "/admin/apps/temperature-marker/api/verify-location",
        json={"kiosk_id": "CANEBOT-PUNE-04", "latitude": 18.5621, "longitude": 73.9168},
    )
    assert valid_resp.status_code == 200
    assert valid_resp.json()["within_geofence"] is True
    assert valid_resp.json()["status"] == "VERIFIED"

    # Test API breach (far away)
    breach_resp = client.post(
        "/admin/apps/temperature-marker/api/verify-location",
        json={"kiosk_id": "CANEBOT-PUNE-04", "latitude": 19.0760, "longitude": 72.8777},
    )
    assert breach_resp.status_code == 200
    assert breach_resp.json()["within_geofence"] is False
    assert breach_resp.json()["status"] == "BREACH"

    # Test API with session_id
    sess_resp = client.post(
        "/admin/apps/temperature-marker/api/verify-location",
        json={
            "kiosk_id": "CANEBOT-PUNE-04",
            "latitude": 18.5621,
            "longitude": 73.9168,
            "session_id": "sess_12345",
        },
    )
    assert sess_resp.status_code == 200

    # Test API with nonexistent kiosk (404)
    bad_kiosk = client.post(
        "/admin/apps/temperature-marker/api/verify-location",
        json={"kiosk_id": "NONEXISTENT-KIOSK", "latitude": 18.0, "longitude": 73.0},
    )
    assert bad_kiosk.status_code == 404

    # Test approve / reject 404
    bad_appr = client.post("/admin/apps/temperature-marker/api/approvals/NONEXISTENT-EMP/approve")
    assert bad_appr.status_code == 404

    bad_rej = client.post("/admin/apps/temperature-marker/api/approvals/NONEXISTENT-EMP/reject")
    assert bad_rej.status_code == 404


def test_root_mounted_shortcuts_and_redirects() -> None:
    """Test root-level shortcuts /loc and /mail mounted on main FastAPI app."""
    # Test GET /loc
    loc_resp = client.get("/loc")
    assert loc_resp.status_code == 200
    assert "text/html" in loc_resp.headers["content-type"]

    # Test POST /api/verify-location (root shortcut)
    api_resp = client.post(
        "/api/verify-location",
        json={"kiosk_id": "CANEBOT-PUNE-04", "latitude": 18.5621, "longitude": 73.9168},
    )
    assert api_resp.status_code == 200
    assert api_resp.json()["within_geofence"] is True

    # Test GET /mail and /mail/ redirects
    m_resp = client.get("/mail", follow_redirects=False)
    assert m_resp.status_code in (302, 307)
    assert m_resp.headers["location"] == "/admin/apps/mail-organizer/dashboard"

    m_resp_slash = client.get("/mail/", follow_redirects=False)
    assert m_resp_slash.status_code in (302, 307)


@pytest.mark.anyio
async def test_main_outbox_sync_worker_cycle() -> None:
    """Test _outbox_sync_worker loop in main.py executes a drain cycle."""
    import asyncio
    from core_platform.main import _outbox_sync_worker

    stop_evt = asyncio.Event()
    stop_evt.set()  # Stop immediately after one check
    # Should complete without error
    await _outbox_sync_worker(stop_evt)


def test_temperature_marker_database_service_crud(tmp_path: Path) -> None:
    """Test real DatabaseService operations on local SQLite file without mocks."""
    from apps.temperature_marker.database.db_service import DatabaseService

    db_path = tmp_path / "tm_real_test.db"
    db = DatabaseService(db_url=f"sqlite:///{db_path}")

    # Register employee
    emp = db.register_employee(
        emp_code="EMP-REAL-001",
        full_name="Real Operator",
        phone_number="+919111222333",
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="PENDING_APPROVAL",
    )
    assert emp.id is not None
    assert emp.status == "PENDING_APPROVAL"

    # Lookup by phone and code
    by_phone = db.get_employee_by_phone("+919111222333")
    assert by_phone is not None
    assert by_phone.emp_code == "EMP-REAL-001"

    by_code = db.get_employee_by_code("EMP-REAL-001")
    assert by_code is not None

    # Pending approvals
    pending = db.get_pending_approvals()
    assert len(pending) >= 1

    # Approve
    ok_appr = db.approve_employee("EMP-REAL-001")
    assert ok_appr is True
    emp_checked = db.get_employee_by_code("EMP-REAL-001")
    assert emp_checked is not None
    assert emp_checked.status == "ACTIVE"

    # Reject nonexistent and update existing
    assert db.approve_employee("NONEXISTENT") is False
    assert db.reject_employee("NONEXISTENT") is False

    # Update employee with new name
    emp_updated = db.register_employee(
        emp_code="EMP-REAL-001",
        full_name="Real Operator Updated",
        phone_number="+919111222333",
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="ACTIVE",
    )
    assert emp_updated.full_name == "Real Operator Updated"

    # Record attendance
    rec = db.record_attendance(
        correlation_id="corr_real_001",
        emp_code="EMP-REAL-001",
        kiosk_id="CANEBOT-PUNE-04",
        face_confidence=0.95,
        gps_distance_meters=12.5,
        geofence_verified=True,
        chiller_temp_c=3.2,
        haccp_compliant=True,
        haccp_status="SAFE_RANGE",
    )
    assert rec.id is not None

    # Get recent attendance
    recents = db.get_recent_attendance(limit=10)
    assert len(recents) >= 1

    # Enqueue outbox item
    item = db.enqueue_outbox(
        correlation_id="corr_real_001",
        target_gateway="in_house_rest",
        payload={"kiosk_id": "CANEBOT-PUNE-04", "temp": 3.2},
    )
    assert item.id is not None
    assert item.status == "PENDING"

    # Get pending outbox
    pending_items = db.get_pending_outbox_items()
    assert len(pending_items) >= 1

    # Mark synced
    db.mark_outbox_synced(item.id)

    # Mark failed on another item
    item2 = db.enqueue_outbox(
        correlation_id="corr_real_002",
        target_gateway="in_house_rest",
        payload={"kiosk_id": "CANEBOT-PUNE-04", "temp": 3.5},
    )
    db.mark_outbox_failed(item2.id, max_attempts=1)

    db.close()


def test_media_vault_photo_serving(tmp_path: Path) -> None:
    """Verify check-in capture images and operator photos are served correctly without 404."""
    from pathlib import Path

    # Create dummy media photo
    media_dir = Path("logs/media")
    media_dir.mkdir(parents=True, exist_ok=True)
    test_photo = media_dir / "test_unit_media.jpg"
    test_photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    try:
        # Test root static mount /logs/media
        resp_mount = client.get("/logs/media/test_unit_media.jpg")
        assert resp_mount.status_code == 200
        assert resp_mount.headers["content-type"] in ("image/jpeg", "image/pjpeg")

        # Test app route /admin/apps/temperature-marker/media
        resp_route = client.get("/admin/apps/temperature-marker/media/test_unit_media.jpg")
        assert resp_route.status_code == 200
        assert resp_route.headers["content-type"] == "image/jpeg"

        # Test non-existent media returns 404
        resp_404 = client.get("/logs/media/nonexistent_file_9999.jpg")
        assert resp_404.status_code == 404
    finally:
        if test_photo.exists():
            test_photo.unlink()


def test_operator_photo_api() -> None:
    """Verify operator profile photo API serves existing photo and returns 404 for missing photo."""
    from pathlib import Path

    photos_dir = Path("logs/photos")
    photos_dir.mkdir(parents=True, exist_ok=True)
    dummy_op_photo = photos_dir / "EMP-TEST-PHOTO_profile.jpg"
    dummy_op_photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    try:
        # Operator with photo
        resp_ok = client.get("/admin/apps/temperature-marker/api/members/EMP-TEST-PHOTO/photo")
        assert resp_ok.status_code == 200
        assert resp_ok.headers["content-type"] == "image/jpeg"

        # Operator without photo returns 404
        resp_404 = client.get("/admin/apps/temperature-marker/api/members/EMP-NO-SUCH-OP/photo")
        assert resp_404.status_code == 404
    finally:
        if dummy_op_photo.exists():
            dummy_op_photo.unlink()




