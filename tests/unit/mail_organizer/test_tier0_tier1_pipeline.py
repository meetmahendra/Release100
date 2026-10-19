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

"""Unit tests for Phase 3 Tier 0 & Tier 1 Pipeline (RFC Headers, Vocative Ownership, Jev Multi-Head, Commitments)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.nodes.classify_node import classify_node
from apps.mail_organizer.graph.nodes.ownership_node import ownership_node
from apps.mail_organizer.graph.nodes.pm_extract_node import pm_extract_node
from apps.mail_organizer.graph.nodes.pre_check_node import pre_check_node
from apps.mail_organizer.graph.state import MailOrganizerState
from core_platform.app.llm.base import DecisionResult, MultiQuestionDecisionResult


@pytest.mark.asyncio
async def test_tier0_rfc_headers_and_contact_entity_vip(tmp_path: Path) -> None:
    """Verify Tier 0 RFC 5322/3834 header detection and ContactEntity 3-layer VIP lookup."""
    db_file = tmp_path / "tier0_test.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")

    # Seed a VIP ContactEntity
    db.resolve_contact_alias_3layer(
        tenant_id="t1",
        user_id=1,
        channel_type="EMAIL",
        raw_identifier="board.chair@venture.com",
        display_name="Board Chair",
        is_vip=True,
    )

    state_vip: MailOrganizerState = {
        "tenant_id": "t1",
        "user_id": 1,
        "gmail_id": "m_vip_1",
        "sender": "board.chair@venture.com",
        "subject": "Board Strategy Sync",
        "body": "Please review Q4 numbers.",
    }
    res_vip = await pre_check_node(state_vip, db_service=db)
    assert res_vip["is_vip"] is True
    assert res_vip["resolved_contact_id"] is not None
    assert res_vip["contact_resolution_layer"] == "LAYER_1_EXACT"

    # RFC 3834 Auto-Submitted & List-Unsubscribe check
    state_list: MailOrganizerState = {
        "gmail_id": "m_list_1",
        "sender": "digest@saas-updates.com",
        "subject": "Weekly Digest",
        "body": "Here are this week's updates.",
        "rfc_headers": {
            "List-Unsubscribe": "<mailto:unsub@saas-updates.com>",
            "Precedence": "bulk",
        },
    }
    res_list = await pre_check_node(state_list)
    assert res_list["has_list_unsubscribe"] is True
    assert res_list["is_no_reply"] is True
    assert res_list["is_auto_reply"] is True


@pytest.mark.asyncio
async def test_4state_ownership_and_dynamic_vocative_promotion() -> None:
    """Verify 4-state header_recipient_role and dynamic vocative promotion from CC to PRIMARY_ACTIONEE."""
    # User is in CC (OBSERVER_CC), but body vocatively addresses Mahendra
    state: MailOrganizerState = {
        "gmail_id": "m_voc_1",
        "sender": "director@client.com",
        "to_recipients": ["pm@company.com", "lead@company.com"],
        "cc_recipients": ["mahendra@company.com"],
        "user_name": "Mahendra Gurav",
        "user_email": "mahendra@company.com",
        "subject": "PO-9982 Architecture Sign-off",
        "body": "Hi Mahendra,\nPlease review and approve the revised architecture diagram by Friday.",
    }

    state = await pre_check_node(state)
    state = await ownership_node(state, user_email="mahendra@company.com")
    assert state["header_recipient_role"] == "OBSERVER_CC"
    assert state["responsibility_role"] == "OBSERVER_ONLY"

    # Now run Tier 1 classify_node: should extract salutation "Mahendra" and promote from CC to PRIMARY_ACTIONEE!
    state = await classify_node(state)
    assert state["salutation_extracted"] == "Mahendra"
    assert state["was_promoted_from_cc"] is True
    assert state["responsibility_role"] == "PRIMARY_ACTIONEE"
    assert state["is_reply_necessary"] is True
    assert "vocative_promoted" in state["context_tags"]


@pytest.mark.asyncio
async def test_tier1_jev_multi_head_and_commitment_extraction() -> None:
    """Verify single-pass Jev classify_multi and bidirectional CommitmentLedger + EntityFactGraph extraction."""
    state: MailOrganizerState = {
        "gmail_id": "m_jev_1",
        "thread_id": "th_jev_1",
        "sender": "vendor@supplier.com",
        "to_recipients": ["user@company.com"],
        "subject": "PO-4451 Delivery Commitment",
        "body": "Hi User,\nWe will deliver the PO-4451 server racks for $45,000 by Friday.",
    }

    mock_multi = MultiQuestionDecisionResult(
        answers={
            "category": DecisionResult(selected_choice="@WaitingOn", confidence=0.95, reasoning="Vendor commitment", latency_ms=18.0),
            "speech_act": DecisionResult(selected_choice="COMMIT", confidence=0.96, reasoning="Promise to deliver", latency_ms=18.0),
            "vocative_ownership": DecisionResult(selected_choice="ADDRESSED_TO_USER", confidence=0.94, reasoning="Addressed to user", latency_ms=18.0),
            "urgency_band": DecisionResult(selected_choice="HIGH_7_8", confidence=0.91, reasoning="High priority PO", latency_ms=18.0),
        },
        latency_ms=18.0,
    )

    with patch("core_platform.app.llm.gateway.LLMGateway.classify_multi", new_callable=AsyncMock) as mock_cm:
        mock_cm.return_value = mock_multi
        state = await ownership_node(state)
        state = await classify_node(state)

    assert state["category"] == "@WaitingOn"
    assert state["speech_act"] == "COMMIT"
    assert state["urgency_score"] == 8

    state = await pm_extract_node(state)
    commitments = state.get("extracted_commitments") or []
    assert len(commitments) >= 1
    assert commitments[0]["direction"] == "OWED_TO_ME"
    assert commitments[0]["speech_act"] == "COMMIT"

    facts = state.get("extracted_entity_facts") or []
    assert len(facts) >= 1
    predicates = {f["predicate"] for f in facts}
    assert "AMOUNT" in predicates
