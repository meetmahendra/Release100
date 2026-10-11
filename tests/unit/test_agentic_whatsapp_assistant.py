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
Unit tests for Dynamic Agentic WhatsApp Assistant and Poller Controls.

Adheres strictly to GEES v3.1:
- Zero shallow status 200 tests.
- High-fidelity verification of agentic conversational answers vs static menu.
- Verifies on-demand sync, cadence inquiries, urgent triage, and search over WhatsApp.
- 100% type completeness under mypy --strict.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.pm.task_manager import PMTaskManager
from apps.mail_organizer.services.whatsapp_handler import MailOrganizerWhatsAppHandler
from core_platform.app.identity.models import PlatformUser


@pytest.fixture
def db_service(tmp_path: Path) -> MailDatabaseService:
    """Create isolated SQLite database for testing."""
    db_file = tmp_path / "test_whatsapp_agentic.db"
    return MailDatabaseService(db_url=f"sqlite:///{db_file}")


@pytest.fixture
def whatsapp_handler(db_service: MailDatabaseService) -> MailOrganizerWhatsAppHandler:
    """Initialize handler with test database and task manager."""
    pm_mgr = PMTaskManager(db_service=db_service)
    return MailOrganizerWhatsAppHandler(db_service=db_service, pm_manager=pm_mgr)


@pytest.fixture
def mock_admin_user() -> PlatformUser:
    """Active customer admin test user."""
    now = datetime.now(timezone.utc)
    return PlatformUser(
        id=101,
        phone_number="+15550001111",
        tenant_id="tenant_gurav",
        full_name="Mahendra Gurav",
        role="ADMIN",
        status="ACTIVE",
        allowed_cartridges_json='["mail_organizer"]',
        email="mahendra@gurav.local",
        google_email="mahendra@gurav.local",
        encrypted_oauth_tokens="mock_encrypted_tokens_mahendra",
        user_secret_salt="mahendra_secret_salt_12345",
        last_whatsapp_interaction_at=now.isoformat(),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )


