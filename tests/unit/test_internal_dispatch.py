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

"""Synthetic Unit Tests for Manager Interactive Triage & Two-Way Quoted Reply Relay (Phase 6)."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from starlette.testclient import TestClient

from apps.temperature_marker.database.db_service import DatabaseService
from core_platform.app.config import settings
from core_platform.app.messaging.internal_dispatch import (
    ManagerTriageSessionManager,
    build_top10_digest,
    handle_manager_navigation,
    handle_manager_reply,
    send_urgent_meta_template_alert,
)
from core_platform.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_triage_sessions() -> None:
    """Reset triage session store before and after each test."""
    session_mgr = ManagerTriageSessionManager.get_instance()
    with session_mgr._lock:
        session_mgr._active_message.clear()
        session_mgr._current_index.clear()
    yield
    with session_mgr._lock:
        session_mgr._active_message.clear()
        session_mgr._current_index.clear()


def test_build_top10_digest_empty() -> None:
    """When manager has 0 pending messages, return friendly empty queue greeting."""
    db = DatabaseService.get_instance()
    mgr_phone = "+919800000001"
    digest = build_top10_digest(
        manager_phone=mgr_phone,
        manager_name="Priya Singh",
        db_service=db,
    )
    assert "Hello Priya Singh!" in digest
    assert "0 pending messages in your queue" in digest


def test_build_top10_digest_with_messages() -> None:
    """When manager has pending messages, format top 10 digest and active Message 1."""
    db = DatabaseService.get_instance()
    mgr_phone = "+919800000002"
    session_mgr = ManagerTriageSessionManager.get_instance()

    # Enqueue two messages with different priorities
    m1 = db.enqueue_internal_message(
        sender_phone="+919700000001",
        sender_name="Operator Amit",
        recipient_phone=mgr_phone,
        message_text="Need 100 paper cups urgently",
        kiosk_id="CANEBOT-PUNE-01",
        priority=50,
    )
    m2 = db.enqueue_internal_message(
        sender_phone="+919700000002",
        sender_name="Operator Rohan",
        recipient_phone=mgr_phone,
        message_text="Chiller temp sensor reading 14.5C - warning!",
        kiosk_id="CANEBOT-MUMBAI-02",
        priority=75,
    )

    digest = build_top10_digest(
        manager_phone=mgr_phone,
        manager_name="Priya Singh",
        db_service=db,
        session_mgr=session_mgr,
    )

    # Priority 75 should come first in digest
    assert "Hello Priya Singh!" in digest
    assert "messages pending" in digest
    assert "CANEBOT-MUMBAI-02" in digest
    assert "CANEBOT-PUNE-01" in digest

    # Message 1 shown in full
    assert "👉 Message 1 of" in digest
    assert "Chiller temp sensor reading 14.5C" in digest
    assert "Reply to this message to answer directly" in digest

    # Session should point to the highest priority message (m2)
    active_id = session_mgr.get_active_message_id(mgr_phone)
    assert active_id == m2.id

    # Clean up
    db.resolve_internal_message(m1.id, "resolved in test", mgr_phone)
    db.resolve_internal_message(m2.id, "resolved in test", mgr_phone)


def test_handle_manager_navigation_next_and_all() -> None:
    """Manager can navigate queue with 'NEXT', 'ALL' commands."""
    db = DatabaseService.get_instance()
    mgr_phone = "+919800000003"
    session_mgr = ManagerTriageSessionManager.get_instance()

    m1 = db.enqueue_internal_message(
        sender_phone="+919700000003",
        sender_name="Operator Vikas",
        recipient_phone=mgr_phone,
        message_text="First message from Vikas",
        kiosk_id="CANEBOT-PUNE-03",
        priority=25,
    )
    m2 = db.enqueue_internal_message(
        sender_phone="+919700000004",
        sender_name="Operator Sunita",
        recipient_phone=mgr_phone,
        message_text="Second message from Sunita",
        kiosk_id="CANEBOT-PUNE-04",
        priority=25,
    )

    # First view sets active to m1
    build_top10_digest(mgr_phone, "Priya", db, session_mgr)

    # Send NEXT -> advances to m2
    nav_next = handle_manager_navigation(mgr_phone, "Priya", "NEXT", db, session_mgr)
    assert "Message 2 of" in nav_next
    assert "Second message from Sunita" in nav_next

    # Send ALL -> lists both messages
    nav_all = handle_manager_navigation(mgr_phone, "Priya", "ALL", db, session_mgr)
    assert "All Pending Messages" in nav_all
    assert "First message from Vikas" in nav_all
    assert "Second message from Sunita" in nav_all

    # Clean up
    db.resolve_internal_message(m1.id, "resolved", mgr_phone)
    db.resolve_internal_message(m2.id, "resolved", mgr_phone)


def test_handle_manager_reply_two_way_relay() -> None:
    """Manager reply resolves message and constructs two-way quoted text to operator."""
    db = DatabaseService.get_instance()
    mgr_phone = "+919800000005"
    session_mgr = ManagerTriageSessionManager.get_instance()

    m1 = db.enqueue_internal_message(
        sender_phone="+919700000005",
        sender_name="Operator Nilesh",
        recipient_phone=mgr_phone,
        message_text="Running out of cane stalks for evening",
        kiosk_id="CANEBOT-PUNE-05",
        priority=50,
    )

    # View digest
    build_top10_digest(mgr_phone, "Supervisor Rajesh", db, session_mgr)

    # Reply to active message
    mgr_confirm, op_phone, op_msg = handle_manager_reply(
        manager_phone=mgr_phone,
        manager_name="Supervisor Rajesh",
        reply_text="Supply truck dispatched, ETA 20 mins.",
        quoted_wamid=None,
        db_service=db,
        session_mgr=session_mgr,
    )

    # Manager confirmation
    assert mgr_confirm is not None
    assert "Reply delivered to Operator Nilesh" in mgr_confirm
    assert "All pending messages in your queue have been resolved!" in mgr_confirm

    # Operator forward message format
    assert op_phone == "+919700000005"
    assert op_msg is not None
    assert "Reply from Supervisor Supervisor Rajesh" in op_msg
    assert 'Re: "Running out of cane stalks for evening"' in op_msg
    assert "Supply truck dispatched, ETA 20 mins." in op_msg
    assert "CANEBOT-PUNE-05" in op_msg

    # Verify message is marked RESOLVED in database
    with db.SessionLocal() as session:
        from apps.temperature_marker.database.models import InternalMessageQueue
        rec = session.query(InternalMessageQueue).filter(InternalMessageQueue.id == m1.id).first()
        assert rec is not None
        assert rec.status == "RESOLVED"
        assert rec.reply_context == "Supply truck dispatched, ETA 20 mins."
        assert rec.resolved_by_phone == mgr_phone


def test_handle_manager_numbered_reply() -> None:
    """Manager can reply specifically by number e.g. '1. Approved'."""
    db = DatabaseService.get_instance()
    mgr_phone = "+919800000006"
    session_mgr = ManagerTriageSessionManager.get_instance()

    m1 = db.enqueue_internal_message(
        sender_phone="+919700000006",
        sender_name="Op 1",
        recipient_phone=mgr_phone,
        message_text="Need cleaning cloth",
        kiosk_id="CANEBOT-01",
        priority=25,
    )
    m2 = db.enqueue_internal_message(
        sender_phone="+919700000007",
        sender_name="Op 2",
        recipient_phone=mgr_phone,
        message_text="Freezer compressor sound",
        kiosk_id="CANEBOT-02",
        priority=75,
    )

    # Manager replies with '1. Technician on the way' -> targets top-1 message (m2 due to priority 75)
    mgr_confirm, op_phone, op_msg = handle_manager_reply(
        manager_phone=mgr_phone,
        manager_name="Supervisor Rajesh",
        reply_text="1. Technician on the way",
        quoted_wamid=None,
        db_service=db,
        session_mgr=session_mgr,
    )

    assert op_phone == "+919700000007"
    assert op_msg is not None
    assert "Technician on the way" in op_msg
    assert 'Re: "Freezer compressor sound"' in op_msg

    # Clean up
    db.resolve_internal_message(m1.id, "cleaned", mgr_phone)


@pytest.mark.asyncio
async def test_send_urgent_meta_template_alert_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Urgent alert helper returns True in simulated mode when Meta credentials aren't set."""
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "")
    res = await send_urgent_meta_template_alert(
        recipient_phone="+919800000008",
        operator_name="Operator Test",
        kiosk_id="CANEBOT-PUNE-01",
        alert_summary="Chiller failure critical",
    )
    assert res is True


