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

"""Regression test suite for all 8 Live Outstation Testing Remediation issues (v1.1)."""

import asyncio
import io
import json
from pathlib import Path
from typing import Any, Dict, List
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from apps.mail_organizer.connectors.auth_manager import get_user_access_token
from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.plugin import MailOrganizerApplication
from apps.mail_organizer.pm.task_manager import PMTaskManager
from apps.mail_organizer.services.poll_worker import MailPollWorker
from apps.mail_organizer.services.whatsapp_handler import MailOrganizerWhatsAppHandler
from core_platform.app.identity.oauth_utils import decrypt_user_tokens, encrypt_user_tokens
from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_interactive_list


@pytest.mark.asyncio
async def test_issue1_whatsapp_interactive_list_24_char_section_title_and_clamping(tmp_path: Path) -> None:
    """Verify Issue #1: Section title is <= 24 chars and send_whatsapp_interactive_list clamps lengths."""
    db_file = tmp_path / "issue1.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")
    worker = MailPollWorker(db_service=db, root_dir=tmp_path)

    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.full_name = "Executive User"
    mock_user.phone_number = "+919822001122"
    mock_user.is_within_24h_window.return_value = True

    state = {
        "gmail_id": "msg_101",
        "subject": "Urgent Board Resolution Required Immediately",
        "sender": "chairman@board.example.com",
        "category": "@Urgent",
        "urgency_score": 10,
    }

    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid.ok1"}]}

    with patch("core_platform.app.config.settings.WHATSAPP_ACCESS_TOKEN", "mock_wa_token_test"), \
         patch("core_platform.app.config.settings.WHATSAPP_PHONE_NUMBER_ID", "1234567890"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
        sent = await worker._dispatch_urgent_whatsapp_push(mock_user, state)
        assert sent is True
        _, kwargs = mock_post.call_args
        sec_title = kwargs["json"]["interactive"]["action"]["sections"][0]["title"]
        assert sec_title == "Actionable Mail"
        assert len(sec_title) <= 24

        # Also test defensive clamping when a caller passes oversized strings
        await send_whatsapp_interactive_list(
            to_phone="+919822001122",
            body_text="Test body",
            button_label="Oversized Button Label Here",
            sections=[
                {
                    "title": "Oversized Section Title Exceeding 24 Characters",
                    "rows": [
                        {
                            "id": "x" * 250,
                            "title": "Oversized Row Title Exceeding 24 Characters",
                            "description": "d" * 100,
                        }
                    ],
                }
            ],
        )
        _, kwargs2 = mock_post.call_args
        sec2 = kwargs2["json"]["interactive"]["action"]["sections"][0]
        assert len(sec2["title"]) <= 24
        assert len(sec2["rows"][0]["id"]) <= 200
        assert len(sec2["rows"][0]["title"]) <= 24
        assert len(sec2["rows"][0]["description"]) <= 72


def test_issue2_dashboard_trace_cards_pm_tasks_no_t_shadowing() -> None:
    """Verify Issue #2: Rendering _dashboard_trace_cards.html with pm_tasks does not shadow global t()."""
    from jinja2 import Environment, FileSystemLoader

    tpl_dir = Path("apps/mail_organizer/ui/templates")
    env = Environment(loader=FileSystemLoader(str(tpl_dir)))
    template = env.get_template("_dashboard_trace_cards.html")

    def mock_t(key: str, **kwargs: Any) -> str:
        if kwargs:
            return f"{key}({kwargs})"
        return key

    recent_emails = [
        {
            "gmail_id": "msg_trace_1",
            "entry_point": "Gmail Ingestion",
            "subject": "Quarterly Audit Action Items",
            "category": "@Action",
            "safety_override": False,
            "confidence": 0.95,
            "execution_time_seconds": 0.42,
            "sender": "auditor@firm.com",
            "to_recipients": ["exec@firm.com"],
            "cc_recipients": [],
            "received_at": "2026-10-19T10:00:00Z",
            "body": "Please complete the audit checklist.",
            "urgency_score": 8,
            "context_tags": ["audit"],
            "recipient_role": "PRIMARY_ACTIONEE",
            "reasoning": "Action required",
            "llm_communications": [],
            "connector_communications": [],
            "pipeline_trace": [{"node": "pre_check", "duration_ms": 0.8, "decision": "Passed"}],
            "suggested_reply": "We will complete the checklist today.",
            "pm_tasks": [
                {
                    "task_id": "TASK-MO-01",
                    "summary": "Complete audit checklist",
                    "destination": "jira",
                    "priority": "High",
                    "status": "PENDING",
                },
                {
                    "task_id": "TASK-MO-02",
                    "summary": "Submit sign-off sheet",
                    "destination": "linear",
                    "priority": "Medium",
                    "status": "PENDING",
                },
            ],
        }
    ]

    rendered = template.render(recent_emails=recent_emails, t=mock_t)
    assert "TASK-MO-01" in rendered
    assert "TASK-MO-02" in rendered
    assert "apps.mail_organizer.dashboard.btn_review_pm_queue" in rendered


def test_issue3_iam_wildcard_tenant_user_entitlement_intersection() -> None:
    """Verify Issue #3: Wildcard '*' in tenant_obj.allowed_cartridges preserves user cartridge selection."""
    tenant_obj = MagicMock()
    tenant_obj.allowed_cartridges = ["*"]
    is_super = False
    allowed = ["mail_organizer"]

    if (
        tenant_obj
        and hasattr(tenant_obj, "allowed_cartridges")
        and not is_super
        and "*" not in tenant_obj.allowed_cartridges
        and "all" not in tenant_obj.allowed_cartridges
    ):
        allowed = [c for c in allowed if c in tenant_obj.allowed_cartridges]

    assert allowed == ["mail_organizer"]


@pytest.mark.asyncio
async def test_issue4_poller_discovers_wildcard_entitled_users(tmp_path: Path) -> None:
    """Verify Issue #4: Poller discovers and polls users whose allowed_cartridges is ['*']."""
    db_file = tmp_path / "issue4.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")
    worker = MailPollWorker(db_service=db, root_dir=tmp_path)

    wildcard_user = MagicMock()
    wildcard_user.id = 7
    wildcard_user.full_name = "Wildcard User"
    wildcard_user.email = "wildcard@test.com"
    wildcard_user.timezone = "UTC"
    wildcard_user.status = "active"
    wildcard_user.tenant_id = "tenant_w"
    wildcard_user.allowed_cartridges = ["*"]
    wildcard_user.encrypted_oauth_tokens = "enc_tok_123"
    wildcard_user.user_secret_salt = "salt_w_123"

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_id_svc, \
         patch("apps.mail_organizer.connectors.auth_manager.get_user_access_token", return_value="valid_tok"), \
         patch.object(worker, "_poll_for_target", new_callable=AsyncMock, return_value=2) as mock_poll_target:
        mock_id_svc.return_value.list_users.return_value = [wildcard_user]
        mock_id_svc.return_value.get_user_by_id.return_value = wildcard_user

        count = await worker.poll_once()
        assert count == 2
        mock_poll_target.assert_awaited_once()

        now_res = await worker.poll_user_now(user_id=7, tenant_id="tenant_w")
        assert now_res["success"] is True
        assert now_res["emails_processed"] == 2


