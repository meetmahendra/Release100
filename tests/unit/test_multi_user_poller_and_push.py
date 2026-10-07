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
Unit tests for Multi-User Ingestion Poller and 24-Hour WhatsApp Push Notification Architecture.
Validates:
1. Multi-user polling loop filtering active entitled users with OAuth tokens.
2. WhatsApp proactive push notification for @Urgent emails within the 24h Meta window.
3. Push notification suppression when outside the 24h Meta window.
4. Cooperative shutdown and cancellation sentinel mechanics.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.services.poll_worker import MailPollWorker, interruptible_sleep, interruptible_async_sleep
from core_platform.app.identity.models import PlatformUser
from core_platform.app.middleware.tenant_context import get_current_user_context


@pytest.fixture
def mock_users() -> List[PlatformUser]:
    """Create fixture of users with different statuses, permissions, and heartbeat times."""
    now = datetime.now(timezone.utc)
    
    # User 1: Active, entitled to mail_organizer, has tokens, within 24h window (active 1 hour ago)
    user1 = PlatformUser(
        id="user_1",
        phone_number="+15551234567",
        tenant_id="tenant_alpha",
        full_name="Alice Alpha",
        role="member",
        status="active",
        allowed_cartridges_json='["mail_organizer"]',
        encrypted_oauth_tokens="mock_encrypted_tokens_1",
        user_secret_salt="salt_user_1_secret",
        last_whatsapp_interaction_at=(now - timedelta(hours=1)).isoformat(),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    # User 2: Active, entitled, has tokens, OUTSIDE 24h window (active 30 hours ago)
    user2 = PlatformUser(
        id="user_2",
        phone_number="+15557654321",
        tenant_id="tenant_beta",
        full_name="Bob Beta",
        role="member",
        status="active",
        allowed_cartridges_json='["mail_organizer"]',
        encrypted_oauth_tokens="mock_encrypted_tokens_2",
        user_secret_salt="salt_user_2_secret",
        last_whatsapp_interaction_at=(now - timedelta(hours=30)).isoformat(),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    # User 3: Suspended / Inactive user
    user3 = PlatformUser(
        id="user_3",
        phone_number="+15559999999",
        tenant_id="tenant_gamma",
        full_name="Charlie Suspended",
        role="member",
        status="suspended",
        allowed_cartridges_json='["mail_organizer"]',
        encrypted_oauth_tokens="mock_encrypted_tokens_3",
        user_secret_salt="salt_user_3_secret",
        last_whatsapp_interaction_at=now.isoformat(),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    # User 4: Active, but only has temperature_marker (not mail_organizer)
    user4 = PlatformUser(
        id="user_4",
        phone_number="+15558888888",
        tenant_id="tenant_delta",
        full_name="Dana TempOnly",
        role="member",
        status="active",
        allowed_cartridges_json='["temperature_marker"]',
        encrypted_oauth_tokens="mock_encrypted_tokens_4",
        user_secret_salt="salt_user_4_secret",
        last_whatsapp_interaction_at=now.isoformat(),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    return [user1, user2, user3, user4]


@pytest.mark.asyncio
async def test_poller_multi_user_entitlement_filtering(mock_users: List[PlatformUser], tmp_path: Path) -> None:
    """Verify that poll_once iterates over only active entitled users with valid credentials."""
    worker = MailPollWorker(poll_interval_seconds=10, root_dir=tmp_path)
    
    mock_identity_service = MagicMock()
    mock_identity_service.list_users.return_value = mock_users

    polled_user_ids = []

    async def fake_poll_for_target(connector: Any, user: Any = None, user_salt: Any = None) -> int:
        if user:
            polled_user_ids.append(user.id)
        return 1

    with patch("core_platform.app.identity.service.get_user_identity_service", return_value=mock_identity_service), \
         patch("apps.mail_organizer.connectors.auth_manager.get_user_access_token", return_value="mock_access_token_xyz"), \
         patch.object(worker, "_poll_for_target", side_effect=fake_poll_for_target):
        
        total = await worker.poll_once()
        assert total == 2
        # User 1 and User 2 should be polled, User 3 (suspended) and User 4 (temperature_marker only) skipped
        assert "user_1" in polled_user_ids
        assert "user_2" in polled_user_ids
        assert "user_3" not in polled_user_ids
        assert "user_4" not in polled_user_ids


@pytest.mark.asyncio
async def test_urgent_email_triggers_whatsapp_push_within_24h(mock_users: List[PlatformUser], tmp_path: Path) -> None:
    """Verify that an @Urgent email triggers proactive WhatsApp push when user is within 24h window."""
    worker = MailPollWorker(poll_interval_seconds=10, root_dir=tmp_path)
    user1 = mock_users[0]  # Alice: within 24h window

    fake_threads = [{
        "gmail_id": "GMAIL_URGENT_123",
        "thread_id": "THREAD_123",
        "sender": "boss@executive.com",
        "to_recipients": ["alice@company.com"],
        "subject": "CRITICAL: Server Outage",
        "body": "Production cluster is failing, please respond immediately.",
        "snippet": "Production cluster is failing...",
    }]

    mock_connector = MagicMock(spec=GmailConnector)
    mock_connector.fetch_unread_threads = AsyncMock(return_value=fake_threads)

    executed_state = {
        "gmail_id": "GMAIL_URGENT_123",
        "category": "@Urgent",
        "urgency_score": 10,
        "subject": "CRITICAL: Server Outage",
        "sender": "boss@executive.com",
        "reasoning": "Severe operational incident.",
    }

    worker.workflow.execute = AsyncMock(return_value=executed_state)

    with patch.object(worker, "_dispatch_urgent_whatsapp_push", new_callable=AsyncMock) as mock_push:
        count = await worker._poll_for_target(mock_connector, user=user1, user_salt=user1.user_secret_salt)
        assert count == 1
        mock_push.assert_awaited_once_with(user1, executed_state)


@pytest.mark.asyncio
async def test_urgent_push_suppressed_outside_24h_window(mock_users: List[PlatformUser], tmp_path: Path) -> None:
    """Verify that proactive WhatsApp push is suppressed if user is outside Meta 24-hour window."""
    worker = MailPollWorker(poll_interval_seconds=10, root_dir=tmp_path)
    user2 = mock_users[1]  # Bob: outside 24h window (30h ago)

    state = {
        "gmail_id": "GMAIL_URGENT_999",
        "category": "@Urgent",
        "urgency_score": 9,
        "subject": "System Alert",
        "sender": "alerts@monitoring.com",
        "reasoning": "High priority alert",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        await worker._dispatch_urgent_whatsapp_push(user2, state)
        # Should be suppressed; no HTTP call made to WhatsApp Graph API
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_urgent_push_dispatches_http_when_allowed(mock_users: List[PlatformUser], tmp_path: Path) -> None:
    """Verify that proactive WhatsApp push makes HTTP POST to WhatsApp endpoint when user is active within 24h."""
    worker = MailPollWorker(poll_interval_seconds=10, root_dir=tmp_path)
    user1 = mock_users[0]  # Alice: within 24h

    state = {
        "gmail_id": "GMAIL_URGENT_555",
        "category": "@Urgent",
        "urgency_score": 9,
        "subject": "Urgent Contract Approval",
        "sender": "legal@client.com",
        "reasoning": "Needs signature before deadline.",
    }

    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200

    with patch("core_platform.app.config.settings.WHATSAPP_ACCESS_TOKEN", "mock_wa_access_token_123"), \
         patch("core_platform.app.config.settings.WHATSAPP_PHONE_NUMBER_ID", "1234567890"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
        
        await worker._dispatch_urgent_whatsapp_push(user1, state)
        assert mock_post.await_count == 1
        args, kwargs = mock_post.call_args
        assert "1234567890/messages" in args[0]
        assert kwargs["json"]["to"] == "15551234567"
        assert "URGENT EMAIL ALERT" in kwargs["json"]["text"]["body"]
        assert "Urgent Contract Approval" in kwargs["json"]["text"]["body"]


def test_cooperative_shutdown_sentinel(tmp_path: Path) -> None:
    """Verify interruptible_sleep terminates cleanly on atomic sentinel file or stop event."""
    sentinel = tmp_path / ".poll_worker_stop"
    
    # 1. Normal sleep finishes with False
    res = interruptible_sleep(seconds=0.05, sentinel_path=sentinel)
    assert res is False

    # 2. Sentinel present triggers early exit True
    sentinel.touch()
    res2 = interruptible_sleep(seconds=5.0, sentinel_path=sentinel)
    assert res2 is True
    sentinel.unlink()

    # 3. Stop event triggers early exit True
    import threading
    ev = threading.Event()
    ev.set()
    res3 = interruptible_sleep(seconds=5.0, stop_event=ev, sentinel_path=sentinel)
    assert res3 is True