@pytest.mark.asyncio
async def test_send_urgent_meta_template_alert_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Urgent alert helper returns True when Meta API returns HTTP 200."""
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "mock_token")
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "mock_phone_id")

    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_post = AsyncMock(return_value=mock_resp)

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    res = await send_urgent_meta_template_alert(
        recipient_phone="+919800000008",
        operator_name="Operator Test",
        kiosk_id="CANEBOT-PUNE-01",
        alert_summary="Chiller failure critical",
    )
    assert res is True


def test_webhook_manager_greeting_and_reply_flow() -> None:
    """End-to-end test of manager sending 'hi', receiving digest, and sending reply via webhook."""
    db = DatabaseService.get_instance()

    # Register manager
    mgr_phone = "+919811998877"
    db.register_employee(
        emp_code="MGR-9901",
        full_name="Anjali Patil",
        phone_number=mgr_phone,
        assigned_kiosk_id="CANEBOT-PUNE-01",
        role="SUPERVISOR",
        status="ACTIVE",
    )

    # Register operator
    op_phone = "+919811998888"
    db.register_employee(
        emp_code="EMP-9902",
        full_name="Ganesh Jadhav",
        phone_number=op_phone,
        assigned_kiosk_id="CANEBOT-PUNE-01",
        role="OPERATOR",
        reporting_manager_emp_code="MGR-9901",
        status="ACTIVE",
    )

    # Clean any leftover messages from previous runs
    for prev_msg in db.get_pending_messages_for_recipient(mgr_phone, limit=50):
        db.resolve_internal_message(prev_msg.id, "pre-test cleanup", mgr_phone)

    # Step 1: Operator sends a query
    op_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "10001"},
                            "contacts": [{"profile": {"name": "Ganesh"}, "wa_id": "919811998888"}],
                            "messages": [
                                {
                                    "from": "919811998888",
                                    "id": "wamid.op_triage_1",
                                    "timestamp": "1710400000",
                                    "text": {"body": "Cold storage door gasket broken"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp1 = client.post("/webhook", json=op_payload)
    assert resp1.status_code == 200
    assert "Message Dispatched to Anjali Patil" in resp1.json()["reply_message"]

    # Step 2: Manager sends 'hi' to get triage digest
    mgr_greet_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "10001"},
                            "contacts": [{"profile": {"name": "Anjali"}, "wa_id": "919811998877"}],
                            "messages": [
                                {
                                    "from": "919811998877",
                                    "id": "wamid.mgr_greet_1",
                                    "timestamp": "1710400010",
                                    "text": {"body": "hi"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp2 = client.post("/webhook", json=mgr_greet_payload)
    assert resp2.status_code == 200
    reply2 = resp2.json()["reply_message"]
    assert "Hello Anjali Patil!" in reply2
    assert "Cold storage door gasket broken" in reply2
    assert "Reply to this message to answer directly" in reply2

    # Step 3: Manager sends reply: 'Will replace gasket during noon maintenance'
    mgr_reply_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "10001"},
                            "contacts": [{"profile": {"name": "Anjali"}, "wa_id": "919811998877"}],
                            "messages": [
                                {
                                    "from": "919811998877",
                                    "id": "wamid.mgr_reply_1",
                                    "timestamp": "1710400020",
                                    "text": {"body": "Will replace gasket during noon maintenance"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp3 = client.post("/webhook", json=mgr_reply_payload)
    assert resp3.status_code == 200
    reply3 = resp3.json()["reply_message"]
    assert "Reply delivered to Ganesh Jadhav" in reply3
    assert "All pending messages in your queue have been resolved!" in reply3