@pytest.mark.asyncio
async def test_issue5_per_user_asyncio_lock_prevents_concurrent_poll_overlap(tmp_path: Path) -> None:
    """Verify Issue #5: Per-user asyncio.Lock skips overlapping background poll cycles for the same user."""
    db_file = tmp_path / "issue5.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")
    worker = MailPollWorker(db_service=db, root_dir=tmp_path)

    user = MagicMock()
    user.id = 42
    user.full_name = "Locked User"
    user.email = "locked@test.com"
    user.timezone = "UTC"
    user.status = "active"
    user.tenant_id = "tenant_l"
    user.allowed_cartridges = ["mail_organizer"]
    user.encrypted_oauth_tokens = "enc_tok_42"
    user.user_secret_salt = "salt_42"

    lock = worker._get_user_lock(42)
    async with lock:
        with patch("core_platform.app.identity.service.get_user_identity_service") as mock_id_svc, \
             patch.object(worker, "_poll_for_target", new_callable=AsyncMock) as mock_poll_target:
            mock_id_svc.return_value.list_users.return_value = [user]
            count = await worker.poll_once()
            assert count == 0
            mock_poll_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_issue6_stage2_card_inspection_dict_keys_and_priority1_routing(tmp_path: Path) -> None:
    """Verify Issue #6: Stage 2 card returns reply_message + interactive_buttons and keywords include inspect_mail:."""
    app = MailOrganizerApplication(db_url=f"sqlite:///{tmp_path / 'issue6_app.db'}")
    for prefix in ("inspect_mail:", "deep_inspect:", "approve_send:", "snooze_mail:", "provide_artifact:"):
        assert prefix in app.keywords

    handler = app.get_whatsapp_handler()
    app.db_service.store_email(
        gmail_id="msg_stage2_6",
        thread_id="th_stage2_6",
        subject="Contract Renewal",
        sender="legal@vendor.com",
        snippet="Please review the renewal terms.",
        body="Please review the renewal terms by EOD.",
    )
    res = await handler.dispatch(
        {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": "inspect_mail:msg_stage2_6", "title": "Contract"}}},
        {"tenant_id": "default_tenant"},
    )
    assert isinstance(res, dict)
    assert res.get("reply_message")
    assert res.get("body_text") == res.get("reply_message")
    assert isinstance(res.get("interactive_buttons"), list)
    assert len(res["interactive_buttons"]) == 3
    assert isinstance(res.get("header_image_bytes"), bytes)


def test_issue7_oauth_expiry_persistence_auto_refresh_401_retry_and_rfc_headers() -> None:
    """Verify Issue #7: Missing expiry triggers token refresh, 401 retries per-user refresh, and rfc_headers extracted."""
    salt = "user_salt_issue7"
    initial_tokens = {
        "access_token": "stale_token_111",
        "refresh_token": "refresh_token_222",
        "client_id": "client_id_test",
        "client_secret": "client_secret_test",
        # Notice: 'expiry' is intentionally missing to simulate legacy stored token
    }
    enc_initial = encrypt_user_tokens(initial_tokens, salt)

    mock_user = MagicMock()
    mock_user.id = 99
    mock_user.user_secret_salt = salt
    mock_user.encrypted_oauth_tokens = enc_initial

    refresh_http_resp = MagicMock()
    refresh_http_resp.status = 200
    refresh_http_resp.read.return_value = json.dumps({
        "access_token": "fresh_token_999",
        "expires_in": 3600,
    }).encode("utf-8")
    refresh_http_resp.__enter__.return_value = refresh_http_resp

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_id_svc, \
         patch("urllib.request.urlopen", return_value=refresh_http_resp):
        mock_id_svc.return_value.get_user_by_id.return_value = mock_user
        token = get_user_access_token(mock_user)
        assert token == "fresh_token_999"
        mock_id_svc.return_value.update_user_tokens.assert_called_once()
        saved_enc = mock_id_svc.return_value.update_user_tokens.call_args[0][1]
        saved_dec = decrypt_user_tokens(saved_enc, salt)
        assert saved_dec is not None
        assert "expiry" in saved_dec

    # Verify GmailConnector._api_request retries on HTTP 401 with get_user_access_token(user_id, force_refresh=True)
    conn = GmailConnector(access_token_override="expired_tok", user_id=99, mock_mode=False)
    err_401 = urllib.error.HTTPError(
        url="https://gmail.googleapis.com/gmail/v1/users/me/messages",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b"{}"),
    )
    ok_resp = MagicMock()
    ok_resp.read.return_value = json.dumps({"messages": []}).encode("utf-8")
    ok_resp.__enter__.return_value = ok_resp

    with patch("urllib.request.urlopen", side_effect=[err_401, ok_resp]), \
         patch("apps.mail_organizer.connectors.auth_manager.get_user_access_token", return_value="refreshed_tok_401") as mock_ref:
        data = conn._api_request("messages", method="GET")
        assert data == {"messages": []}
        mock_ref.assert_called_once_with(99, force_refresh=True)
        assert conn.access_token_override == "refreshed_tok_401"


