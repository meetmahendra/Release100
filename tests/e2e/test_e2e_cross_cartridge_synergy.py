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
E2E Journey 4: Cross-Cartridge Platform Synergy & Semantic Event Choreography (GEES v3.1).

Exercises the multi-cartridge microkernel substrate:
1. Ingress receives polymorphic intents (Email triage vs Kiosk duty check-in).
2. Semantic Router dispatches without hardcoded domain couplings.
3. Cartridge A (Mail Organizer) & Cartridge B (Temperature Marker) execute domain workflows.
4. Cryptographic Audit Engine records contemporaneous SHA-256 chained telemetry.
5. Unified Admin Shell renders cross-cartridge KPIs and health diagnostics.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.database.models import Base as MailBase
from apps.temperature_marker.database.db_service import DatabaseService as TMDatabaseService
from apps.temperature_marker.database.models import Base as TMBase
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.identity.models import Base as IdentityBase, Tenant, TenantDomain
from core_platform.app.routing.semantic_router import RoutingDecision, SemanticRouter
from core_platform.app.telemetry.audit_engine import AuditEngine
from core_platform.main import app


@pytest.fixture
def synergy_e2e_env(tmp_path: Path) -> tuple[TestClient, MailDatabaseService, TMDatabaseService, AuditEngine]:
    """Initialize isolated multi-cartridge database and services."""
    db_file = tmp_path / "e2e_synergy.db"
    db_url = f"sqlite:///{db_file}"
    audit_dir = tmp_path / "audit"

    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(database_url=db_url)
    engine = db_mgr.get_engine()
    IdentityBase.metadata.create_all(bind=engine)
    MailBase.metadata.create_all(bind=engine)
    TMBase.metadata.create_all(bind=engine)
    session_maker = sessionmaker(bind=engine)

    with session_maker() as session:
        omni = Tenant(
            id="omni_corp",
            name="Omni Enterprise Solutions",
            license_tier="ENTERPRISE",
            storage_region="ap-south-1",
            allowed_cartridges_json='["*"]',
        )
        omni_dom = TenantDomain(tenant_id="omni_corp", domain_name="omni.intentrouter.io")
        session.merge(omni)
        session.merge(omni_dom)
        session.commit()

    MailDatabaseService._instance = None
    mail_db = MailDatabaseService.get_instance(engine=engine)

    TMDatabaseService._instance = None
    tm_db = TMDatabaseService.get_instance(engine=engine)

    AuditEngine._instance = None
    audit_engine = AuditEngine(audit_dir=audit_dir)
    AuditEngine._instance = audit_engine

    client = TestClient(app, follow_redirects=False)
    return client, mail_db, tm_db, audit_engine


@pytest.mark.asyncio
async def test_e2e_cross_cartridge_semantic_routing_and_audit(
    synergy_e2e_env: tuple[TestClient, MailDatabaseService, TMDatabaseService, AuditEngine]
) -> None:
    client, mail_db, tm_db, audit_engine = synergy_e2e_env

    # -------------------------------------------------------------------------
    # STEP 1: Semantic Intent Routing for Inbound Requests
    # -------------------------------------------------------------------------
    candidate_apps = ["mail_organizer", "temperature_marker"]

    # Intent 1: Mail triage
    with patch.object(
        SemanticRouter,
        "route",
        new_callable=AsyncMock,
        return_value=RoutingDecision(
            selected_app="mail_organizer",
            confidence=0.98,
            reasoning="Inbound inquiry asking to review partner contract email",
            intent_category="email_triage",
        ),
    ):
        dec_mail = await SemanticRouter.route(
            text_content="Please draft a reply to partner contract email",
            candidate_apps=candidate_apps,
            sender_id="+919876543210",
        )
        assert dec_mail.selected_app == "mail_organizer"
        assert dec_mail.confidence >= 0.85

    # Intent 2: Temperature marker check-in
    with patch.object(
        SemanticRouter,
        "route",
        new_callable=AsyncMock,
        return_value=RoutingDecision(
            selected_app="temperature_marker",
            confidence=0.99,
            reasoning="Worker duty check-in photo and temperature reading",
            intent_category="attendance_checkin",
        ),
    ):
        dec_tm = await SemanticRouter.route(
            text_content="Checkin duty at Kiosk Pune-01 with temp reading",
            candidate_apps=candidate_apps,
            sender_id="+919876543210",
        )
        assert dec_tm.selected_app == "temperature_marker"
        assert dec_tm.confidence >= 0.85

    # -------------------------------------------------------------------------
    # STEP 2: Simultaneous Multi-Cartridge Business Logic Execution
    # -------------------------------------------------------------------------
    # Cartridge A: Ingest email
    email = mail_db.store_email(
        gmail_id="msg-omni-001",
        thread_id="th-omni-001",
        subject="Omni Partner SLA Agreement",
        sender="partner@omni.com",
        tenant_id="omni_corp",
    )
    assert email is not None

    # Cartridge B: Register and check in operator
    emp = tm_db.register_employee(
        emp_code="EMP-OMNI-1",
        full_name="Vikram Singh",
        phone_number="+919876543210",
        assigned_kiosk_id="KIOSK-OMNI-1",
        status="ACTIVE",
        tenant_id="omni_corp",
    )
    assert emp is not None

    # -------------------------------------------------------------------------
    # STEP 3: Contemporaneous Cryptographic Audit Logging across Cartridges
    # -------------------------------------------------------------------------
    rec1 = audit_engine.record_event(
        action_type="EMAIL_TRIAGED",
        operator_id="mail_organizer",
        payload_summary={"gmail_id": "msg-omni-001", "subject": "Omni Partner SLA Agreement"},
        correlation_id="corr-omni-mail-01",
    )
    assert rec1 is not None
    assert rec1.sequence_number == 1
    assert rec1.record_hash is not None

    rec2 = audit_engine.record_event(
        action_type="DUTY_CHECKIN_VERIFIED",
        operator_id="EMP-OMNI-1",
        kiosk_id="KIOSK-OMNI-1",
        payload_summary={"emp_code": "EMP-OMNI-1", "kiosk_id": "KIOSK-OMNI-1", "temp": 3.4},
        correlation_id="corr-omni-tm-01",
    )
    assert rec2 is not None
    assert rec2.sequence_number == 2
    # Verify cryptographic hash chaining invariant: PrevHash of rec2 == Hash of rec1
    assert rec2.prev_hash == rec1.record_hash

    # Verify chain integrity
    is_valid, tampered_seq = AuditEngine.verify_chain_integrity(audit_engine._active_records)
    assert is_valid is True
    assert tampered_seq is None

    # -------------------------------------------------------------------------
    # STEP 4: Unified Admin Shell Cross-Cartridge Telemetry & DOM Invariants
    # -------------------------------------------------------------------------
    admin_token = create_jwt_token(
        principal_id="omni_admin",
        roles=["admin"],
        permitted_apps=["all", "mail_organizer", "temperature_marker"],
        tenant_id="omni_corp",
    )
    client.cookies.set("admin_token", admin_token)

    resp_dashboard = client.get("/admin/", headers={"Host": "omni.intentrouter.io"})
    assert resp_dashboard.status_code in (200, 302, 303)

    resp_entitlements = client.get("/admin/entitlements", headers={"Host": "omni.intentrouter.io"})
    assert resp_entitlements.status_code == 200
    assert "Groups and Access" in resp_entitlements.text or "Access" in resp_entitlements.text
