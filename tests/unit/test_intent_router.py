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

"""Synthetic Unit Tests for Ingress Intent Inference & Direct Manager Routing (Phase 5)."""

import pytest
from starlette.testclient import TestClient

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.services.intent_router import (
    IngressIntent,
    classify_ingress_intent,
    infer_message_priority_and_category,
)
from core_platform.main import app

client = TestClient(app)


def test_infer_priority_and_category() -> None:
    """Keyword heuristics classify emergency, breakdown, supply, and queries accurately."""
    # Emergency / Hazard -> 100
    p_emerg, cat_emerg = infer_message_priority_and_category("Emergency fire at kiosk electrical board")
    assert p_emerg == 100
    assert cat_emerg == "emergency"

    # Breakdown / Mechanical -> 75
    p_bk, cat_bk = infer_message_priority_and_category("Juice motor vibrating and making grinding noise")
    assert p_bk == 75
    assert cat_bk == "breakdown"

    # Supply request -> 50
    p_sup, cat_sup = infer_message_priority_and_category("Need 200 cups and extra straws for rush hour")
    assert p_sup == 50
    assert cat_sup == "supply"

    # General query -> 25
    p_q, cat_q = infer_message_priority_and_category("When is the weekly maintenance shift scheduled?")
    assert p_q == 25
    assert cat_q == "query"


def test_classify_ingress_intent_operator() -> None:
    """Operator messages are classified into queries, checkins, and system commands without @tagging."""
    # Operator friendly greetings -> OPERATOR_GREETING
    for greet in ["hi", "hello", "good morning", "namaste", "hey"]:
        res_g = classify_ingress_intent(greet, is_image=False, sender_role="OPERATOR")
        assert res_g.intent == IngressIntent.OPERATOR_GREETING
        assert res_g.category == "operator_greeting"

    # Operator text note -> OPERATOR_QUERY
    res_query = classify_ingress_intent("Need 100 cups", is_image=False, sender_role="OPERATOR")
    assert res_query.intent == IngressIntent.OPERATOR_QUERY
    assert res_query.priority == 50

    # Image payload -> ATTENDANCE_CHECKIN
    res_img = classify_ingress_intent("", is_image=True, sender_role="OPERATOR")
    assert res_img.intent == IngressIntent.ATTENDANCE_CHECKIN

    # System command -> SYSTEM_COMMAND
    res_cmd = classify_ingress_intent("help", is_image=False, sender_role="OPERATOR")
    assert res_cmd.intent == IngressIntent.SYSTEM_COMMAND

    # Kiosk switch -> SYSTEM_COMMAND
    res_kiosk = classify_ingress_intent("kiosk CANEBOT-PUNE-05", is_image=False, sender_role="OPERATOR")
    assert res_kiosk.intent == IngressIntent.SYSTEM_COMMAND


def test_classify_ingress_intent_manager() -> None:
    """Manager greetings and replies are detected based on sender role."""
    # Supervisor saying 'hi' -> MANAGER_GREETING
    res_greet = classify_ingress_intent("hi", is_image=False, sender_role="SUPERVISOR")
    assert res_greet.intent == IngressIntent.MANAGER_GREETING

    # Supervisor sending 'digest' -> MANAGER_GREETING
    res_digest = classify_ingress_intent("digest", is_image=False, sender_role="MANAGER")
    assert res_digest.intent == IngressIntent.MANAGER_GREETING

    # Quoted reply -> MANAGER_REPLY
    res_reply = classify_ingress_intent(
        "Technician is on the way",
        is_image=False,
        sender_role="SUPERVISOR",
        has_quoted_reply=True,
    )
    assert res_reply.intent == IngressIntent.MANAGER_REPLY


def test_whatsapp_webhook_operator_query_routes_to_reporting_manager() -> None:
    """Inbound operator query automatically routes to reporting manager in InternalMessageQueue."""
    db = DatabaseService.get_instance()

    # Register manager
    db.register_employee(
        emp_code="MGR-1042",
        full_name="Rajesh Sharma",
        phone_number="+919811224400",
        assigned_kiosk_id="CANEBOT-PUNE-05",
        role="SUPERVISOR",
        status="ACTIVE",
    )

    # Register operator reporting to MGR-1042
    db.register_employee(
        emp_code="EMP-2001",
        full_name="Suresh Kumar",
        phone_number="+919811225500",
        assigned_kiosk_id="CANEBOT-PUNE-05",
        role="OPERATOR",
        reporting_manager_emp_code="MGR-1042",
        status="ACTIVE",
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "10001"},
                            "contacts": [{"profile": {"name": "Suresh"}, "wa_id": "919811225500"}],
                            "messages": [
                                {
                                    "from": "919811225500",
                                    "id": "wamid.op_query_1",
                                    "timestamp": "1710400000",
                                    "text": {"body": "Need 200 cups and cane stock"},
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

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "EVENT_RECEIVED"
    assert "Message Dispatched to Rajesh Sharma (MGR-1042)" in data["reply_message"]

    # Verify message enqueued for MGR-1042
    pending = db.get_pending_messages_for_recipient("+919811224400")
    assert len(pending) >= 1
    latest = pending[0]
    assert latest.recipient_emp_code == "MGR-1042"
    assert latest.sender_emp_code == "EMP-2001"
    assert "Need 200 cups" in latest.message_text
    assert latest.priority == 50


def test_whatsapp_webhook_operator_greeting_returns_self_service_status_and_does_not_alert_manager() -> None:
    """Operator sending 'hi' receives self-service status card without alerting reporting manager."""
    db = DatabaseService.get_instance()

    # Register manager
    db.register_employee(
        emp_code="MGR-9901",
        full_name="Anjali Patil",
        phone_number="+919811990001",
        assigned_kiosk_id="CANEBOT-PUNE-04",
        role="SUPERVISOR",
        status="ACTIVE",
    )

    # Register operator reporting to MGR-9901
    db.register_employee(
        emp_code="EMP-9902",
        full_name="Ganesh Jadhav",
        phone_number="+919811990002",
        assigned_kiosk_id="CANEBOT-PUNE-04",
        role="OPERATOR",
        reporting_manager_emp_code="MGR-9901",
        status="ACTIVE",
    )

    # Count manager's pending messages before greeting
    initial_pending = len(db.get_pending_messages_for_recipient("+919811990001"))

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "10001"},
                            "contacts": [{"profile": {"name": "Ganesh"}, "wa_id": "919811990002"}],
                            "messages": [
                                {
                                    "from": "919811990002",
                                    "id": "wamid.op_greet_1",
                                    "timestamp": "1710400000",
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

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "EVENT_RECEIVED"
    reply = data["reply_message"]

    # Verify self-service greeting content
    assert "👋 Hello Ganesh Jadhav!" in reply
    assert "CANEBOT-PUNE-04" in reply
    assert "Shift Attendance:" in reply
    assert "Chiller Temperature:" in reply

    # Crucial assertion: NO message enqueued for Anjali Patil (MGR-9901)
    new_pending = len(db.get_pending_messages_for_recipient("+919811990001"))
    assert new_pending == initial_pending