@pytest.mark.asyncio
async def test_poller_status_command(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    db_service: MailDatabaseService,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify 'poller status' returns real workspace & user poller configurations."""
    # Seed workspace config and user config
    db_service.set_workspace_poller_status(is_enabled=True, tenant_id="tenant_gurav")
    db_service.upsert_user_poller_config(
        user_id=101,
        email="mahendra@gurav.local",
        is_enabled=True,
        poll_interval_seconds=900,
        active_window="08:00-20:00",
        tenant_id="tenant_gurav",
    )
    db_service.record_user_poll_run(user_id=101, emails_fetched=7, tenant_id="tenant_gurav")

    context: Dict[str, Any] = {
        "sender_phone": mock_admin_user.phone_number,
        "user": mock_admin_user,
        "user_id": mock_admin_user.id,
        "tenant_id": mock_admin_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    msg: Dict[str, Any] = {"text": {"body": "poller status"}}
    res = await whatsapp_handler.dispatch(msg, context)

    assert "Email Poller & Sync Status" in res
    assert "*Workspace Master Switch:* 🟢 Active" in res
    assert "*Your Personal Poller:* 🟢 Active" in res
    assert "Every 15 minutes" in res
    assert "08:00-20:00" in res
    assert "*Total Sync Cycles:* 1" in res
    assert "*Total Emails Processed:* 7" in res
    assert "poll now" in res


@pytest.mark.asyncio
async def test_poll_now_on_demand_sync(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify 'poll now' triggers on-demand sync via poller manager."""
    context: Dict[str, Any] = {
        "sender_phone": mock_admin_user.phone_number,
        "user": mock_admin_user,
        "user_id": mock_admin_user.id,
        "tenant_id": mock_admin_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    msg: Dict[str, Any] = {"text": {"body": "poll now"}}

    with patch("apps.mail_organizer.services.poller_manager.MailPollerManager.poll_user_now", new_callable=AsyncMock) as mock_poll:
        mock_poll.return_value = {"emails_processed": 3}
        res = await whatsapp_handler.dispatch(msg, context)
        assert mock_poll.called
        assert "On-Demand Inbox Sync Complete" in res
        assert "*New Emails Processed:* 3" in res
        assert "*Target User:* `101`" in res


@pytest.mark.asyncio
async def test_toggle_user_poller_pause_and_resume(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    db_service: MailDatabaseService,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify user can pause and resume their poller via WhatsApp."""
    context: Dict[str, Any] = {
        "sender_phone": mock_admin_user.phone_number,
        "user": mock_admin_user,
        "user_id": mock_admin_user.id,
        "tenant_id": mock_admin_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    # 1. Pause poller
    pause_msg: Dict[str, Any] = {"text": {"body": "pause poller"}}
    pause_res = await whatsapp_handler.dispatch(pause_msg, context)
    assert "paused ⏸️" in pause_res

    cfg = db_service.get_user_poller_config(user_id=101, tenant_id="tenant_gurav")
    assert cfg is not None
    assert cfg.is_poller_enabled is False

    # 2. Resume poller
    resume_msg: Dict[str, Any] = {"text": {"body": "resume poller"}}
    resume_res = await whatsapp_handler.dispatch(resume_msg, context)
    assert "resumed and active 🟢" in resume_res

    cfg_after = db_service.get_user_poller_config(user_id=101, tenant_id="tenant_gurav")
    assert cfg_after is not None
    assert cfg_after.is_poller_enabled is True


@pytest.mark.asyncio
async def test_urgent_emails_command(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    db_service: MailDatabaseService,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify 'urgent' returns high-urgency items, and 'all clear' when empty."""
    context: Dict[str, Any] = {
        "sender_phone": mock_admin_user.phone_number,
        "user": mock_admin_user,
        "user_id": mock_admin_user.id,
        "tenant_id": mock_admin_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    # 1. When empty
    res_empty = await whatsapp_handler.dispatch({"text": {"body": "urgent"}}, context)
    assert "No Urgent Emails" in res_empty

    # 2. Add an urgent email and a normal email
    db_service.store_email(
        gmail_id="MSG-URGENT-1",
        thread_id="THREAD-URGENT-1",
        subject="CRITICAL: Server Outage in Production",
        sender="devops@company.com",
        body="Production database is down, immediate investigation needed.",
        labels_applied="AI_TRIAGE/Urgent",
        tenant_id="tenant_gurav",
    )
    db_service.store_classification(
        gmail_id="MSG-URGENT-1",
        category="Urgent",
        confidence_score=0.98,
        urgency_score=10,
        reasoning="Critical server outage alert.",
        responsibility_role="CTO",
        tenant_id="tenant_gurav",
    )

    db_service.store_email(
        gmail_id="MSG-NORMAL-2",
        thread_id="THREAD-NORMAL-2",
        subject="Weekly Newsletter",
        sender="news@newsletter.com",
        body="Here is your weekly summary of tech news.",
        labels_applied="AI_TRIAGE/General",
        tenant_id="tenant_gurav",
    )
    db_service.store_classification(
        gmail_id="MSG-NORMAL-2",
        category="General",
        confidence_score=0.90,
        urgency_score=2,
        reasoning="Routine newsletter.",
        responsibility_role="Reader",
        tenant_id="tenant_gurav",
    )

    res_urgent = await whatsapp_handler.dispatch({"text": {"body": "urgent"}}, context)
    assert "Urgent & Critical Emails" in res_urgent
    assert "CRITICAL: Server Outage" in res_urgent
    assert "devops@company.com" in res_urgent
    assert "Weekly Newsletter" not in res_urgent


@pytest.mark.asyncio
async def test_search_emails_command(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    db_service: MailDatabaseService,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify natural search queries locate relevant emails."""
    db_service.store_email(
        gmail_id="MSG-SEARCH-1",
        thread_id="THREAD-SEARCH-1",
        subject="Vendor Invoice #99824 for Q3",
        sender="accounting@acme.com",
        body="Please find attached invoice #99824 for renewal.",
        labels_applied="AI_TRIAGE/Finance",
        tenant_id="tenant_gurav",
    )
    db_service.store_classification(
        gmail_id="MSG-SEARCH-1",
        category="Finance",
        confidence_score=0.95,
        urgency_score=6,
        reasoning="Vendor payment invoice.",
        responsibility_role="Finance Lead",
        tenant_id="tenant_gurav",
    )

    context: Dict[str, Any] = {
        "sender_phone": mock_admin_user.phone_number,
        "user": mock_admin_user,
        "user_id": mock_admin_user.id,
        "tenant_id": mock_admin_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    search_msg: Dict[str, Any] = {"text": {"body": "search invoice"}}
    res = await whatsapp_handler.dispatch(search_msg, context)
    assert "Emails matching \"invoice\"" in res
    assert "Vendor Invoice #99824" in res
    assert "accounting@acme.com" in res


@pytest.mark.asyncio
async def test_conversational_agentic_query_with_llm(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    db_service: MailDatabaseService,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify natural questions use Gemini LLM and return dynamic smart answers, NOT static command list."""
    context: Dict[str, Any] = {
        "sender_phone": mock_admin_user.phone_number,
        "user": mock_admin_user,
        "user_id": mock_admin_user.id,
        "tenant_id": mock_admin_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    mock_llm_response = {
        "reply": "📅 You have an executive meeting with the design team tomorrow at 2:00 PM to review the new UI mockups."
    }

    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(return_value=mock_llm_response)

    with patch("core_platform.app.llm.gateway.get_platform_llm_gateway", return_value=mock_gateway):
        query_msg: Dict[str, Any] = {"text": {"body": "What meetings do I have scheduled with design?"}}
        res = await whatsapp_handler.dispatch(query_msg, context)

        # Assert LLM was called with structured context
        assert mock_gateway.generate.called
        call_kwargs = mock_gateway.generate.call_args[1]
        assert call_kwargs["task"] == "text_generation"
        assert "design" in call_kwargs["prompt"]

        # Assert response is the SMART dynamic answer, NOT the static menu!
        assert "You have an executive meeting with the design team" in res
        assert "Available Commands:" not in res


@pytest.mark.asyncio
async def test_conversational_query_fallback_when_llm_fails(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    db_service: MailDatabaseService,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify intelligent context fallback when LLM is offline, NEVER returning static menu for questions."""
    db_service.store_email(
        gmail_id="MSG-FALLBACK-1",
        thread_id="THREAD-FALLBACK-1",
        subject="Important Client Followup",
        sender="sarah@client.com",
        body="Following up on our agreement.",
        labels_applied="AI_TRIAGE/Client",
        tenant_id="tenant_gurav",
    )
    db_service.store_classification(
        gmail_id="MSG-FALLBACK-1",
        category="Client",
        confidence_score=0.91,
        urgency_score=8,
        reasoning="Key client inquiry.",
        responsibility_role="Account Exec",
        tenant_id="tenant_gurav",
    )

    context: Dict[str, Any] = {
        "sender_phone": mock_admin_user.phone_number,
        "user": mock_admin_user,
        "user_id": mock_admin_user.id,
        "tenant_id": mock_admin_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    mock_gateway = MagicMock()
    # Simulate LLM failure or empty response
    mock_gateway.generate = AsyncMock(return_value=None)

    with patch("core_platform.app.llm.gateway.get_platform_llm_gateway", return_value=mock_gateway):
        # 1. Greeting
        greeting_res = await whatsapp_handler.dispatch({"text": {"body": "Good morning!"}}, context)
        assert "Hello Mahendra Gurav" in greeting_res
        assert "Inbox Overview" in greeting_res
        assert "Available Commands:" not in greeting_res

        # 2. General inquiry
        general_res = await whatsapp_handler.dispatch({"text": {"body": "Can you give me an update on my messages?"}}, context)
        assert "Inbox Status Update for Mahendra Gurav" in general_res
        assert "Important Client Followup" in general_res
        assert "Available Commands:" not in general_res


@pytest.mark.asyncio
async def test_explicit_help_command_renders_menu(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify explicit 'help' returns the full command directory."""
    context: Dict[str, Any] = {
        "sender_phone": mock_admin_user.phone_number,
        "user": mock_admin_user,
        "user_id": mock_admin_user.id,
        "tenant_id": mock_admin_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    help_res = await whatsapp_handler.dispatch({"text": {"body": "help"}}, context)
    assert "AI Email & Calendar Triage Assistant" in help_res
    assert "Available Commands:" in help_res
    assert "• *summary*" in help_res
    assert "• *poll now*" in help_res
    assert "• *poller status*" in help_res
    assert "• *urgent*" in help_res
    assert "• *drafts*" in help_res
    assert "• *tasks*" in help_res


@pytest.mark.asyncio
async def test_poll_now_zero_false_success_when_unauthenticated(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
    mock_admin_user: PlatformUser,
) -> None:
    """Verify 'poll now' NEVER returns false success when Google account is not connected (GEES v3.1)."""
    # Unlinked user
    unlinked_user = PlatformUser(
        id=404,
        phone_number="+15552001703",
        full_name="New Team Member",
        role="employee",
        status="active",
        tenant_id="tenant_gurav",
        allowed_cartridges_json='["mail_organizer"]',
        encrypted_oauth_tokens=None,  # No OAuth tokens
    )

    context: Dict[str, Any] = {
        "sender_phone": unlinked_user.phone_number,
        "user": unlinked_user,
        "user_id": unlinked_user.id,
        "tenant_id": unlinked_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    # When poller manager returns error indicating no linked account
    with patch("apps.mail_organizer.services.poller_manager.MailPollerManager.poll_user_now", new_callable=AsyncMock) as mock_poll:
        mock_poll.return_value = {
            "success": False,
            "message": "User New Team Member has not linked a Google account.",
        }
        res = await whatsapp_handler.dispatch({"text": {"body": "poll now"}}, context)

        assert mock_poll.called
        # MUST NOT report success or "Inbox up to date"
        assert "Inbox up to date" not in res
        assert "On-Demand Inbox Sync Complete" not in res
        # MUST guide user to connect Google account
        assert "Google Account Not Connected" in res
        assert "http://localhost:8000/auth/google/connect?token=" in res
        assert "⏱️" in res


@pytest.mark.asyncio
async def test_poller_status_shows_setup_required_when_unauthenticated(
    whatsapp_handler: MailOrganizerWhatsAppHandler,
) -> None:
    """Verify 'poller status' clearly indicates setup required when account is unlinked."""
    unlinked_user = PlatformUser(
        id=405,
        phone_number="+15552001704",
        full_name="Unauthenticated Member",
        role="employee",
        status="active",
        tenant_id="fresh_tenant",
        allowed_cartridges_json='["mail_organizer"]',
        encrypted_oauth_tokens=None,
    )

    context: Dict[str, Any] = {
        "sender_phone": unlinked_user.phone_number,
        "user": unlinked_user,
        "user_id": unlinked_user.id,
        "tenant_id": unlinked_user.tenant_id,
        "base_url": "http://localhost:8000",
    }

    res = await whatsapp_handler.dispatch({"text": {"body": "poller status"}}, context)
    assert "Email Poller & Sync Status" in res
    assert "*Your Personal Poller:* ⚠️ Not Connected (Setup Required)" in res
    assert "Reply `connect` to receive your setup link" in res

