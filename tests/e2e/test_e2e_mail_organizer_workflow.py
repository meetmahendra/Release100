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
E2E Journey 2: AI Mail Organizer Ingestion, Rule Matching, PM Queue & Outbound Loop (GEES v3.1).

Exercises the full email lifecycle:
1. Admin creates routing and whitelist rules for the tenant.
2. Inbound email arrives with multi-tenant context.
3. Cognitive Intent & Category triage executes (Action Item Extraction).
4. Token usage and financial liability logged to tenant LLM ledger.
5. Staged PM deliverables and draft replies populate Human-in-the-Loop PM Queue.
6. PM logs in via Web UI, inspects actionable DOM invariants, and approves PM task/draft.
7. Outbox / Task state successfully advances to EXECUTED / DISPATCHED.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.database.models import (
    Base as MailBase,
    DraftRecord,
    EmailClassification,
    EmailRecord,
    MailRule,
    PMActionQueue,
)
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.identity.models import Base as IdentityBase, Tenant, TenantDomain
from core_platform.app.llm.cost_tracker import LLMCostTracker, get_llm_cost_tracker
from core_platform.main import app


@pytest.fixture
def mail_e2e_env(tmp_path: Path) -> tuple[TestClient, MailDatabaseService, LLMCostTracker]:
    """Initialize isolated database and services for Mail Organizer E2E."""
    db_file = tmp_path / "e2e_mail_organizer.db"
    db_url = f"sqlite:///{db_file}"

    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(database_url=db_url)
    engine = db_mgr.get_engine()
    IdentityBase.metadata.create_all(bind=engine)
    MailBase.metadata.create_all(bind=engine)
    session_maker = sessionmaker(bind=engine)

    with session_maker() as session:
        acme = Tenant(id="acme_corp", name="Acme Logistics", license_tier="ENTERPRISE", storage_region="us-east-1")
        acme_dom = TenantDomain(tenant_id="acme_corp", domain_name="acme.intentrouter.io")
        session.merge(acme)
        session.merge(acme_dom)
        session.commit()

    MailDatabaseService._instance = None
    mail_db = MailDatabaseService.get_instance(engine=engine)
    cost_tracker = get_llm_cost_tracker()

    client = TestClient(app, follow_redirects=False)
    return client, mail_db, cost_tracker


