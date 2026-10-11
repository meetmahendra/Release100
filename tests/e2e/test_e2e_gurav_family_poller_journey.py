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
E2E Journey: Gurav Family Multi-User Email Poller Configuration & Agentic WhatsApp Assistant.

Validates the full real-world production lifecycle:
1. Workspace Provisioning: Tenant 'tenant_gurav' provisioned with Admin (Mahendra) and Users (Dipali, Alka).
2. Clean-Slate Admin UI: Admin accesses /accounts, verifying actionable DOM controls for all members.
3. Cadence & Window Setup: Admin assigns Dipali (5m, 24x7), Alka (15m, 09:00-18:00), and Mahendra (15m, 08:00-20:00).
4. Selective Poller Pause: Admin pauses Alka's poller; Alka status shows PAUSED while Dipali & Mahendra remain ACTIVE.
5. Smart Background Execution: Background worker polls Dipali & Mahendra, cleanly skipping paused Alka.
6. Strict Deduplication: Identical Gmail IDs in successive cycles are skipped with zero duplicate database rows.
7. On-Demand Sync: 1-click 'Poll Now' successfully synchronizes inbox immediately.
8. Dynamic Agentic WhatsApp Assistant: Natural language queries return live context-grounded responses instead of static command lists.
9. Workspace Master Switch: Toggling master pause halts polling tenant-wide.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.database.models import (
    Base as MailBase,
    EmailClassification,
    EmailRecord,
    UserPollerConfig,
    WorkspacePollerConfig,
)
from apps.mail_organizer.pm.task_manager import PMTaskManager
from apps.mail_organizer.services.poll_worker import MailPollWorker
from apps.mail_organizer.services.whatsapp_handler import MailOrganizerWhatsAppHandler
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.db.base import Base as IdentityBase
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.identity.models import PlatformUser, Tenant, TenantDomain
from core_platform.app.identity.service import UserIdentityService
from core_platform.main import app


@pytest.fixture
def gurav_family_env(tmp_path: Path) -> Generator[Tuple[TestClient, MailDatabaseService, MailOrganizerWhatsAppHandler, List[PlatformUser]], None, None]:
    """Initialize isolated multi-user database environment for the Gurav Family E2E Journey."""
    db_file = tmp_path / "gurav_family_e2e.db"
    db_url = f"sqlite:///{db_file}"

    DatabaseManager.reset_instance()
    UserIdentityService.reset_instance()
    db_mgr = DatabaseManager.get_instance(database_url=db_url)
    engine = db_mgr.get_engine()
    IdentityBase.metadata.create_all(bind=engine)
    MailBase.metadata.create_all(bind=engine)
    session_maker = sessionmaker(bind=engine)

    now = datetime.now(timezone.utc)

    # 1. Provision Tenant and Users
    with session_maker() as session:
        tenant = Tenant(
            id="tenant_gurav",
            name="Gurav Family Workspace",
            license_tier="ENTERPRISE",
            storage_region="ap-south-1",
        )
        tenant_domain = TenantDomain(
            tenant_id="tenant_gurav",
            domain_name="gurav.family",
        )
        session.merge(tenant)
        session.merge(tenant_domain)

        user_mahendra = PlatformUser(
            id=101,
            tenant_id="tenant_gurav",
            phone_number="+919800000001",
            full_name="Mahendra Gurav",
            role="ADMIN",
            status="ACTIVE",
            allowed_cartridges_json='["mail_organizer"]',
            email="mahendra@gurav.family",
            google_email="mahendra@gurav.family",
            encrypted_oauth_tokens="mock_oauth_tokens_mahendra",
            user_secret_salt="salt_mahendra_123",
            last_whatsapp_interaction_at=now,
            created_at=now,
            updated_at=now,
        )
        user_dipali = PlatformUser(
            id=102,
            tenant_id="tenant_gurav",
            phone_number="+919800000002",
            full_name="Dipali Gurav",
            role="MEMBER",
            status="ACTIVE",
            allowed_cartridges_json='["mail_organizer"]',
            email="dipali@gurav.family",
            google_email="dipali@gurav.family",
            encrypted_oauth_tokens="mock_oauth_tokens_dipali",
            user_secret_salt="salt_dipali_456",
            last_whatsapp_interaction_at=now,
            created_at=now,
            updated_at=now,
        )
        user_alka = PlatformUser(
            id=103,
            tenant_id="tenant_gurav",
            phone_number="+919800000003",
            full_name="Alka Gurav",
            role="MEMBER",
            status="ACTIVE",
            allowed_cartridges_json='["mail_organizer"]',
            email="alka@gurav.family",
            google_email="alka@gurav.family",
            encrypted_oauth_tokens="mock_oauth_tokens_alka",
            user_secret_salt="salt_alka_789",
            last_whatsapp_interaction_at=now,
            created_at=now,
            updated_at=now,
        )
        session.merge(user_mahendra)
        session.merge(user_dipali)
        session.merge(user_alka)
        session.commit()

    MailDatabaseService._instance = None
    mail_db = MailDatabaseService.get_instance(engine=engine)
    pm_mgr = PMTaskManager(db_service=mail_db)
    whatsapp_handler = MailOrganizerWhatsAppHandler(db_service=mail_db, pm_manager=pm_mgr)

    # Sync route singleton
    from apps.mail_organizer.ui import routes as mail_routes
    mail_routes._db_service = mail_db

    users = [user_mahendra, user_dipali, user_alka]

    client = TestClient(app, follow_redirects=False)
    admin_token = create_jwt_token(
        principal_id="101",
        roles=["admin", "tenant_admin"],
        permitted_apps=["all", "mail_organizer"],
        tenant_id="tenant_gurav",
    )
    client.cookies.set("admin_token", admin_token)

    yield client, mail_db, whatsapp_handler, users


