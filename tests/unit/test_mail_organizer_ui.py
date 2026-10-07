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

"""Unit tests for Mail Organizer FastAPI Admin UI routes and simulator."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.main import app


@pytest.fixture
def client():
    c = TestClient(app)
    token = create_jwt_token("admin", ["admin"], ["all", "mail_organizer"])
    c.cookies.set("admin_token", token)
    return c


def test_mail_organizer_unauthenticated_access():
    """Unauthenticated requests to mail organizer admin endpoints must be rejected."""
    unauth = TestClient(app, follow_redirects=False)
    res = unauth.get("/admin/apps/mail-organizer/dashboard", headers={"Accept": "text/html"})
    assert res.status_code == 302
    assert res.headers["location"] == "/admin/login"


def test_dashboard_endpoint(client):
    res = client.get("/admin/apps/mail-organizer/dashboard")
    assert res.status_code == 200
    assert "AI Mail & Calendar Organizer" in res.text
    assert "Total Emails Triaged" in res.text


def test_triage_page(client):
    res = client.get("/admin/apps/mail-organizer/triage")
    assert res.status_code == 200
    assert "Triage Simulator" in res.text
    assert "Run Complete LangGraph Pipeline" in res.text


def test_pm_queue_page(client):
    res = client.get("/admin/apps/mail-organizer/pm-queue")
    assert res.status_code == 200
    assert "Human-in-the-Loop PM Action Queue" in res.text


def test_rules_page(client):
    res = client.get("/admin/apps/mail-organizer/rules")
    assert res.status_code == 200
    assert "Deterministic VIP & Whitelist Rules" in res.text


def test_drafts_page(client):
    res = client.get("/admin/apps/mail-organizer/drafts")
    assert res.status_code == 200
    assert "Contextual Staged Drafts" in res.text


def test_simulate_endpoint(client):
    payload = {
        "sender": "investor@venture-capital.com",
        "recipients": ["user@company.com"],
        "subject": "Follow up on seed round terms",
        "body": "Please review the updated term sheet and let us know your thoughts.",
    }
    res = client.post("/admin/apps/mail-organizer/api/simulate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "category" in data
    assert "confidence" in data


def test_accounts_page(client):
    """GET /accounts must render Google account OAuth status page."""
    res = client.get("/admin/apps/mail-organizer/accounts")
    assert res.status_code == 200
    assert "Google Account" in res.text
    assert "Connection Status" in res.text


def test_accounts_reauth(client):
    """GET /accounts/reauth must initiate OAuth flow or redirect."""
    res = client.get("/admin/apps/mail-organizer/accounts/reauth", follow_redirects=False)
    assert res.status_code in (302, 307)


def test_pm_task_reject_nonexistent(client):
    """POST /api/pm-tasks/99999/reject must return 404 for nonexistent task."""
    res = client.post("/admin/apps/mail-organizer/api/pm-tasks/99999/reject")
    assert res.status_code == 404


def test_mail_database_service_crud(tmp_path: Any) -> None:
    """Test real MailDatabaseService operations with local SQLite."""
    from pathlib import Path
    from apps.mail_organizer.database.db_service import MailDatabaseService

    db_path = Path(tmp_path) / "real_mail_test.db"
    db = MailDatabaseService(db_url=f"sqlite:///{db_path}")

    # Metrics on empty db
    metrics = db.get_dashboard_metrics()
    assert isinstance(metrics, dict)

    # Add a deterministic rule
    db.add_rule(
        rule_type="WHITELIST",
        pattern="*@example.com",
        action="INBOX",
    )
    rules = db.get_all_rules()
    assert len(rules) >= 1
    assert any(r.pattern == "*@example.com" for r in rules)

    # Queue PM task
    task = db.queue_pm_task(
        summary="Test Review Proposal",
        gmail_id="msg_real_001",
        description="Detailed review needed",
        priority="High",
    )
    assert task.task_id is not None

    # Get pending tasks
    pending = db.get_pending_pm_tasks()
    assert len(pending) >= 1

    # Reject PM task
    ok_rej = db.reject_pm_task(task.id)
    assert ok_rej is True

    # Queue and approve PM task
    task2 = db.queue_pm_task(
        summary="Second Task",
        gmail_id="msg_real_002",
        description="For approval test",
    )
    ok_appr = db.approve_pm_task(task2.id)
    assert ok_appr is True

    # Save draft
    db.store_draft(
        gmail_id="msg_real_003",
        thread_id="thread_real_003",
        recipient="client@example.com",
        subject="Re: Test Offer",
        body="Thank you for your proposal.",
    )
    drafts = db.get_all_drafts()
    assert len(drafts) >= 1


