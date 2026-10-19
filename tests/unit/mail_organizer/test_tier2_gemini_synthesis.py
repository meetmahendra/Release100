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

"""Unit tests for Phase 4 Tier 2 4-Stage Gemini Pipeline & Missing-Reference HITL Gate."""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.nodes.context_assembler_node import context_assembler_node
from apps.mail_organizer.graph.nodes.draft_node import draft_node
from apps.mail_organizer.graph.nodes.missing_ref_gate_node import missing_ref_gate_node
from apps.mail_organizer.graph.state import MailOrganizerState
from apps.mail_organizer.graph.state_graph import MailOrganizerWorkflow


@pytest.mark.asyncio
async def test_stage_a_c_d_citation_grounded_draft_and_learned_salutation(tmp_path: Path) -> None:
    """Verify Stage A Hybrid Context + Stage C Citation-Grounded Draft + Learned Salutation + Stage D Self-Critique."""
    db_file = tmp_path / "tier2_test.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")

    # Seed superseding EntityFactGraph triple from WhatsApp
    db.upsert_entity_fact(
        subject_entity="PO-8801",
        predicate="DELIVERY_DATE",
        object_value="2026-11-10",
        source_msg_id="email-old",
        source_channel="EMAIL",
        tenant_id="t1",
        user_id=1,
    )
    db.upsert_entity_fact(
        subject_entity="PO-8801",
        predicate="DELIVERY_DATE",
        object_value="2026-11-22",
        source_msg_id="wa-99",
        source_channel="WHATSAPP",
        tenant_id="t1",
        user_id=1,
    )

    state: MailOrganizerState = {
        "tenant_id": "t1",
        "user_id": 1,
        "gmail_id": "msg_po_8801",
        "sender": "sanjay@vendor.com",
        "subject": "PO-8801 Delivery Confirmation",
        "body": "Can you confirm the updated delivery date for PO-8801?",
        "category": "@Action",
        "responsibility_role": "PRIMARY_ACTIONEE",
        "is_reply_necessary": True,
        "learned_salutations": ["Sanjay Ji"],
    }

    state = await context_assembler_node(state, db_service=db)
    assert len(state["hybrid_context_bundle"]["entity_facts"]) == 1
    assert state["hybrid_context_bundle"]["entity_facts"][0]["object_value"] == "2026-11-22"
    assert "[Whatsapp #wa-99]" in state["citation_ids"]

    state = await missing_ref_gate_node(state, db_service=db)
    assert state["missing_artifact_detected"] is False

    state = await draft_node(state)
    reply = state["suggested_reply"] or ""
    assert reply.startswith("Hi Sanjay Ji,")
    assert "2026-11-22" in reply or "November 22" in reply
    assert "[Whatsapp #wa-99]" in reply
    assert state["self_critique_passed"] is True
    assert state["infographic_card_spec"] is not None


@pytest.mark.asyncio
async def test_stage_b_missing_reference_gate_pauses_drafting(tmp_path: Path) -> None:
    """Verify Stage B detects missing attachment/reference and pauses autonomous draft generation."""
    db_file = tmp_path / "missing_ref_test.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")

    state: MailOrganizerState = {
        "tenant_id": "t1",
        "user_id": 1,
        "gmail_id": "msg_missing_xlsx",
        "thread_id": "th_missing_xlsx",
        "sender": "cfo@partner.com",
        "subject": "CapEx Sign-off",
        "body": "Please approve the numbers in the attached spreadsheet Q3_CapEx_Model.xlsx by EOD.",
        "category": "@Action",
        "responsibility_role": "PRIMARY_ACTIONEE",
        "is_reply_necessary": True,
        "attachments_present": [],
    }

    state = await context_assembler_node(state, db_service=db)
    state = await missing_ref_gate_node(state, db_service=db)
    assert state["missing_artifact_detected"] is True
    assert state["missing_artifact_type"] == "ATTACHMENT_MISSING"

    state = await draft_node(state)
    assert state["suggested_reply"] is None
    assert "WAITING_FOR_USER_ARTIFACT" in (state.get("self_critique_notes") or "")

    pending = db.get_pending_artifact_requests("t1")
    assert len(pending) == 1
    assert pending[0].gmail_id == "msg_missing_xlsx"


@pytest.mark.asyncio
async def test_stage_d_self_critique_clamps_ungrounded_currency() -> None:
    """Verify Stage D Self-Critique clamps hallucinated dollar figures not present in email or context."""
    state: MailOrganizerState = {
        "gmail_id": "msg_halluc_1",
        "sender": "client@corp.com",
        "subject": "Project Scope",
        "body": "Please confirm we are aligned on the timeline.",
        "category": "@Action",
        "responsibility_role": "PRIMARY_ACTIONEE",
        "is_reply_necessary": True,
    }

    with patch("core_platform.app.llm.gateway.LLMGateway.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {"draft": "Hi Client,\nWe confirm the budget of $999,999 for the timeline.\nBest regards,\nLead"}
        state = await draft_node(state)

    assert state["self_critique_passed"] is False
    assert "$999,999" not in (state["suggested_reply"] or "")
    assert "[PENDING_VERIFIED_AMOUNT]" in (state["suggested_reply"] or "")


@pytest.mark.asyncio
async def test_full_11_node_workflow_persists_commitments_and_facts(tmp_path: Path) -> None:
    """Verify full 11-node MailOrganizerWorkflow persists FTS5, CommitmentLedger, and EntityFactGraph."""
    db_file = tmp_path / "full_11node_wf.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")
    wf = MailOrganizerWorkflow(db_service=db)

    state: MailOrganizerState = {
        "tenant_id": "t1",
        "user_id": 1,
        "gmail_id": "msg_full_11",
        "thread_id": "th_full_11",
        "sender": "ops@vendor.com",
        "to_recipients": ["user@company.com"],
        "subject": "PO-7744 Calibration Update",
        "body": "Please review and approve the calibration report for PO-7744 ($18,500) before Friday.",
        "execution_mode": "shadow",
    }

    final_state = await wf.execute(state)
    assert final_state["category"] in ("@Action", "@Financial")
    assert len(db.list_commitments(tenant_id="t1")) >= 1
    assert len(db.query_entity_facts(tenant_id="t1", subject_entities=["PO-7744"])) >= 1