@pytest.mark.asyncio
async def test_e2e_gurav_family_poller_and_agentic_lifecycle(
    gurav_family_env: Tuple[TestClient, MailDatabaseService, MailOrganizerWhatsAppHandler, List[PlatformUser]],
) -> None:
    """Full end-to-end journey verifying customer admin controls and agentic assistant."""
    client, mail_db, whatsapp_handler, users = gurav_family_env
    user_mahendra, user_dipali, user_alka = users

    # =========================================================================
    # STEP 1: Admin Verifies Accounts Screen on Clean Slate
    # =========================================================================
    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis:
        mock_service = MagicMock()
        mock_service.list_users.return_value = users
        mock_service.get_user_by_id.side_effect = lambda uid: next((u for u in users if u.id == uid), None)
        mock_uis.return_value = mock_service

        res_accounts = client.get("/admin/apps/mail-organizer/accounts")
        assert res_accounts.status_code == 200
        html = res_accounts.text

        # Verify Actionable DOM Invariants for all members
        assert "Mahendra Gurav" in html
        assert "Dipali Gurav" in html
        assert "Alka Gurav" in html
        assert 'id="btn-toggle-workspace"' in html
        assert 'action="/admin/apps/mail-organizer/accounts/users/102/poll-now"' in html
        assert 'action="/admin/apps/mail-organizer/accounts/users/103/toggle"' in html

    # =========================================================================
    # STEP 2: Customer Admin Configures Cadence & Active Windows
    # =========================================================================
    # Dipali: 5 min (300s), 24x7
    post_dipali = client.post(
        "/admin/apps/mail-organizer/accounts/users/102/config",
        data={"poll_interval_seconds": "300", "active_window": "24x7"},
    )
    assert post_dipali.status_code in (302, 303)

    # Alka: 15 min (900s), Work: 09:00-18:00
    post_alka = client.post(
        "/admin/apps/mail-organizer/accounts/users/103/config",
        data={"poll_interval_seconds": "900", "active_window": "09:00-18:00"},
    )
    assert post_alka.status_code in (302, 303)

    # Mahendra: 15 min (900s), Extended: 08:00-20:00
    post_mahendra = client.post(
        "/admin/apps/mail-organizer/accounts/users/101/config",
        data={"poll_interval_seconds": "900", "active_window": "08:00-20:00"},
    )
    assert post_mahendra.status_code in (302, 303)

    # Verify configs persisted in DB
    cfg_dipali = mail_db.get_user_poller_config(user_id=102, tenant_id="tenant_gurav")
    assert cfg_dipali is not None
    assert cfg_dipali.poll_interval_seconds == 300
    assert cfg_dipali.active_window == "24x7"

    cfg_alka = mail_db.get_user_poller_config(user_id=103, tenant_id="tenant_gurav")
    assert cfg_alka is not None
    assert cfg_alka.poll_interval_seconds == 900
    assert cfg_alka.active_window == "09:00-18:00"

    # =========================================================================
    # STEP 3: Admin Pauses Alka's Poller (Vacation / Leave)
    # =========================================================================
    toggle_alka = client.post("/admin/apps/mail-organizer/accounts/users/103/toggle")
    assert toggle_alka.status_code in (302, 303)

    cfg_alka_paused = mail_db.get_user_poller_config(user_id=103, tenant_id="tenant_gurav")
    assert cfg_alka_paused is not None
    assert cfg_alka_paused.is_poller_enabled is False

    # Verify Dipali remains active
    cfg_dipali_active = mail_db.get_user_poller_config(user_id=102, tenant_id="tenant_gurav")
    assert cfg_dipali_active is not None
    assert cfg_dipali_active.is_poller_enabled is True

    # =========================================================================
    # STEP 4: Background Poller Worker Cycle with Deduplication
    # =========================================================================
    worker = MailPollWorker(root_dir=Path("."))
    worker.db_service = mail_db

    # Mock inbound threads: 1 for Dipali, 1 for Alka
    mock_dipali_email = {
        "gmail_id": "GMAIL-DIPALI-001",
        "thread_id": "TH-DIPALI-001",
        "sender": "school@academy.edu",
        "subject": "Parent Teacher Conference Schedule",
        "body": "Dear Parents, please select your time slot for the upcoming conference.",
        "snippet": "Parent teacher conference schedule selection...",
    }

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis, \
         patch("apps.mail_organizer.connectors.gmail_connector.GmailConnector.fetch_unread_threads") as mock_fetch, \
         patch("apps.mail_organizer.connectors.auth_manager.get_user_access_token", return_value="mock_valid_token"):

        mock_uis_inst = MagicMock()
        mock_uis_inst.list_users.return_value = users
        mock_uis.return_value = mock_uis_inst
        mock_fetch.return_value = [mock_dipali_email]

        # Cycle 1: Poll execution
        count = await worker.poll_once()
        assert count >= 1

        # Check Alka was skipped (last_polled_at remains None)
        alka_check = mail_db.get_user_poller_config(user_id=103, tenant_id="tenant_gurav")
        assert alka_check is not None
        assert alka_check.last_polled_at is None

        # Check Dipali was polled
        dipali_check = mail_db.get_user_poller_config(user_id=102, tenant_id="tenant_gurav")
        assert dipali_check is not None
        assert dipali_check.total_cycles >= 1

        # Cycle 2: Strict Deduplication (same thread arrives again)
        count_cycle_2 = await worker.poll_once()
        assert count_cycle_2 == 0  # Deduplication skips already ingested message

    # =========================================================================
    # STEP 5: On-Demand 1-Click Sync for Dipali
    # =========================================================================
    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis, \
         patch("apps.mail_organizer.services.poller_manager.MailPollerManager.poll_user_now", new_callable=AsyncMock) as mock_poll_now:
        mock_uis_inst = MagicMock()
        mock_uis_inst.get_user_by_id.side_effect = lambda uid: next((u for u in users if u.id == uid), None)
        mock_uis.return_value = mock_uis_inst
        mock_poll_now.return_value = {"success": True, "emails_processed": 0}
        post_sync = client.post(
            "/admin/apps/mail-organizer/accounts/users/102/poll-now",
            headers={"Accept": "application/json"},
        )
        assert post_sync.status_code == 200
        assert post_sync.json()["success"] is True

    # =========================================================================
    # STEP 6: Dynamic Agentic WhatsApp Assistant
    # =========================================================================
    # A. Dipali asks: "is poller running?"
    dipali_context: Dict[str, Any] = {
        "sender_phone": user_dipali.phone_number,
        "user": user_dipali,
        "user_id": user_dipali.id,
        "tenant_id": user_dipali.tenant_id,
        "base_url": "http://localhost:8000",
    }
    dipali_status_msg = {"text": {"body": "is the email poller running?"}}
    res_status = await whatsapp_handler.dispatch(dipali_status_msg, dipali_context)
    assert "*Workspace Master Switch:* 🟢 Active" in res_status
    assert "*Your Personal Poller:* 🟢 Active" in res_status
    assert "Every 5 minutes" in res_status
    assert "Available Commands:" not in res_status

    # B. Alka asks: "poller status"
    alka_context: Dict[str, Any] = {
        "sender_phone": user_alka.phone_number,
        "user": user_alka,
        "user_id": user_alka.id,
        "tenant_id": user_alka.tenant_id,
        "base_url": "http://localhost:8000",
    }
    alka_status_msg = {"text": {"body": "poller status"}}
    res_alka = await whatsapp_handler.dispatch(alka_status_msg, alka_context)
    assert "*Your Personal Poller:* ⏸️ Paused" in res_alka

    # C. Mahendra checks urgent emails
    mahendra_context: Dict[str, Any] = {
        "sender_phone": user_mahendra.phone_number,
        "user": user_mahendra,
        "user_id": user_mahendra.id,
        "tenant_id": user_mahendra.tenant_id,
        "base_url": "http://localhost:8000",
    }
    # Ingest an urgent email for Mahendra
    mail_db.store_email(
        gmail_id="GMAIL-URGENT-FEES",
        thread_id="TH-FEES-001",
        subject="URGENT: Annual Registration Fee Deadline Tomorrow",
        sender="bursar@university.edu",
        body="Please finalize payment before 5:00 PM tomorrow to avoid cancellation.",
        labels_applied="AI_TRIAGE/Urgent",
        tenant_id="tenant_gurav",
    )
    mail_db.store_classification(
        gmail_id="GMAIL-URGENT-FEES",
        category="Urgent",
        confidence_score=0.99,
        urgency_score=9,
        reasoning="Time-sensitive financial deadline alert.",
        responsibility_role="Admin",
        tenant_id="tenant_gurav",
    )

    urgent_msg = {"text": {"body": "any urgent emails?"}}
    res_urgent = await whatsapp_handler.dispatch(urgent_msg, mahendra_context)
    assert "Urgent & Critical Emails" in res_urgent
    assert "Annual Registration Fee Deadline" in res_urgent

    # D. Dipali asks conversational question answered by Gemini LLM
    mock_llm_ans = {
        "reply": "🎓 The academy sent the conference schedule for next week. You can reply `summary` for details."
    }
    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(return_value=mock_llm_ans)

    with patch("core_platform.app.llm.gateway.get_platform_llm_gateway", return_value=mock_gateway):
        query_msg = {"text": {"body": "What did the academy send regarding conference?"}}
        res_query = await whatsapp_handler.dispatch(query_msg, dipali_context)
        assert "The academy sent the conference schedule" in res_query
        assert "Available Commands:" not in res_query

    # E. Explicit Help Command
    help_res = await whatsapp_handler.dispatch({"text": {"body": "help"}}, dipali_context)
    assert "Available Commands:" in help_res
    assert "• *poll now*" in help_res
    assert "• *poller status*" in help_res

    # =========================================================================
    # STEP 7: Customer Admin Workspace Master Pause
    # =========================================================================
    toggle_ws = client.post("/admin/apps/mail-organizer/accounts/workspace/toggle")
    assert toggle_ws.status_code in (302, 303)

    ws_check = mail_db.get_workspace_poller_config(tenant_id="tenant_gurav")
    assert ws_check.is_master_enabled is False

    # Background poller halts for entire workspace
    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis:
        mock_uis_inst = MagicMock()
        mock_uis_inst.list_users.return_value = users
        mock_uis.return_value = mock_uis_inst

        # Ingest new email thread
        new_threads = [{
            "gmail_id": "GMAIL-DIPALI-002",
            "thread_id": "TH-DIPALI-002",
            "sender": "club@sports.org",
            "subject": "Weekend Practice",
            "body": "Practice at 9am.",
            "snippet": "Weekend practice schedule...",
        }]
        with patch("apps.mail_organizer.connectors.gmail_connector.GmailConnector.fetch_unread_threads", return_value=new_threads):
            count_paused = await worker.poll_once()
            assert count_paused == 0  # Master switch blocks all tenant user checks