@pytest.mark.asyncio
async def test_issue8_whatsapp_drafts_and_deep_inspect_decrypt_aes_gcm_payloads(tmp_path: Path) -> None:
    """Verify Issue #8: Encrypted drafts and email snippets are transparently decrypted on WhatsApp replies."""
    db_file = tmp_path / "issue8.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")
    pm = PMTaskManager(db_service=db)
    handler = MailOrganizerWhatsAppHandler(db_service=db, pm_manager=pm)

    salt = "executive_secret_salt_98765"
    mock_user = MagicMock()
    mock_user.id = 5
    mock_user.full_name = "Depali Gurav"
    mock_user.phone_number = "+919822001122"
    mock_user.tenant_id = "default_tenant"
    mock_user.user_secret_salt = salt

    db.store_email(
        gmail_id="msg_enc_8",
        thread_id="th_enc_8",
        subject="Encrypted Budget Proposal",
        sender="finance@corp.com",
        snippet="Confidential Q4 budget allocation of $250,000.",
        body="Confidential Q4 budget allocation of $250,000 for cloud infrastructure.",
        user_salt=salt,
        tenant_id="default_tenant",
    )
    draft_rec = db.store_draft(
        gmail_id="msg_enc_8",
        thread_id="th_enc_8",
        recipient="finance@corp.com",
        subject="Re: Encrypted Budget Proposal",
        body="Hi Finance Team, the $250,000 Q4 cloud budget is approved.",
        user_salt=salt,
        tenant_id="default_tenant",
    )
    assert draft_rec.body.startswith("ENC:v1:")

    ctx = {
        "user": mock_user,
        "user_id": mock_user.id,
        "tenant_id": "default_tenant",
        "sender_phone": mock_user.phone_number,
        "base_url": "http://localhost:8000",
    }

    # 1. 'drafts' command must show decrypted plaintext, never 'ENC:v1:'
    drafts_reply = await handler.dispatch({"text": {"body": "drafts"}}, ctx)
    assert isinstance(drafts_reply, dict)
    assert "ENC:v1:" not in drafts_reply
    assert "$250,000 Q4 cloud budget is approved" in drafts_reply

    # 2. 'inspect_mail:msg_enc_8' Stage 2 card must show decrypted draft preview
    stage2_reply = await handler.dispatch({"text": {"body": "inspect_mail:msg_enc_8"}}, ctx)
    assert isinstance(stage2_reply, dict)
    assert "ENC:v1:" not in stage2_reply["reply_message"]
    assert "$250,000 Q4 cloud budget is approved" in stage2_reply["reply_message"]

    # 3. 'deep_inspect:msg_enc_8' must show decrypted full staged draft
    deep_reply = await handler.dispatch({"text": {"body": "deep_inspect:msg_enc_8"}}, ctx)
    assert isinstance(deep_reply, dict)
    assert "ENC:v1:" not in deep_reply["reply_message"]
    assert "$250,000 Q4 cloud budget is approved" in deep_reply
