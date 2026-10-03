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

"""Unit Tests for Unified Fleet Monitoring, Multi-Check Cadence, and Alert Dispatch."""

from datetime import datetime, timezone
import pytest

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.database.models import AttendanceRecord, Employee, InternalMessageQueue
from apps.temperature_marker.services.alert_dispatcher import (
    dispatch_critical_hazard_alert,
    reset_alert_cooldown,
    should_dispatch_alert,
)
from apps.temperature_marker.services.intent_router import IngressIntent, classify_ingress_intent
from apps.temperature_marker.services.internal_dispatch import build_fleet_executive_digest


@pytest.fixture
def db_service(tmp_path):
    """Provide isolated in-memory SQLite database service for testing."""
    test_db_url = f"sqlite:///{tmp_path}/test_monitoring.db"
    return DatabaseService(db_url=test_db_url)


def test_kiosk_config_upsert_and_retrieval(db_service):
    """Verify KioskMonitoringConfig CRUD operations."""
    cfg = db_service.upsert_kiosk_config(
        kiosk_id="CANEBOT-PUNE-01",
        required_daily_temp_checks=4,
        check_interval_hours=3.5,
        min_safe_temp=2.0,
        max_safe_temp=4.5,
        critical_alert_temp=7.5,
        alert_manager_on_hazard=True,
    )
    assert cfg.kiosk_id == "CANEBOT-PUNE-01"
    assert cfg.required_daily_temp_checks == 4
    assert cfg.check_interval_hours == 3.5

    # Retrieve specific
    fetched = db_service.get_kiosk_config("CANEBOT-PUNE-01")
    assert fetched is not None
    assert fetched.required_daily_temp_checks == 4

    # Update
    updated = db_service.upsert_kiosk_config(
        kiosk_id="CANEBOT-PUNE-01",
        required_daily_temp_checks=5,
    )
    assert updated.required_daily_temp_checks == 5
    assert db_service.get_kiosk_config("CANEBOT-PUNE-01").required_daily_temp_checks == 5


def test_kiosk_daily_attendance_summary(db_service):
    """Verify get_kiosk_daily_attendance_summary calculates check-in, checks, and progress correctly."""
    # Enroll test employee
    emp = Employee(
        emp_code="EMP-TEST-01",
        full_name="Ramesh Pawar",
        phone_number="+919800112233",
        role="OPERATOR",
        status="ACTIVE",
        assigned_kiosk_id="CANEBOT-PUNE-04",
    )
    with db_service.SessionLocal() as session:
        session.add(emp)
        session.commit()

    # Log attendance check-in
    now = datetime.now(timezone.utc)
    rec1 = AttendanceRecord(
        correlation_id="corr-test-att-01",
        kiosk_id="CANEBOT-PUNE-04",
        emp_code="EMP-TEST-01",
        checkin_time_utc=now,
        is_duty_checkin=True,
        face_confidence=0.95,
        geofence_verified=True,
        gps_distance_meters=15.0,
        chiller_temp_c=3.2,
        haccp_compliant=True,
        haccp_status="COMPLIANT",
    )
    with db_service.SessionLocal() as session:
        session.add(rec1)
        session.commit()

    summaries = db_service.get_kiosk_daily_attendance_summary()
    assert len(summaries) >= 1

    pune_04 = next((s for s in summaries if s["kiosk_id"] == "CANEBOT-PUNE-04"), None)
    assert pune_04 is not None
    assert pune_04["has_checkin_today"] is True
    assert pune_04["checkin_operator_name"] == "Ramesh Pawar"
    assert pune_04["total_temp_checks_today"] == 1
    assert pune_04["latest_chiller_temp_c"] == 3.2
    assert pune_04["has_critical_hazard"] is False


