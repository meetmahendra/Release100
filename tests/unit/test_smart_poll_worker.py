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
Unit tests for Smart PollWorker scheduling and deduplication logic.

Verifies:
- Active window boundary evaluation (_is_within_active_window)
- Email deduplication (already processed gmail_id is skipped)
- Workspace master poller pause (skips all tenant users)
- Per-user poller pause (skips disabled user)
- Per-user cadence interval gate (skips until interval has elapsed)
- On-demand manual sync (poll_user_now)
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import create_engine

from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.database.models import Base
from apps.mail_organizer.services.poll_worker import MailPollWorker


@pytest.fixture
def mock_db() -> Generator[MailDatabaseService, None, None]:
    """Provide an isolated in-memory DB service."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    service = MailDatabaseService(engine=engine)
    yield service
    service.close()


def test_active_window_evaluation(mock_db: MailDatabaseService) -> None:
    """_is_within_active_window correctly handles 24x7, normal, and overnight ranges."""
    worker = MailPollWorker(db_service=mock_db)

    # 1. 24x7 and empty always return True
    assert worker._is_within_active_window("24x7") is True
    assert worker._is_within_active_window("24/7") is True
    assert worker._is_within_active_window("") is True

    # 2. Window logic
    # Test with explicit datetime mocking
    with patch("apps.mail_organizer.services.poll_worker.datetime") as mock_dt:
        mock_now = datetime(2026, 10, 11, 14, 30, tzinfo=timezone.utc)
        mock_dt.now.return_value = mock_now

        # 14:30 is inside 09:00-18:00
        assert worker._is_within_active_window("09:00-18:00") is True

        # 14:30 is outside 15:00-18:00
        assert worker._is_within_active_window("15:00-18:00") is False

        # Overnight window 22:00-06:00 (14:30 is outside)
        assert worker._is_within_active_window("22:00-06:00") is False

        # Overnight window 12:00-02:00 (14:30 is inside)
        assert worker._is_within_active_window("12:00-02:00") is True


@pytest.mark.asyncio
async def test_email_deduplication(mock_db: MailDatabaseService) -> None:
    """Already processed email is skipped without re-executing workflow."""
    tenant = "gurav_family"

    # Pre-store an already processed email in DB
    mock_db.store_email(
        gmail_id="gmail_msg_existing_001",
        thread_id="thread_001",
        subject="Important Notice",
        sender="boss@corp.com",
        tenant_id=tenant,
    )

    # Mock connector returning the existing email and a new email
    mock_connector = MagicMock(spec=GmailConnector)
    mock_connector.fetch_unread_threads = AsyncMock(
        return_value=[
            {
                "gmail_id": "gmail_msg_existing_001",
                "thread_id": "thread_001",
                "sender": "boss@corp.com",
                "subject": "Important Notice",
                "body": "Already seen",
            },
            {
                "gmail_id": "gmail_msg_new_002",
                "thread_id": "thread_002",
                "sender": "client@corp.com",
                "subject": "New Project Update",
                "body": "Need feedback",
            },
        ]
    )

    worker = MailPollWorker(db_service=mock_db, gmail_connector=mock_connector)
    worker.workflow = MagicMock()
    worker.workflow.execute = AsyncMock(
        return_value={
            "category": "@ActionRequired",
            "urgency_score": 6,
            "reasoning": "New client update",
        }
    )

    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.tenant_id = tenant
    mock_user.phone_number = "+919800000001"
    mock_user.full_name = "Mahendra Gurav"
    mock_user.role = "USER"
    mock_user.user_secret_salt = "synthetic_salt_123"
    mock_user.allowed_cartridges = ["mail_organizer"]

    count = await worker._poll_for_target(connector=mock_connector, user=mock_user)

    # Only 1 new email should be processed (the existing one skipped via dedup)
    assert count == 1
    assert worker.workflow.execute.call_count == 1
    call_args = worker.workflow.execute.call_args[0][0]
    assert call_args["gmail_id"] == "gmail_msg_new_002"


@pytest.mark.asyncio
async def test_workspace_master_pause_skips_users(mock_db: MailDatabaseService) -> None:
    """When workspace poller is paused, poll_once skips all tenant users."""
    tenant = "tenant_master_pause"

    # Pause workspace master poller
    mock_db.set_workspace_poller_status(is_enabled=False, tenant_id=tenant)

    mock_user = MagicMock()
    mock_user.id = 10
    mock_user.tenant_id = tenant
    mock_user.status = "ACTIVE"
    mock_user.allowed_cartridges = ["mail_organizer"]
    mock_user.encrypted_oauth_tokens = "encrypted_token_dummy"

    worker = MailPollWorker(db_service=mock_db)
    worker._poll_for_target = AsyncMock(return_value=0)  # type: ignore[method-assign]

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis:
        mock_service = MagicMock()
        mock_service.list_users.return_value = [mock_user]
        mock_uis.return_value = mock_service

        processed = await worker.poll_once()

    assert processed == 0
    # _poll_for_target was NEVER called because master is paused
    assert worker._poll_for_target.call_count == 0


@pytest.mark.asyncio
async def test_user_poller_pause_skips_specific_user(mock_db: MailDatabaseService) -> None:
    """When an individual user's poller is paused, poll_once skips only that user."""
    tenant = "tenant_user_pause"

    # Workspace is active
    mock_db.set_workspace_poller_status(is_enabled=True, tenant_id=tenant)

    # User 1 active, User 2 paused
    mock_db.upsert_user_poller_config(
        user_id=1,
        email="active@tenant.com",
        is_enabled=True,
        poll_interval_seconds=60,
        tenant_id=tenant,
    )
    mock_db.upsert_user_poller_config(
        user_id=2,
        email="paused@tenant.com",
        is_enabled=False,
        poll_interval_seconds=60,
        tenant_id=tenant,
    )

    u1 = MagicMock(id=1, tenant_id=tenant, status="ACTIVE", allowed_cartridges=["mail_organizer"], encrypted_oauth_tokens="tok1", timezone="UTC", user_secret_salt="")
    u2 = MagicMock(id=2, tenant_id=tenant, status="ACTIVE", allowed_cartridges=["mail_organizer"], encrypted_oauth_tokens="tok2", timezone="UTC", user_secret_salt="")

    worker = MailPollWorker(db_service=mock_db)
    polled_users: List[int] = []

    async def fake_poll(connector: Any, user: Optional[Any] = None, user_salt: Optional[str] = None) -> int:
        if user:
            polled_users.append(user.id)
        return 1

    worker._poll_for_target = fake_poll  # type: ignore[method-assign]

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis:
        with patch("apps.mail_organizer.connectors.auth_manager.get_user_access_token", return_value="mock_tok"):
            mock_service = MagicMock()
            mock_service.list_users.return_value = [u1, u2]
            mock_uis.return_value = mock_service

            processed = await worker.poll_once()

    # User 1 polled, User 2 skipped
    assert processed == 1
    assert polled_users == [1]