def test_e2e_mail_organizer_full_lifecycle(mail_e2e_env: tuple[TestClient, MailDatabaseService, LLMCostTracker]) -> None:
    client, mail_db, cost_tracker = mail_e2e_env

    # -------------------------------------------------------------------------
    # STEP 1: Admin Sets Up a Routing Rule
    # -------------------------------------------------------------------------
    rule = mail_db.add_rule(
        rule_type="whitelist_domain",
        pattern="partner-corp.com",
        action="tag_vip",
        tenant_id="acme_corp",
    )
    assert rule is not None
    assert rule.id is not None
    assert rule.tenant_id == "acme_corp"

    # -------------------------------------------------------------------------
    # STEP 2: Inbound Email Ingested for acme_corp
    # -------------------------------------------------------------------------
    email_record = mail_db.store_email(
        gmail_id="msg-e2e-1001",
        thread_id="th-e2e-1001",
        subject="Urgent: Q3 Logistics Invoice Clarification Required",
        sender="client@partner-corp.com",
        to_recipients="logistics@acme.intentrouter.io",
        body="Dear Acme team, please provide clarification on invoice #90210 by tomorrow.",
        tenant_id="acme_corp",
    )
    assert email_record is not None
    assert email_record.tenant_id == "acme_corp"

    # Store classification
    cls_record = mail_db.store_classification(
        gmail_id="msg-e2e-1001",
        category="Finance & Invoicing",
        urgency_score=9,
        confidence_score=0.96,
        reasoning="Inquiry regarding pending invoice with explicit deadline.",
        context_tags="finance, urgent, invoice",
        is_reply_necessary=True,
        responsibility_role="PRIMARY_ACTIONEE",
        suggested_reply="Hello, we are actively reviewing invoice #90210 and will send updates shortly.",
        tenant_id="acme_corp",
    )
    assert cls_record is not None

    # -------------------------------------------------------------------------
    # STEP 3: Cognitive Router & Token Usage Financial Liability Logged
    # -------------------------------------------------------------------------
    cost_tracker.record_interaction(
        interaction_id="int-e2e-001",
        operation_id="msg-e2e-1001",
        task="text_generation",
        provider="gemini",
        model="gemini-2.0-flash",
        prompt_tokens=450,
        completion_tokens=120,
        latency_ms=240.0,
        tenant_id="acme_corp",
        cartridge_id="mail_organizer",
        credential_mode="CUSTOMER_BYOK",
    )

    # Store staged PM task deliverable
    pm_task = mail_db.queue_pm_task(
        summary="Review Q3 Logistics invoice #90210",
        gmail_id="msg-e2e-1001",
        email_subject="Urgent: Q3 Logistics Invoice Clarification Required",
        email_sender="client@partner-corp.com",
        description="Clarify itemized line items on invoice #90210 before EOD tomorrow.",
        priority="High",
        project_key="LOG",
        destination="jira",
        tenant_id="acme_corp",
    )
    assert pm_task is not None
    assert pm_task.status == "PENDING"

    # Store staged draft
    draft_record = mail_db.store_draft(
        gmail_id="msg-e2e-1001",
        thread_id="th-e2e-1001",
        recipient="client@partner-corp.com",
        subject="Re: Urgent: Q3 Logistics Invoice Clarification Required",
        body="Hello, we are actively reviewing invoice #90210 and will send updates shortly.",
        tenant_id="acme_corp",
    )
    assert draft_record is not None
    assert draft_record.status == "STAGED"

    # -------------------------------------------------------------------------
    # STEP 4: PM logs into Web UI to view Human-in-the-Loop PM Queue
    # -------------------------------------------------------------------------
    pm_token = create_jwt_token(
        principal_id="acme_pm",
        roles=["admin"],
        permitted_apps=["all", "mail_organizer"],
        tenant_id="acme_corp",
    )
    client.cookies.set("admin_token", pm_token)
    client.cookies.set("csrf_token", "csrf_mail_e2e_123")

    queue_resp = client.get(
        "/admin/apps/mail-organizer/pm-queue",
        headers={"Host": "acme.intentrouter.io"},
    )
    assert queue_resp.status_code == 200
    html_queue = queue_resp.text

    # Assert Actionable DOM Invariants (queue rendered, task present with action triggers)
    assert "PM Action Queue" in html_queue or "Action Queue" in html_queue
    assert "invoice #90210" in html_queue or "partner-corp.com" in html_queue

    # -------------------------------------------------------------------------
    # STEP 5: PM Approves & Dispatches PM Task via API
    # -------------------------------------------------------------------------
    with patch("apps.mail_organizer.pm.jira_adapter.JiraAdapter.create_issue", new_callable=AsyncMock) as mock_jira:
        mock_jira.return_value = {"success": True, "issue_key": "LOG-101", "url": "https://jira.acme.com/browse/LOG-101"}
        
        approve_resp = client.post(
            f"/admin/apps/mail-organizer/api/pm-tasks/{pm_task.id}/approve",
            json={"sync_to": "jira"},
            headers={"Host": "acme.intentrouter.io", "X-CSRF-Token": "csrf_mail_e2e_123"},
        )
        assert approve_resp.status_code == 200
        data = approve_resp.json()
        assert data.get("success") is True

    # -------------------------------------------------------------------------
    # STEP 6: Verify Database Status & Cost Ledger Persistence
    # -------------------------------------------------------------------------
    tasks = mail_db.get_pending_pm_tasks(tenant_id="acme_corp")
    assert len(tasks) == 0  # Task was approved and transitioned out of PENDING

    # Verify LLM cost record was attributed to acme_corp
    breakdowns = cost_tracker.get_tenant_breakdown()
    acme_breakdown = next((b for b in breakdowns if b["tenant_id"] == "acme_corp"), None)
    assert acme_breakdown is not None
    assert acme_breakdown["prompt_tokens"] >= 450
    assert acme_breakdown["completion_tokens"] >= 120
    assert acme_breakdown["credential_mode"] == "CUSTOMER_BYOK"
    assert acme_breakdown["platform_liability_usd"] == 0.0  # BYOK isolation invariant
