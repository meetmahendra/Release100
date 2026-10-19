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

"""Unit tests for Phase 2 Hybrid Neuro-Symbolic Data Layer (FTS5 + 3-Layer Identity + Commitments + Facts)."""

from datetime import datetime, timezone
from pathlib import Path

from apps.mail_organizer.database.db_service import MailDatabaseService


def test_fts5_and_hybrid_search(tmp_path: Path) -> None:
    """Verify FTS5 indexing and hybrid BM25 + semantic similarity search."""
    db_file = tmp_path / "mail_hybrid_test.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")

    db.index_fts_and_semantic_chunk(
        tenant_id="t1",
        user_id=1,
        source_channel="EMAIL",
        msg_id="email-101",
        subject="Q3 CapEx Budget Revisions and PO-9982",
        body_clean="Attached is the revised Q3 CapEx budget spreadsheet for PO-9982 approval.",
        entity_tags="PO-9982,PRJ-ALPHA",
    )
    db.index_fts_and_semantic_chunk(
        tenant_id="t1",
        user_id=1,
        source_channel="WHATSAPP",
        msg_id="wa-202",
        subject="Verbal update on PO-9982",
        body_clean="Spoke with vendor; they agreed to a 10% discount on PO-9982 if signed by Friday.",
        entity_tags="PO-9982,PRJ-ALPHA",
    )

    results = db.search_hybrid_context(
        tenant_id="t1",
        user_id=1,
        query_terms=["PO-9982", "budget", "discount"],
        entities=["PO-9982"],
        limit=5,
    )
    assert len(results["fts_matches"]) >= 1
    assert len(results["semantic_matches"]) >= 2
    msg_ids = {r["msg_id"] for r in results["semantic_matches"]}
    assert "email-101" in msg_ids
    assert "wa-202" in msg_ids


def test_3layer_identity_resolution_and_salutation_learning(tmp_path: Path) -> None:
    """Verify Layer 1 Exact, Layer 2 Scoped Fuzzy, Layer 3 Quarantine, and Salutation Learning."""
    db_file = tmp_path / "mail_identity_test.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")

    # First encounter creates canonical ContactEntity + EMAIL alias
    c_init = db.resolve_contact_alias_3layer(
        tenant_id="t1",
        user_id=1,
        channel_type="EMAIL",
        raw_identifier="sanjay.patil@acme-corp.com",
        display_name="Sanjay Patil",
        organization="Acme",
    )
    contact_id = int(c_init["contact_id"])
    assert c_init["resolution_status"] == "VERIFIED"

    # Layer 1: Exact Email Match hits LAYER_1_EXACT
    l1 = db.resolve_contact_alias_3layer(
        tenant_id="t1",
        user_id=1,
        channel_type="EMAIL",
        raw_identifier="sanjay.patil@acme-corp.com",
        display_name="Sanjay Patil",
    )
    assert l1["resolution_layer"] == "LAYER_1_EXACT"
    assert l1["contact_id"] == contact_id

    # Layer 2: Scoped Fuzzy match on same organization with high similarity
    l2 = db.resolve_contact_alias_3layer(
        tenant_id="t1",
        user_id=1,
        channel_type="WHATSAPP",
        raw_identifier="+919822001122",
        display_name="Sanjay Patil",
        organization="Acme",
    )
    assert l2["resolution_layer"] == "LAYER_2_SCOPED_FUZZY"
    assert l2["contact_id"] == contact_id
    assert l2["resolution_status"] == "VERIFIED"

    # Layer 3: Ambiguous partial display name (e.g. "Sanjay P") -> Quarantined
    l3 = db.resolve_contact_alias_3layer(
        tenant_id="t1",
        user_id=1,
        channel_type="WHATSAPP",
        raw_identifier="+919800000001",
        display_name="Sanjay P",
        organization="External",
    )
    assert l3["resolution_layer"] == "LAYER_3_QUARANTINE"
    assert l3["resolution_status"] == "PROVISIONAL_QUARANTINE"

    quarantined = db.get_quarantined_aliases("t1")
    assert len(quarantined) == 1
    alias_id = int(quarantined[0]["id"])

    # Resolve quarantine via HITL
    resolved = db.resolve_quarantined_alias(
        alias_id=alias_id,
        approve=True,
        target_contact_id=contact_id,
        tenant_id="t1",
    )
    assert resolved is True
    assert len(db.get_quarantined_aliases("t1")) == 0

    # Salutation learning: 1 external sender does NOT promote immediately
    s1 = db.record_observed_salutation(
        tenant_id="t1",
        contact_id=contact_id,
        salutation="Dear Sanjay Ji,",
        is_outbound_from_user=False,
        observer_sender="colleague1@acme-corp.com",
    )
    assert "Sanjay Ji" not in s1

    # 2nd distinct external sender promotes salutation
    s2 = db.record_observed_salutation(
        tenant_id="t1",
        contact_id=contact_id,
        salutation="Hi Sanjay Ji,",
        is_outbound_from_user=False,
        observer_sender="colleague2@acme-corp.com",
    )
    assert "Sanjay Ji" in s2


