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

"""Unit tests for LangGraph StateGraph, discrete nodes, and Zero-Deletion policy."""

import pytest
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.nodes.guardrail_node import guardrail_node
from apps.mail_organizer.graph.nodes.ownership_node import ownership_node
from apps.mail_organizer.graph.nodes.pre_check_node import pre_check_node
from apps.mail_organizer.graph.state import MailOrganizerState
from apps.mail_organizer.graph.state_graph import MailOrganizerWorkflow


@pytest.fixture
def workflow(tmp_path):
    db_file = tmp_path / "test_wf.db"
    db_service = MailDatabaseService(db_url=f"sqlite:///{db_file}")
    # Pre-seed VIP rule
    db_service.add_rule(rule_type="vip", pattern="vip-investor@fund.com", action="tag_vip")
    return MailOrganizerWorkflow(db_service=db_service)


@pytest.mark.asyncio
async def test_layer_0_pre_check_vip():
    state: MailOrganizerState = {
        "gmail_id": "msg_vip",
        "sender": "vip-investor@fund.com",
        "subject": "Quarterly Update Call",
        "body": "Let's review the financials.",
    }
    res = await pre_check_node(state, vip_senders=["vip-investor@fund.com"])
    assert res["is_vip"] is True


@pytest.mark.asyncio
async def test_layer_0_pre_check_critical_subject():
    state: MailOrganizerState = {
        "gmail_id": "msg_urg",
        "sender": "alerts@monitoring.com",
        "subject": "CRITICAL: Server Outage in Region US-East",
        "body": "Immediate action required.",
    }
    res = await pre_check_node(state)
    assert res["has_critical_subject"] is True


@pytest.mark.asyncio
async def test_layer_2_guardrail_diverts_sub_threshold():
    state: MailOrganizerState = {
        "gmail_id": "msg_low_conf",
        "confidence_score": 0.72,
        "category": "@Action",
    }
    res = await guardrail_node(state)
    assert res["safety_override"] is True
    assert any(a.get("label") == "_LLM/NeedsReview" for a in res.get("gmail_actions", []))


@pytest.mark.asyncio
async def test_ownership_node_observer_role():
    state: MailOrganizerState = {
        "to_recipients": ["manager@company.com"],
        "cc_recipients": ["depali@company.com"],
        "body": "FYI keeping you in the loop on this update.",
    }
    res = await ownership_node(state)
    assert res["responsibility_role"] == "OBSERVER_ONLY"
    assert res["is_reply_necessary"] is False


@pytest.mark.asyncio
async def test_full_workflow_zero_deletion_promo(workflow):
    state: MailOrganizerState = {
        "gmail_id": "msg_promo_01",
        "thread_id": "th_promo_01",
        "sender": "marketing@newsletter.com",
        "to_recipients": ["depali@company.com"],
        "subject": "Discount Sale 50% Off Everything Today!",
        "body": "Unsubscribe anytime. Click here for 50% discount.",
        "execution_mode": "shadow",
    }
    final_state = await workflow.execute(state)
    assert final_state["category"] == "@Promotions"
    # Zero-deletion verify: promotions get moved out of inbox and labeled without deletion
    actions = final_state.get("gmail_actions") or []
    assert any(a.get("label") == "_LLM/Promotions" for a in actions)


@pytest.mark.asyncio
async def test_full_workflow_urgent_meeting(workflow):
    state: MailOrganizerState = {
        "gmail_id": "msg_meet_01",
        "thread_id": "th_meet_01",
        "sender": "ceo@customer.com",
        "to_recipients": ["depali@company.com"],
        "subject": "URGENT: Contract discussion meeting tomorrow morning",
        "body": "Can we meet tomorrow at 10 AM to finalize the agreement terms?",
        "execution_mode": "shadow",
    }
    final_state = await workflow.execute(state)
    assert final_state["category"] in ("@Meeting", "@Urgent", "@Action")
    assert final_state.get("safety_override") is False
