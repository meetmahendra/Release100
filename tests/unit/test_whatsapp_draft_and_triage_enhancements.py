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
Unit tests for WhatsApp 1-Click Draft Sending, Out-of-Office Triage Filtering,
and Timezone-Aware Calendar Availability.
Validates:
1. WhatsApp drafts listing with 1-click action commands.
2. Direct draft dispatching and lifecycle update over WhatsApp (`send <draft_id>`).
3. Draft discarding over WhatsApp (`discard <draft_id>`).
4. Automated detection and suppression of Out-of-Office (OOO) and Auto-Replies to @FYI.
5. Timezone-aware calendar meeting proposal synthesis.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from apps.mail_organizer.connectors.calendar_connector import GoogleCalendarConnector
from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.nodes.classify_node import classify_node
from apps.mail_organizer.graph.nodes.pre_check_node import pre_check_node
from apps.mail_organizer.graph.state import MailOrganizerState
from apps.mail_organizer.pm.task_manager import PMTaskManager
from apps.mail_organizer.services.whatsapp_handler import MailOrganizerWhatsAppHandler
from core_platform.app.identity.models import PlatformUser


@pytest.fixture
def db_service(tmp_path: Path) -> MailDatabaseService:
    """Create isolated SQLite database for testing."""
    db_file = tmp_path / "test_whatsapp_drafts.db"
    return MailDatabaseService(db_url=f"sqlite:///{db_file}")


@pytest.fixture
def whatsapp_handler(db_service: MailDatabaseService) -> MailOrganizerWhatsAppHandler:
    """Initialize handler with test database and task manager."""
    pm_mgr = PMTaskManager(db_service=db_service)
    return MailOrganizerWhatsAppHandler(db_service=db_service, pm_manager=pm_mgr)


@pytest.fixture
def mock_user() -> PlatformUser:
    """Active test user with secret salt."""
    now = datetime.now(timezone.utc)
    return PlatformUser(
        id="user_whatsapp_test",
        phone_number="+15559876543",
        tenant_id="tenant_alpha",
        full_name="Alice WhatsApp",
        role="member",
        status="active",
        allowed_cartridges_json='["mail_organizer"]',
        encrypted_oauth_tokens="mock_encrypted_tokens_alice",
        user_secret_salt="alice_secret_salt_12345",
        last_whatsapp_interaction_at=now.isoformat(),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )


@pytest.mark.asyncio
async def test_staged_drafts_listing_and_send_command(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    db_service: MailDatabaseService,
    mock_user: PlatformUser,
) -> None:
    """Verify drafts listing renders actionable 1-click command and send executes draft dispatch."""
    # 1. Stage a draft
    draft_record = db_service.store_draft(
        gmail_id="GMAIL-DRAFT-100",
        thread_id="THREAD-100",
        recipient="partner@company.com",
        subject="Re: Strategic Partnership Proposal",
        body="Thank you for your proposal. We are pleased to proceed with the terms discussed.",
        user_salt=mock_user.user_secret_salt,
    )
    draft_id = draft_record.id

    context = {
        "sender_phone": mock_user.phone_number,
        "user": mock_user,
        "user_id": mock_user.id,
        "tenant_id": mock_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    # 2. Test 'drafts' listing command
    drafts_msg = {"text": {"body": "drafts"}}
    list_response = await whatsapp_handler.dispatch(drafts_msg, context)
    assert f"Draft #{draft_id}" in list_response
    assert "partner@company.com" in list_response
    assert f"send {draft_id}" in list_response

    # 3. Test 'send <draft_id>' command with mock Gmail dispatch
    send_msg = {"text": {"body": f"send {draft_id}"}}
    mock_send_res = {"id": "MSG-SENT-777", "status": "SENT"}

    with patch.object(GmailConnector, "send_message", new_callable=AsyncMock, return_value=mock_send_res), \
         patch("apps.mail_organizer.connectors.auth_manager.get_user_access_token", return_value="mock_access_tok"):
        
        send_response = await whatsapp_handler.dispatch(send_msg, context)
        assert "Email Sent Successfully" in send_response
        assert "partner@company.com" in send_response
        assert "MSG-SENT-777" in send_response

        # Verify DB status updated to SENT
        draft_in_db = db_service.get_draft(draft_id)
        assert draft_in_db is not None
        assert draft_in_db["status"] == "SENT"


@pytest.mark.asyncio
async def test_discard_draft_command(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    db_service: MailDatabaseService,
    mock_user: PlatformUser,
) -> None:
    """Verify discard command transitions draft status to DISCARDED."""
    draft_record = db_service.store_draft(
        gmail_id="GMAIL-DRAFT-200",
        thread_id="THREAD-200",
        recipient="unwanted@spam.com",
        subject="Re: Discard Test",
        body="Discard this reply.",
        user_salt=mock_user.user_secret_salt,
    )
    draft_id = draft_record.id

    context = {
        "sender_phone": mock_user.phone_number,
        "user": mock_user,
        "base_url": "http://localhost:8000",
    }

    discard_msg = {"text": {"body": f"discard {draft_id}"}}
    discard_response = await whatsapp_handler.dispatch(discard_msg, context)
    assert "discarded" in discard_response.lower()

    draft_in_db = db_service.get_draft(draft_id)
    assert draft_in_db is not None
    assert draft_in_db["status"] == "DISCARDED"


@pytest.mark.asyncio
async def test_out_of_office_and_auto_reply_triage() -> None:
    """Verify that OOO and auto-replies are categorized as @FYI with minimum urgency."""
    # 1. Subject-based OOO
    state_ooo: MailOrganizerState = {
        "gmail_id": "GMAIL-OOO-1",
        "thread_id": "THREAD-OOO-1",
        "sender": "colleague@company.com",
        "subject": "Automatic reply: Out of Office until next week",
        "body": "I am currently away on annual leave with limited access to email.",
    }

    state_checked = await pre_check_node(state_ooo)
    assert state_checked.get("is_auto_reply") is True

    final_state = await classify_node(state_checked)
    assert final_state.get("category") == "@FYI"
    assert final_state.get("urgency_score") == 1
    assert final_state.get("is_reply_necessary") is False

    # 2. Body-based OOO
    state_ooo_body: MailOrganizerState = {
        "gmail_id": "GMAIL-OOO-2",
        "thread_id": "THREAD-OOO-2",
        "sender": "vendor@partner.com",
        "subject": "Status Update",
        "body": "Thank you for reaching out. I am currently out of the office returning Monday.",
    }

    state_checked2 = await pre_check_node(state_ooo_body)
    assert state_checked2.get("is_auto_reply") is True

    final_state2 = await classify_node(state_checked2)
    assert final_state2.get("category") == "@FYI"
    assert final_state2.get("urgency_score") == 1
    assert final_state2.get("is_reply_necessary") is False


@pytest.mark.asyncio
async def test_calendar_timezone_proposal_synthesis() -> None:
    """Verify that GoogleCalendarConnector formats candidate slots with user timezone."""
    calendar = GoogleCalendarConnector(mock_mode=True)
    
    # UTC synthesis
    proposal_utc = await calendar.synthesize_availability_proposal(user_timezone="UTC")
    assert "10:00 AM" in proposal_utc

    # Asia/Kolkata timezone synthesis
    proposal_ist = await calendar.synthesize_availability_proposal(user_timezone="Asia/Kolkata")
    assert "Asia/Kolkata" in proposal_ist
    assert "10:00 AM Asia/Kolkata" in proposal_ist