def test_role_taxonomy_commitments_facts_and_consent(tmp_path: Path) -> None:
    """Verify Role Taxonomy templates, CommitmentLedger, EntityFactGraph supersession, and ConsentAuditLog."""
    db_file = tmp_path / "mail_ledger_test.db"
    db = MailDatabaseService(f"sqlite:///{db_file}")

    # Clean-slate default returns 7 canonical categories
    default_cats = db.get_active_user_taxonomy(tenant_id="t1", user_id=1)
    assert len(default_cats) == 7
    cat_names = {c["category_name"] for c in default_cats}
    assert "@Action" in cat_names

    # Select Role Pack SWE_IC
    applied = db.select_user_role_taxonomy(role_key="SWE_IC", tenant_id="t1", user_id=1)
    assert len(applied) == 6
    assert any(c["category_name"] == "@CodeReview" for c in applied)

    # Bidirectional Commitment Ledger
    rec = db.upsert_commitment(
        source_msg_id="msg-555",
        deliverable_summary="Send revised architecture diagram by Friday",
        direction="OWED_BY_ME",
        speech_act="COMMIT",
        source_channel="EMAIL",
        counterparty_handle="sanjay.patil@acme-corp.com",
        raw_deadline_text="Friday 5pm",
        resolved_due_at=datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc),
        tenant_id="t1",
        user_id=1,
    )
    assert rec.commitment_uid.startswith("CMT-")
    open_items = db.list_commitments(tenant_id="t1", user_id=1, direction="OWED_BY_ME", active_only=True)
    assert len(open_items) == 1
    assert open_items[0]["deliverable_summary"] == "Send revised architecture diagram by Friday"

    assert db.update_commitment_status(rec.commitment_uid, "FULFILLED", tenant_id="t1") is True
    assert len(db.list_commitments(tenant_id="t1", user_id=1, direction="OWED_BY_ME", active_only=True)) == 0

    # Entity Fact Graph with chronological supersession
    f1 = db.upsert_entity_fact(
        subject_entity="PO-9982",
        predicate="DELIVERY_DATE",
        object_value="2026-11-01",
        source_msg_id="email-1",
        source_channel="EMAIL",
        tenant_id="t1",
        user_id=1,
    )
    f2 = db.upsert_entity_fact(
        subject_entity="PO-9982",
        predicate="DELIVERY_DATE",
        object_value="2026-11-15",
        source_msg_id="wa-2",
        source_channel="WHATSAPP",
        tenant_id="t1",
        user_id=1,
    )
    assert f2.id != f1.id
    active_facts = db.query_entity_facts(
        tenant_id="t1",
        subject_entities=["PO-9982"],
        include_superseded=False,
    )
    assert len(active_facts) == 1
    assert active_facts[0]["object_value"] == "2026-11-15"
    assert active_facts[0]["source_channel"] == "WHATSAPP"

    # Missing Artifact Request & Resolution
    req = db.create_missing_artifact_request(
        gmail_id="email-999",
        artifact_type="ATTACHMENT_MISSING",
        artifact_description="Q3_CapEx_Model.xlsx",
        tenant_id="t1",
        user_id=1,
    )
    pending_reqs = db.get_pending_artifact_requests("t1")
    assert len(pending_reqs) == 1
    assert pending_reqs[0].id == req.id
    resolved_req = db.resolve_missing_artifact_request(
        gmail_id="email-999",
        resolved_content_summary="Approved CapEx is $120,000",
        tenant_id="t1",
    )
    assert resolved_req is not None
    assert resolved_req.status == "RESOLVED"
    assert len(db.get_pending_artifact_requests("t1")) == 0

    # Consent Audit Log
    log_rec = db.record_consent_audit_log(
        session_id="meet-123",
        channel_type="MEETING_TRANSCRIPT",
        jurisdiction_policy="ALL_PARTY",
        participants=["alice@acme.com", "bob@acme.com"],
        all_parties_consented=True,
        tenant_id="t1",
        user_id=1,
    )
    assert log_rec.id > 0
    assert len(log_rec.consent_proof_hash) == 64
