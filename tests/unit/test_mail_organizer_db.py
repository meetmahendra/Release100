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

"""Unit tests for MailDatabaseService and SQLAlchemy 2.0 models."""

import pytest
from apps.mail_organizer.database.db_service import MailDatabaseService


@pytest.fixture
def db_service(tmp_path):
    db_file = tmp_path / "test_mail.db"
    return MailDatabaseService(db_url=f"sqlite:///{db_file}")


def test_store_and_retrieve_email(db_service):
    email = db_service.store_email(
        gmail_id="test_msg_001",
        thread_id="thread_001",
        subject="Sprint Review Meeting",
        sender="lead@company.com",
        to_recipients="team@company.com",
        snippet="Discussing sprint deliverables",
        body="Full body text of sprint review",
        labels_applied="INBOX",
    )
    assert email.id is not None
    assert email.gmail_id == "test_msg_001"

    recent = db_service.get_recent_emails(limit=10)
    assert len(recent) == 1
    assert recent[0]["gmail_id"] == "test_msg_001"
    assert recent[0]["subject"] == "Sprint Review Meeting"


def test_get_recent_emails_multiple(db_service):
    """Verify get_recent_emails returns all stored records, not just the last one."""
    for i in range(15):
        db_service.store_email(
            gmail_id=f"test_msg_{i:03d}",
            thread_id=f"thread_{i:03d}",
            subject=f"Email Subject {i}",
            sender=f"sender_{i}@company.com",
            body=f"Body content {i}",
        )
    recent = db_service.get_recent_emails(limit=50)
    assert len(recent) == 15
    assert recent[0]["gmail_id"] == "test_msg_014"  # Most recent first
    assert recent[-1]["gmail_id"] == "test_msg_000"


def test_store_classification_and_metrics(db_service):
    db_service.store_email(
        gmail_id="test_msg_002",
        thread_id="thread_002",
        subject="Action item follow-up",
        sender="pm@company.com",
    )
    cls = db_service.store_classification(
        gmail_id="test_msg_002",
        category="@Action",
        urgency_score=8,
        confidence_score=0.95,
        reasoning="Direct action requested",
        is_reply_necessary=True,
    )
    assert cls.id is not None
    assert cls.category == "@Action"

    metrics = db_service.get_dashboard_metrics()
    assert metrics["total_processed"] == 1
    assert metrics["category_breakdown"]["@Action"] == 1


def test_pm_action_queue_lifecycle(db_service):
    task = db_service.queue_pm_task(
        summary="Configure Redis Sentinel cluster",
        description="High availability caching",
        priority="High",
        destination="jira",
        project_key="OPS",
    )
    assert task.id is not None
    assert task.status == "PENDING"

    pending = db_service.get_pending_pm_tasks()
    assert len(pending) == 1
    assert pending[0].summary == "Configure Redis Sentinel cluster"

    updated = db_service.update_pm_task_status(task.task_id, status="APPROVED")
    assert updated.status == "APPROVED"
    assert len(db_service.get_pending_pm_tasks()) == 0


def test_reject_pm_task(db_service):
    task = db_service.queue_pm_task(
        summary="Dismissable task",
        destination="linear",
    )
    ok = db_service.reject_pm_task(task.id)
    assert ok is True
    assert len(db_service.get_pending_pm_tasks()) == 0


def test_rules_crud(db_service):
    rule = db_service.add_rule(
        rule_type="vip",
        pattern="ceo@customer.com",
        action="tag_vip",
    )
    assert rule.id is not None
    assert rule.is_active is True

    rules = db_service.get_all_rules()
    assert len(rules) == 1
    assert rules[0].pattern == "ceo@customer.com"


def test_store_and_get_drafts(db_service):
    draft = db_service.store_draft(
        gmail_id="msg_003",
        thread_id="th_003",
        recipient="client@enterprise.com",
        subject="Re: SLA Terms",
        body="Thank you. We confirm the updated SLA terms.",
    )
    assert draft.id is not None
    assert draft.status == "STAGED"

    drafts = db_service.get_all_drafts()
    assert len(drafts) == 1
    assert drafts[0].recipient == "client@enterprise.com"
