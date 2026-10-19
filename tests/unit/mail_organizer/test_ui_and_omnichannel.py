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

"""Phase 6 unit tests for Admin UI (Taxonomy, Alias Review, Commitments) & Omnichannel Consent/Ingestor."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.mcp.tools import MailOrganizerMCPTools
from apps.mail_organizer.services.omnichannel_ingestor import OmnichannelContextIngestor
from apps.mail_organizer.ui import routes as ui_routes
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.main import app


@pytest.fixture
def isolated_ui_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Create a TestClient backed by an isolated temporary MailDatabaseService."""
    db_path = tmp_path / "phase6_ui_test.db"
    isolated_db = MailDatabaseService(db_url=f"sqlite:///{db_path}")
    monkeypatch.setattr(ui_routes, "_db_service", isolated_db)

    client = TestClient(app)
    token = create_jwt_token("admin", ["admin"], ["all", "mail_organizer"])
    client.cookies.set("admin_token", token)
    return client, isolated_db


def test_rules_ui_actionable_dom_and_clean_slate_roundtrip_mutations(
    isolated_ui_client: Any,
) -> None:
    """Verify actionable DOM invariants and Clean-Slate GET -> POST -> GET mutations on /rules."""
    client, db = isolated_ui_client

    # Seed an initial contact + an ambiguous Layer 3 quarantined alias (0.60 <= score < 0.88)
    db.resolve_contact_alias_3layer(
        tenant_id="default_tenant",
        user_id=None,
        channel_type="EMAIL",
        raw_identifier="rajesh.kumar@acme.com",
        display_name="Rajesh Kumar",
        organization="Acme",
    )
    ambig = db.resolve_contact_alias_3layer(
        tenant_id="default_tenant",
        user_id=None,
        channel_type="WHATSAPP",
        raw_identifier="+919876543210",
        display_name="Rajesh K",
        organization="ExternalOrg",
    )
    assert ambig["resolution_status"] == "PROVISIONAL_QUARANTINE"
    quarantined = db.get_quarantined_aliases(tenant_id="default_tenant")
    assert len(quarantined) == 1
    alias_id = quarantined[0]["id"]

    # Seed an active commitment
    c_rec = db.upsert_commitment(
        source_msg_id="msg_ui_test_1",
        deliverable_summary="Send revised Q3 financial deck",
        direction="OWED_BY_ME",
        speech_act="COMMIT",
        source_channel="EMAIL",
        counterparty_handle="client@acme.com",
        tenant_id="default_tenant",
    )
    commitment_uid = c_rec.commitment_uid

    # 1. GET (default state) & verify Actionable DOM invariants
    res_get = client.get("/admin/apps/mail-organizer/rules")
    assert res_get.status_code == 200
    html = res_get.text
    assert 'action="/admin/apps/mail-organizer/taxonomy/select"' in html
    assert f'action="/admin/apps/mail-organizer/aliases/{alias_id}/resolve"' in html
    assert f'action="/admin/apps/mail-organizer/commitments/{commitment_uid}/status"' in html
    assert "Role-Adaptive Triage Taxonomy (5 Canonical Role Packs)" in html
    assert "3-Layer Alias Resolution Quarantine Queue" in html
    assert "Bidirectional Commitment Ledger" in html

    # 2. POST (mutate taxonomy preset -> SWE_IC)
    res_tax = client.post(
        "/admin/apps/mail-organizer/taxonomy/select",
        data={"role_key": "SWE_IC"},
        follow_redirects=False,
    )
    assert res_tax.status_code == 303

    # 3. POST (mutate alias -> approve)
    res_alias = client.post(
        f"/admin/apps/mail-organizer/aliases/{alias_id}/resolve",
        data={"approve": "true"},
        follow_redirects=False,
    )
    assert res_alias.status_code == 303

    # 4. POST (mutate commitment -> FULFILLED)
    res_commit = client.post(
        f"/admin/apps/mail-organizer/commitments/{commitment_uid}/status",
        data={"status": "FULFILLED"},
        follow_redirects=False,
    )
    assert res_commit.status_code == 303

    # 5. GET (verify persisted state)
    res_after = client.get("/admin/apps/mail-organizer/rules")
    assert res_after.status_code == 200
    active_tax = db.get_active_user_taxonomy(tenant_id="default_tenant")
    assert any(c["category_name"] == "@CodeReview" for c in active_tax)
    assert len(db.get_quarantined_aliases(tenant_id="default_tenant")) == 0
    assert len(db.list_commitments(tenant_id="default_tenant", active_only=True)) == 0


@pytest.mark.asyncio
async def test_omnichannel_ingestor_consent_gate_and_mcp_tools(tmp_path: Path) -> None:
    """Verify CIPA/GDPR/DPDP consent gate blocks unconsented transcripts and MCP tools ingest & query hybrid context."""
    db_path = tmp_path / "phase6_omni_test.db"
    db = MailDatabaseService(db_url=f"sqlite:///{db_path}")
    ingestor = OmnichannelContextIngestor(db_service=db)
    mcp_tools = MailOrganizerMCPTools(db_service=db, omnichannel_ingestor=ingestor)

    # 1. Unconsented ingestion MUST raise PermissionError (Layer 0 legal guardrail)
    with pytest.raises(PermissionError, match="Omnichannel ingestion blocked"):
        await mcp_tools.mail_ingest_omnichannel_context(
            session_id="meet_unconsented_01",
            channel_type="MEETING_TRANSCRIPT",
            subject="Confidential Budget Call",
            transcript_or_text="Confidential call without consent banner",
            participants=["ceo@acme.com", "vendor@partner.com"],
            jurisdiction_policy="ALL_PARTY",
            all_parties_consented=False,
            tenant_id="tenant_acme",
        )

    # 2. Seed an initial email fact and supersede it via consented Google Meet session
    old_fact = db.upsert_entity_fact(
        subject_entity="PO-4421",
        predicate="AMOUNT",
        object_value="$40,000",
        source_msg_id="msg_old_budget",
        source_channel="EMAIL",
        tenant_id="tenant_acme",
    )
    assert old_fact.id is not None

    ingest_res = await mcp_tools.mail_ingest_omnichannel_context(
        session_id="meet_consented_02",
        channel_type="MEETING_TRANSCRIPT",
        subject="PO-4421 Scope Revision Call",
        transcript_or_text=(
            "Regarding PO-4421, we agreed to increase the budget cap to $55,000 "
            "and delivery date is 2026-11-15. I will send the updated SOW by Friday."
        ),
        participants=["pm@acme.com", "client@partner.com"],
        jurisdiction_policy="ALL_PARTY",
        all_parties_consented=True,
        tenant_id="tenant_acme",
        entity_tags="PO-4421",
    )
    assert ingest_res["success"] is True
    assert len(ingest_res["consent_proof_hash"]) == 64
    assert len(ingest_res["facts_recorded"]) >= 1
    assert len(ingest_res["commitments_recorded"]) >= 1

    # 3. Query hybrid context via MCP tool
    query_res = await mcp_tools.mail_query_hybrid_context(
        query="PO-4421 $55,000",
        tenant_id="tenant_acme",
        entities=["PO-4421"],
        limit=5,
    )
    assert query_res["success"] is True
    active_facts = query_res["entity_facts"]
    amt_facts = [f for f in active_facts if f["predicate"] == "AMOUNT"]
    assert len(amt_facts) == 1
    assert amt_facts[0]["object_value"] == "$55,000"
    assert amt_facts[0]["source_channel"] == "MEETING_TRANSCRIPT"
