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
Synthetic Unit Tests for Phase 2 Operational Defect Fixes:
- ISSUE-006: Clean-slate zero kiosk & unregistered location guard
- ISSUE-007: Unregistered sender Layer 0 rejection (no mock manager escalation)
- ISSUE-008: Outbound manager push notification & role triage resolution
- ENHANCEMENT-001: Multi-role operator/manager support
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from apps.temperature_marker.graph.nodes.layer0_location_node import layer0_location_node
from apps.temperature_marker.services.intent_router import IngressIntent, classify_ingress_intent
from core_platform.app.ingress.whatsapp_router import dispatch_whatsapp_payload
from core_platform.main import app


client = TestClient(app)


@pytest.mark.anyio
async def test_issue006_ghost_kiosk_clean_slate_and_unregistered_location() -> None:
    """ISSUE-006: Clean-slate with 0 registered kiosks or unregistered phone returns clear rejection."""
    # 1. Test layer0_location_node with empty roster
    mock_kg = KnowledgeGraphService()
    mock_kg.roster.kiosks = {}  # Empty roster simulation

    state = {
        "kiosk_id": "CANEBOT-UNKNOWN",
        "user_coords": (18.5204, 73.8567),
        "sender_phone": "+919999988888",
    }
    res_state = await layer0_location_node(state, mock_kg)
    assert res_state["geofence_verified"] is False
    assert res_state["layer_0_passed"] is False
    assert "No active kiosks are configured" in res_state["reply_message"]

    # 2. Test WhatsApp webhook receiving native location from unregistered sender
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919999977777",
                        "type": "location",
                        "location": {
                            "latitude": 18.5077,
                            "longitude": 73.7913,
                        }
                    }]
                }
            }]
        }]
    }
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http:
        mock_http.return_value = MagicMock(is_success=True, json=lambda: {"messages": [{"id": "MSG-TEST"}]})
        res = await dispatch_whatsapp_payload(payload)
        assert res["status"] == "EVENT_RECEIVED"
        assert "not registered with any CaneBot kiosk" in res["reply_message"]


@pytest.mark.anyio
async def test_issue007_ghost_operator_unregistered_text_rejection() -> None:
    """ISSUE-007: Unregistered sender texting general query must NOT enqueue mock manager messages."""
    db = DatabaseService.get_instance()
    unreg_phone = "+919999966666"

    # Verify phone not in db
    emp = db.get_employee_by_phone(unreg_phone)
    assert emp is None

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919999966666",
                        "type": "text",
                        "text": {"body": "I need more cups urgently at the station"}
                    }]
                }
            }]
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http:
        mock_http.return_value = MagicMock(is_success=True, json=lambda: {"messages": [{"id": "MSG-TEST"}]})
        res = await dispatch_whatsapp_payload(payload)
        assert res["status"] == "EVENT_RECEIVED"
        assert "not registered in the system" in res["reply_message"]
        assert "Message Dispatched" not in res["reply_message"]


@pytest.mark.anyio
async def test_issue008_manager_push_notification_and_triage_flow() -> None:
    """ISSUE-008: Operator query sends outbound WhatsApp push to manager; manager greeting shows digest."""
    db = DatabaseService.get_instance()
    
    # 1. Setup registered manager and operator
    mgr_phone = "+919888811111"
    op_phone = "+919888822222"
    
    db.register_employee(
        emp_code="MGR-5001",
        full_name="Fleet Lead Vikram",
        phone_number=mgr_phone,
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="ACTIVE",
        role="MANAGER",
    )
    db.register_employee(
        emp_code="EMP-5002",
        full_name="Operator Sunil",
        phone_number=op_phone,
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="ACTIVE",
        role="OPERATOR",
        reporting_manager_emp_code="MGR-5001",
    )

    # 2. Operator sends routine operational query
    op_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919888822222",
                        "type": "text",
                        "text": {"body": "The sugarcane stalk bin is full"}
                    }]
                }
            }]
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http:
        mock_http.return_value = MagicMock(is_success=True, json=lambda: {"messages": [{"id": "MSG-TEST"}]})
        with patch("apps.temperature_marker.services.whatsapp_handler.send_whatsapp_raw_message", new_callable=AsyncMock) as mock_push:
            res_op = await dispatch_whatsapp_payload(op_payload)
            assert res_op["status"] == "EVENT_RECEIVED"
            assert "Message Dispatched to Fleet Lead Vikram" in res_op["reply_message"]
            
            # Verify manager received outbound WhatsApp push notification (ISSUE-008 Defect 8.1)
            mock_push.assert_called()
            call_args = mock_push.call_args[1]
            assert call_args["to_phone"] == mgr_phone
            assert "New Operator Message" in call_args["text"]
            assert "sugarcane stalk bin" in call_args["text"]

    # 3. Manager sends "Hello" to triage pending messages
    mgr_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919888811111",
                        "type": "text",
                        "text": {"body": "Hello"}
                    }]
                }
            }]
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http:
        mock_http.return_value = MagicMock(is_success=True, json=lambda: {"messages": [{"id": "MSG-TEST"}]})
        res_mgr = await dispatch_whatsapp_payload(mgr_payload)
        assert res_mgr["status"] == "EVENT_RECEIVED"
        assert "messages pending" in res_mgr["reply_message"]
        assert "The sugarcane stalk bin is full" in res_mgr["reply_message"]
        assert "Reply to this message to answer directly" in res_mgr["reply_message"]


def test_enhancement001_multi_role_support() -> None:
    """ENHANCEMENT-001: Staff with dual role 'OPERATOR|MANAGER' is recognized as manager."""
    classification = classify_ingress_intent(
        text="Hello",
        is_image=False,
        sender_role="OPERATOR|MANAGER",
    )
    assert classification.intent == IngressIntent.MANAGER_GREETING
