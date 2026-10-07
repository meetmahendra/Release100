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
Synthetic Unit Tests for Phase 3 Conversational Intelligence & Memory:
- ISSUE-004: Multi-turn SQLite dialogue memory
- ISSUE-002: Natural language question answering & grounded assistant
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from apps.temperature_marker.services.conversational_agent import generate_conversational_response
from core_platform.app.ingress.whatsapp_router import dispatch_whatsapp_payload
from core_platform.app.messaging.conversation_memory import ConversationMemory


def test_conversation_memory_crud_and_fifo(tmp_path: Path) -> None:
    """Verify SQLite-backed ConversationMemory records, retrieves, and clears dialogue turns."""
    mem = ConversationMemory(db_path=tmp_path / "test_conv.db")
    phone = "+919876500001"

    # Initially empty
    assert mem.get_recent_turns(phone) == []
    assert mem.format_history_for_prompt(phone) == ""

    # Record 3 turns
    mem.record_turn(phone, "user", "What is the chiller limit?", "CONV_QUERY")
    mem.record_turn(phone, "assistant", "Chiller temperature must be between 2°C and 8°C.", "CONV_REPLY")
    mem.record_turn(phone, "user", "Is 4.5 fine?", "CONV_QUERY")

    turns = mem.get_recent_turns(phone, limit=10)
    assert len(turns) == 3
    assert turns[0]["role"] == "user"
    assert turns[0]["content"] == "What is the chiller limit?"
    assert turns[2]["role"] == "user"
    assert turns[2]["content"] == "Is 4.5 fine?"

    prompt_ctx = mem.format_history_for_prompt(phone)
    assert "Operator: What is the chiller limit?" in prompt_ctx
    assert "KioskNode Coordinator: Chiller temperature must be between 2°C and 8°C." in prompt_ctx

    # Clear history
    mem.clear_history(phone)
    assert mem.get_recent_turns(phone) == []


@pytest.mark.anyio
async def test_conversational_agent_grounded_response() -> None:
    """Verify conversational agent returns grounded answer using station and HACCP metadata."""
    db = DatabaseService.get_instance()
    kg = KnowledgeGraphService()

    phone = "+919876500002"
    emp = db.register_employee(
        emp_code="EMP-7001",
        full_name="Anil Jadhav",
        phone_number=phone,
        assigned_kiosk_id="NODE-PUNE-04",
        status="ACTIVE",
    )

    # Test with mocked LLM response
    mock_llm_res = {"text": "Yes, 4.5°C is well within the required 2.0°C to 8.0°C HACCP range for KioskNode Pune."}
    with patch("core_platform.app.llm.gateway.LLMGateway.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = mock_llm_res

        reply = await generate_conversational_response(
            sender_phone=phone,
            user_text="Is 4.5 C okay for chiller?",
            emp=emp,
            kiosk_id="NODE-PUNE-04",
            kg_service=kg,
            db_service=db,
        )

        assert "4.5°C" in reply
        assert "HACCP" in reply

        # Verify system instruction included operator and kiosk grounding
        call_args = mock_gen.call_args[1]
        assert "Anil Jadhav" in call_args["system_instruction"]
        assert "NODE-PUNE-04" in call_args["system_instruction"]


@pytest.mark.anyio
async def test_whatsapp_operator_procedural_question_routing() -> None:
    """Verify operator procedural question triggers conversational agent rather than manager dispatch."""
    db = DatabaseService.get_instance()
    phone = "+919876500003"

    db.register_employee(
        emp_code="EMP-7002",
        full_name="Kavita Shinde",
        phone_number=phone,
        assigned_kiosk_id="NODE-PUNE-04",
        status="ACTIVE",
    )

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919876500003",
                        "type": "text",
                        "text": {"body": "What is the temperature range for chiller?"}
                    }]
                }
            }]
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http:
        mock_http.return_value = MagicMock(is_success=True, json=lambda: {"messages": [{"id": "MSG-TEST"}]})
        res = await dispatch_whatsapp_payload(payload)
        assert res["status"] == "EVENT_RECEIVED"
        assert "Chiller temperature" in res["reply_message"]
        assert "Message Dispatched" not in res["reply_message"]
