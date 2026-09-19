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

"""Unit tests for Mail Organizer connectors and PM adapters."""

import pytest
from apps.mail_organizer.connectors.calendar_connector import GoogleCalendarConnector
from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.pm.jira_adapter import JiraAdapter
from apps.mail_organizer.pm.linear_adapter import LinearAdapter


@pytest.mark.asyncio
async def test_gmail_connector_mock_workflow():
    connector = GmailConnector(mock_mode=True)
    connector.seed_mock_thread(
        gmail_id="msg_mock_01",
        thread_id="th_mock_01",
        subject="Sprint Review",
        sender="lead@company.com",
        body="Reviewing deliverables tomorrow",
    )
    messages = await connector.fetch_unread_threads(max_results=5)
    assert len(messages) >= 1
    msg_id = messages[0]["gmail_id"]

    # Test label modification without deletion
    mod_res = await connector.apply_labels(
        gmail_id=msg_id,
        add_labels=["_LLM/@Urgent"],
        remove_labels=["UNREAD"],
    )
    assert mod_res is True
    applied = connector.get_applied_labels(msg_id)
    assert "_LLM/@Urgent" in applied

    # Test staging draft
    draft_res = await connector.create_draft(
        thread_id="th_101",
        recipient="user@client.com",
        subject="Re: Update",
        body="Everything is on schedule.",
    )
    assert "draft_id" in draft_res
    assert draft_res["status"] == "STAGED"


@pytest.mark.asyncio
async def test_calendar_connector_mock_query():
    connector = GoogleCalendarConnector(mock_mode=True)
    busy_slots = await connector.get_free_busy()
    assert isinstance(busy_slots, list)
    assert len(busy_slots) >= 1

    proposal = await connector.synthesize_availability_proposal(preferred_date="2026-09-17")
    assert "2026-09-17" in proposal
    assert "available" in proposal.lower()


@pytest.mark.asyncio
async def test_jira_adapter_mock_create():
    adapter = JiraAdapter(mock_mode=True)
    res = await adapter.create_issue(
        summary="Implement database partition cleanup",
        description="Auto-purge stale audit files older than 90 days",
        project_key="CORE",
        priority="High",
    )
    assert res["success"] is True
    assert "issue_id" in res
    assert res["issue_id"].startswith("CORE-")


@pytest.mark.asyncio
async def test_linear_adapter_mock_create():
    adapter = LinearAdapter(mock_mode=True)
    res = await adapter.create_issue(
        title="Refactor OAuth token rotation",
        description="Ensure AES-256 encrypted refresh tokens rotate every 30 days",
    )
    assert res["success"] is True
    assert "issue_id" in res