def test_active_high_alerts_and_acknowledgement(db_service):
    """Verify high alerts are flagged and can be acknowledged."""
    now = datetime.now(timezone.utc)
    hazard_rec = AttendanceRecord(
        correlation_id="corr-test-att-02",
        kiosk_id="CANEBOT-PUNE-05",
        emp_code="EMP-TEST-02",
        checkin_time_utc=now,
        is_duty_checkin=True,
        face_confidence=0.95,
        geofence_verified=True,
        gps_distance_meters=10.0,
        chiller_temp_c=8.5,
        haccp_compliant=False,
        haccp_status="CRITICAL_HAZARD",
    )
    with db_service.SessionLocal() as session:
        session.add(hazard_rec)
        session.commit()
        hazard_id = hazard_rec.id

    alerts = db_service.get_active_high_alerts()
    assert any(a["id"] == hazard_id and a["type"] == "HACCP Hazard" for a in alerts)

    # Acknowledge alert
    success = db_service.acknowledge_alert(hazard_id, ack_notes="Thermostat checked by manager")
    assert success is True

    # Check alert is now cleared
    remaining_alerts = db_service.get_active_high_alerts()
    assert not any(a["id"] == hazard_id for a in remaining_alerts)


def test_web_message_reply_and_resolution(db_service):
    """Verify resolve_internal_message_web resolves message and returns outbound reply payload."""
    msg = db_service.enqueue_internal_message(
        correlation_id="corr-test-1",
        sender_phone="+919811223344",
        sender_emp_code="EMP-01",
        sender_name="Suresh K",
        kiosk_id="CANEBOT-PUNE-04",
        recipient_emp_code="MGR-01",
        recipient_phone="+919800000000",
        message_text="Need extra sugarcane cups today",
        priority=50,
    )
    assert msg.status == "QUEUED"

    success, op_phone, reply_text = db_service.resolve_internal_message_web(
        message_id=msg.id,
        reply_text="Dispatched 200 cups with supply van",
        resolver_phone="+919800000000",
    )
    assert success is True
    assert op_phone == "+919811223344"
    assert reply_text is not None
    assert "Dispatched 200 cups" in reply_text
    assert "RESOLVED" in reply_text


def test_alert_dispatcher_cooldown():
    """Verify alert dispatcher suppresses duplicate alerts within cooldown window."""
    reset_alert_cooldown()

    # First alert should be permitted
    allowed_1 = should_dispatch_alert("CANEBOT-PUNE-04", "HACCP_HAZARD", cooldown_seconds=60.0)
    assert allowed_1 is True

    # Immediate second alert for same kiosk & type should be suppressed
    allowed_2 = should_dispatch_alert("CANEBOT-PUNE-04", "HACCP_HAZARD", cooldown_seconds=60.0)
    assert allowed_2 is False

    # Different kiosk should be permitted
    allowed_other_kiosk = should_dispatch_alert("CANEBOT-PUNE-05", "HACCP_HAZARD", cooldown_seconds=60.0)
    assert allowed_other_kiosk is True

    reset_alert_cooldown()


def test_fleet_executive_digest_builder(db_service):
    """Verify build_fleet_executive_digest compiles a readable multi-kiosk summary."""
    digest = build_fleet_executive_digest(manager_name="Supervisor Ajay", db_service=db_service)
    assert "CANECTAR FLEET EXECUTIVE STATUS" in digest
    assert "Manager: Supervisor Ajay" in digest
    assert "Active Kiosks:" in digest
    assert "CANEBOT-PUNE-04" in digest


def test_ingress_intent_classification_for_fleet_commands():
    """Verify 'fleet', 'status', and 'alerts' classify as SYSTEM_COMMAND."""
    res_fleet = classify_ingress_intent("fleet", is_image=False, sender_role="MANAGER")
    assert res_fleet.intent == IngressIntent.SYSTEM_COMMAND

    res_status = classify_ingress_intent("status", is_image=False, sender_role="MANAGER")
    assert res_status.intent == IngressIntent.SYSTEM_COMMAND

    res_alerts = classify_ingress_intent("alerts", is_image=False, sender_role="MANAGER")
    assert res_alerts.intent == IngressIntent.SYSTEM_COMMAND
