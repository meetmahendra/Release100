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

"""Unit tests for Phase 5 Two-Stage WhatsApp Executive Brief UX & 24-Hour Window Gate."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.pm.task_manager import PMTaskManager
from apps.mail_organizer.services.poll_worker import MailPollWorker
from apps.mail_organizer.services.whatsapp_handler import MailOrganizerWhatsAppHandler


@pytest.mark.asyncio
async def test_poll_worker_24h_window_gate_and_stage1_list_drawer(tmp_path: Path) -> None:
    """Verify Meta 24h window gate dispatches Utility Template when expired and Stage 1 List Drawer when active."""
    db_file = tmp_path / "wa_ux_poll.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")
    worker = MailPollWorker(db_service=db, root_dir=tmp_path)

    mock_user = MagicMock()
    mock_user.id = 10
    mock_user.full_name = "Mahendra Gurav"
    mock_user.phone_number = "+919822001122"

    state = {
        "gmail_id": "msg_u99",
        "subject": "SEV-1 Outage Escalation",
        "sender": "noc@corp.com",
        "category": "@Urgent",
        "urgency_score": 10,
    }

    # Case 1: Outside 24h window -> calls send_whatsapp_template
    mock_user.is_within_24h_window.return_value = False
    with patch(
        "core_platform.app.ingress.whatsapp_outbound.send_whatsapp_template",
        new_callable=AsyncMock,
    ) as mock_tpl:
        mock_tpl.return_value = True
        sent_tpl = await worker._dispatch_urgent_whatsapp_push(mock_user, state)
        assert sent_tpl is True
        mock_tpl.assert_awaited_once()

    # Case 2: Inside 24h window -> calls send_whatsapp_interactive_list (Stage 1 Drawer)
    mock_user.is_within_24h_window.return_value = True
    with patch(
        "core_platform.app.ingress.whatsapp_outbound.send_whatsapp_interactive_list",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = True
        sent_list = await worker._dispatch_urgent_whatsapp_push(mock_user, state)
        assert sent_list is True
        mock_list.assert_awaited_once()
        _, kwargs = mock_list.call_args
        assert kwargs["sections"][0]["rows"][0]["id"] == "inspect_mail:msg_u99"


@pytest.mark.asyncio
async def test_stage2_card_inspection_deep_inspect_and_artifact_resolution(tmp_path: Path) -> None:
    """Verify Stage 2 Infographic PNG Card + 3 native buttons, Deep Inspect, and Missing Artifact resolution."""
    db_file = tmp_path / "wa_handler_test.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")
    pm = PMTaskManager(db_service=db)
    handler = MailOrganizerWhatsAppHandler(db_service=db, pm_manager=pm)

    db.store_email(
        gmail_id="msg_card_1",
        thread_id="th_card_1",
        subject="PO-5500 Approval",
        sender="cfo@client.com",
        snippet="Please approve PO-5500 for $64,000.",
        body="Please approve PO-5500 for $64,000 by Friday.",
    )
    db.store_classification(
        gmail_id="msg_card_1",
        category="@Action",
        urgency_score=9,
        confidence_score=0.96,
        reasoning="Direct CFO approval request",
        suggested_reply="Hi CFO,\nApproved PO-5500 for $64,000.\nBest regards,\nLead",
    )
    db.upsert_entity_fact(
        subject_entity="PO-5500",
        predicate="AMOUNT",
        object_value="$64,000",
        source_msg_id="msg_card_1",
        source_channel="EMAIL",
        tenant_id="t1",
        user_id=1,
    )

    # 1. Stage 2 Card Inspection
    card_resp: Any = await handler.dispatch(
        msg={"type": "interactive", "interactive": {"list_reply": {"id": "inspect_mail:msg_card_1", "title": "PO-5500"}}},
        context={"tenant_id": "t1", "user_id": 1, "sender_phone": "+919822001122"},
    )
    assert isinstance(card_resp, dict)
    assert card_resp["response_type"] == "interactive_buttons"
    assert isinstance(card_resp["header_image_bytes"], bytes)
    assert card_resp["header_image_bytes"].startswith(b"\x89PNG\r\n\x1a\n")
    btn_ids = [b["id"] for b in card_resp["buttons"]]
    assert "approve_send:msg_card_1" in btn_ids
    assert "deep_inspect:msg_card_1" in btn_ids
    assert "snooze_mail:msg_card_1" in btn_ids

    # 2. Deep Inspect
    deep_resp: Any = await handler.dispatch(
        msg={"type": "interactive", "interactive": {"button_reply": {"id": "deep_inspect:msg_card_1", "title": "Deep Inspect"}}},
        context={"tenant_id": "t1", "user_id": 1, "sender_phone": "+919822001122"},
    )
    assert isinstance(deep_resp, dict)
    assert deep_resp["response_type"] == "interactive_buttons"
    assert deep_resp["header_image_bytes"].startswith(b"\x89PNG\r\n\x1a\n")
    assert "PO-5500" in deep_resp
    assert "$64,000" in deep_resp

    # 3. Missing Artifact Resolution via WhatsApp
    db.create_missing_artifact_request(
        gmail_id="msg_art_77",
        artifact_type="ATTACHMENT_MISSING",
        artifact_description="Missing CapEx sheet",
        tenant_id="t1",
        user_id=1,
    )
    art_resp = await handler.dispatch(
        msg={"text": {"body": "artifact msg_art_77 Confirmed CapEx cap is $85,000"}},
        context={"tenant_id": "t1", "user_id": 1, "sender_phone": "+919822001122"},
    )
    assert isinstance(art_resp, str)
    assert "Missing Artifact Resolved" in art_resp
    assert len(db.get_pending_artifact_requests("t1")) == 0