@pytest.mark.asyncio
async def test_cadence_interval_gate(mock_db: MailDatabaseService) -> None:
    """User is skipped if elapsed time since last_polled_at is less than poll_interval_seconds."""
    tenant = "tenant_cadence"
    mock_db.set_workspace_poller_status(is_enabled=True, tenant_id=tenant)

    # User polled 20 seconds ago, but interval is 300s (5m)
    cfg = mock_db.upsert_user_poller_config(
        user_id=10,
        email="user10@tenant.com",
        is_enabled=True,
        poll_interval_seconds=300,
        tenant_id=tenant,
    )
    mock_db.record_user_poll_run(user_id=10, emails_fetched=0, tenant_id=tenant)

    u = MagicMock(id=10, tenant_id=tenant, status="ACTIVE", allowed_cartridges=["mail_organizer"], encrypted_oauth_tokens="tok", timezone="UTC", user_secret_salt="")

    worker = MailPollWorker(db_service=mock_db)
    worker._poll_for_target = AsyncMock(return_value=1)  # type: ignore[method-assign]

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis:
        mock_service = MagicMock()
        mock_service.list_users.return_value = [u]
        mock_uis.return_value = mock_service

        processed = await worker.poll_once()

    # Skipped because only ~0 seconds elapsed of 300s interval
    assert processed == 0
    assert worker._poll_for_target.call_count == 0


@pytest.mark.asyncio
async def test_poll_user_now_manual_sync(mock_db: MailDatabaseService) -> None:
    """poll_user_now bypasses interval and executes immediate sync."""
    tenant = "tenant_manual"

    mock_user = MagicMock()
    mock_user.id = 55
    mock_user.tenant_id = tenant
    mock_user.full_name = "Dipali Gurav"
    mock_user.status = "ACTIVE"
    mock_user.allowed_cartridges = ["mail_organizer"]
    mock_user.user_secret_salt = "salt_55"

    worker = MailPollWorker(db_service=mock_db)
    worker._poll_for_target = AsyncMock(return_value=4)  # type: ignore[method-assign]

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis:
        with patch("apps.mail_organizer.connectors.auth_manager.get_user_access_token", return_value="mock_access_tok"):
            mock_service = MagicMock()
            mock_service.get_user_by_id.return_value = mock_user
            mock_uis.return_value = mock_service

            res = await worker.poll_user_now(user_id=55, tenant_id=tenant)

    assert res["success"] is True
    assert res["emails_processed"] == 4
    assert "Polled inbox for Dipali Gurav: 4 new email(s) processed." in res["message"]

    # Verify telemetry was recorded
    recorded = mock_db.get_user_poller_config(user_id=55, tenant_id=tenant)
    assert recorded is not None
    assert recorded.last_polled_at is not None
    assert recorded.total_emails_fetched == 4
