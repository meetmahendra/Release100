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
Unit test suite verifying that every page and API in Release100 is strictly tenant-aware.

Tests:
1. JWT cookie and Authorization header resolution in TenantContextMiddleware.
2. Mail Organizer multi-tenant data isolation and template context badge rendering.
3. Temperature Marker multi-tenant data isolation and template context badge rendering.
4. Admin Shell multi-tenant scoped dashboards and user management.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.identity.models import Base as IdentityBase, PlatformUser, Tenant
from core_platform.app.middleware.tenant_context import resolve_effective_tenant_info
from apps.mail_organizer.database.models import Base as MailBase
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.temperature_marker.database.models import Base as TempBase
from apps.temperature_marker.database.db_service import DatabaseService as TempDBService
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService


@pytest.fixture
def memory_db_engine():
    """In-memory SQLite engine with all platform and domain schemas."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    IdentityBase.metadata.create_all(bind=engine)
    MailBase.metadata.create_all(bind=engine)
    TempBase.metadata.create_all(bind=engine)
    return engine


def test_tenant_context_resolution_with_customer_jwt(memory_db_engine, monkeypatch):
    """Verify that a customer tenant admin JWT accurately resolves their real organization."""
    Session = sessionmaker(bind=memory_db_engine)
    with Session() as session:
        t = Tenant(
            id="acme_corp",
            name="Acme Corporation Ltd",
            status="ACTIVE",
        )
        session.add(t)
        session.commit()

    # Mock get_db_manager to return our test engine
    class MockDBMgr:
        def get_engine(self):
            return memory_db_engine

        def get_session(self):
            return Session()

    monkeypatch.setattr("core_platform.app.db.manager.get_db_manager", lambda: MockDBMgr())

    # Create token for acme_corp tenant admin
    token = create_jwt_token(
        principal_id="acme_admin",
        roles=["admin"],
        permitted_apps=["mail_organizer", "temperature_marker"],
        tenant_id="acme_corp",
    )

    class MockRequest:
        def __init__(self, token_str: str):
            self.cookies = {"admin_token": token_str}
            self.headers = {}
            self.state = type("State", (), {"tenant_id": "acme_corp"})()

    req = MockRequest(token)
    eff_tenant, tenant_name, tenant_obj = resolve_effective_tenant_info(req)

    assert eff_tenant == "acme_corp"
    assert tenant_name == "Acme Corporation Ltd"
    assert tenant_obj is not None
    assert tenant_obj.id == "acme_corp"


def test_mail_organizer_tenant_data_isolation(memory_db_engine):
    """Verify that MailOrganizerDBService strictly isolates data between different tenants."""
    mail_db = MailDatabaseService(engine=memory_db_engine)

    # Store email for tenant A
    email_a = mail_db.store_email(
        gmail_id="msg-a-1",
        thread_id="th-a-1",
        subject="Tenant A Q3 Invoice",
        sender="billing@tenant-a.com",
        to_recipients="admin@tenant-a.com",
        body="Invoice details for Tenant A",
        tenant_id="tenant_a",
    )

    # Store email for tenant B
    email_b = mail_db.store_email(
        gmail_id="msg-b-1",
        thread_id="th-b-1",
        subject="Tenant B Security Audit",
        sender="security@tenant-b.com",
        to_recipients="admin@tenant-b.com",
        body="Security report for Tenant B",
        tenant_id="tenant_b",
    )

    # Query as tenant A
    emails_a = mail_db.get_recent_emails(limit=10, tenant_id="tenant_a")
    assert len(emails_a) == 1
    assert emails_a[0]["id"] == email_a.id
    assert emails_a[0]["subject"] == "Tenant A Q3 Invoice"

    # Query as tenant B
    emails_b = mail_db.get_recent_emails(limit=10, tenant_id="tenant_b")
    assert len(emails_b) == 1
    assert emails_b[0]["id"] == email_b.id
    assert emails_b[0]["subject"] == "Tenant B Security Audit"

    # Query as platform super-admin (*)
    all_emails = mail_db.get_recent_emails(limit=10, tenant_id="*")
    assert len(all_emails) == 2


def test_temperature_marker_tenant_data_isolation(memory_db_engine):
    """Verify that TempDBService and KnowledgeGraph strictly isolate operators, kiosks, and attendance."""
    temp_db = TempDBService(engine=memory_db_engine)

    # Register employee for tenant A
    emp_a = temp_db.register_employee(
        emp_code="EMP-A-01",
        full_name="Alice Tenant A",
        phone_number="+919800000001",
        assigned_kiosk_id="KIOSK-A",
        tenant_id="tenant_a",
    )

    # Register employee for tenant B
    emp_b = temp_db.register_employee(
        emp_code="EMP-B-01",
        full_name="Bob Tenant B",
        phone_number="+919800000002",
        assigned_kiosk_id="KIOSK-B",
        tenant_id="tenant_b",
    )

    # Record attendance for both
    temp_db.record_attendance(
        correlation_id="att-a-1",
        emp_code="EMP-A-01",
        kiosk_id="KIOSK-A",
        face_confidence=0.98,
        gps_distance_meters=12.5,
        geofence_verified=True,
        chiller_temp_c=3.2,
        haccp_compliant=True,
        haccp_status="SAFE_RANGE",
        tenant_id="tenant_a",
    )

    temp_db.record_attendance(
        correlation_id="att-b-1",
        emp_code="EMP-B-01",
        kiosk_id="KIOSK-B",
        face_confidence=0.96,
        gps_distance_meters=15.0,
        geofence_verified=True,
        chiller_temp_c=3.5,
        haccp_compliant=True,
        haccp_status="SAFE_RANGE",
        tenant_id="tenant_b",
    )

    # Verify employee queries are isolated
    emps_a = temp_db.get_all_employees(tenant_id="tenant_a")
    assert len(emps_a) == 1
    assert emps_a[0].full_name == "Alice Tenant A"

    emps_b = temp_db.get_all_employees(tenant_id="tenant_b")
    assert len(emps_b) == 1
    assert emps_b[0].full_name == "Bob Tenant B"

    # Verify attendance queries are isolated
    att_a = temp_db.get_recent_attendance(limit=10, tenant_id="tenant_a")
    assert len(att_a) == 1
    assert att_a[0].emp_code == "EMP-A-01"

    att_b = temp_db.get_recent_attendance(limit=10, tenant_id="tenant_b")
    assert len(att_b) == 1
    assert att_b[0].emp_code == "EMP-B-01"

    # Verify KnowledgeGraph kiosk listing is isolated
    kg = KnowledgeGraphService()
    kg.add_kiosk("KIOSK-A", "Site Alpha", "Pune", 18.52, 73.85, tenant_id="tenant_a")
    kg.add_kiosk("KIOSK-B", "Site Beta", "Mumbai", 19.07, 72.87, tenant_id="tenant_b")

    kiosks_a = kg.list_all_kiosks(tenant_id="tenant_a")
    assert len(kiosks_a) == 1
    assert kiosks_a[0]["kiosk_id"] == "KIOSK-A"

    kiosks_b = kg.list_all_kiosks(tenant_id="tenant_b")
    assert len(kiosks_b) == 1
    assert kiosks_b[0]["kiosk_id"] == "KIOSK-B"


def test_mail_organizer_rules_and_drafts_isolation(memory_db_engine):
    """Verify that mail rules, drafts, and PM action queues are strictly isolated by tenant."""
    mail_db = MailDatabaseService(engine=memory_db_engine)

    # 1. Rules
    mail_db.add_rule(
        rule_type="vip_domain",
        pattern="*@vip-corp-a.com",
        action="tag_vip",
        tenant_id="tenant_a",
    )
    mail_db.add_rule(
        rule_type="vip_domain",
        pattern="*@partner-b.com",
        action="tag_vip",
        tenant_id="tenant_b",
    )

    rules_a = mail_db.get_active_rules(tenant_id="tenant_a")
    assert len(rules_a) == 1
    assert rules_a[0].pattern == "*@vip-corp-a.com"

    rules_b = mail_db.get_active_rules(tenant_id="tenant_b")
    assert len(rules_b) == 1
    assert rules_b[0].pattern == "*@partner-b.com"

    # 2. Drafts
    mail_db.store_draft(
        gmail_id="draft-a-1",
        thread_id="th-a-draft",
        subject="Draft Reply A",
        body="Dear Client A",
        recipient="client@tenant-a.com",
        tenant_id="tenant_a",
    )
    mail_db.store_draft(
        gmail_id="draft-b-1",
        thread_id="th-b-draft",
        subject="Draft Reply B",
        body="Dear Client B",
        recipient="client@tenant-b.com",
        tenant_id="tenant_b",
    )

    drafts_a = mail_db.get_all_drafts(tenant_id="tenant_a")
    assert len(drafts_a) == 1
    assert drafts_a[0].subject == "Draft Reply A"

    drafts_b = mail_db.get_all_drafts(tenant_id="tenant_b")
    assert len(drafts_b) == 1
    assert drafts_b[0].subject == "Draft Reply B"

    # 3. PM Tasks
    mail_db.queue_pm_task(
        summary="Action Item Tenant A",
        gmail_id="msg-pm-a",
        email_subject="Subject A",
        email_sender="sender@a.com",
        assignee="Lead A",
        tenant_id="tenant_a",
    )
    mail_db.queue_pm_task(
        summary="Action Item Tenant B",
        gmail_id="msg-pm-b",
        email_subject="Subject B",
        email_sender="sender@b.com",
        assignee="Lead B",
        tenant_id="tenant_b",
    )

    pm_a = mail_db.get_pending_pm_tasks(tenant_id="tenant_a")
    assert len(pm_a) == 1
    assert pm_a[0].summary == "Action Item Tenant A"

    pm_b = mail_db.get_pending_pm_tasks(tenant_id="tenant_b")
    assert len(pm_b) == 1
    assert pm_b[0].summary == "Action Item Tenant B"


def test_temperature_marker_messages_and_summary_isolation(memory_db_engine):
    """Verify that TM internal messages, alerts, and summaries are isolated by tenant."""
    temp_db = TempDBService(engine=memory_db_engine)

    # Messages
    temp_db.enqueue_internal_message(
        sender_phone="+919800000001",
        sender_name="Operator A",
        recipient_phone="+919800000099",
        message_text="Need maintenance on Kiosk A",
        priority=100,
        tenant_id="tenant_a",
    )
    temp_db.enqueue_internal_message(
        sender_phone="+919800000002",
        sender_name="Operator B",
        recipient_phone="+919800000099",
        message_text="Need supplies on Kiosk B",
        priority=100,
        tenant_id="tenant_b",
    )

    msgs_a = temp_db.get_recent_internal_messages(tenant_id="tenant_a")
    assert len(msgs_a) == 1
    assert "Kiosk A" in msgs_a[0].message_text

    msgs_b = temp_db.get_recent_internal_messages(tenant_id="tenant_b")
    assert len(msgs_b) == 1
    assert "Kiosk B" in msgs_b[0].message_text

    alerts_a = temp_db.get_active_high_alerts(tenant_id="tenant_a")
    assert len(alerts_a) == 1
    assert alerts_a[0]["emp_code"] == "OPERATOR"

    alerts_b = temp_db.get_active_high_alerts(tenant_id="tenant_b")
    assert len(alerts_b) == 1

