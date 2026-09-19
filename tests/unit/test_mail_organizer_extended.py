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

"""Extended unit tests to reach >= 80% branch & line code coverage."""

import pytest
from apps.mail_organizer.connectors.auth_manager import GoogleAuthManager
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.nodes.calendar_node import calendar_node
from apps.mail_organizer.graph.nodes.draft_node import draft_node
from apps.mail_organizer.graph.nodes.execution_node import execution_node
from apps.mail_organizer.graph.nodes.pm_extract_node import pm_extract_node
from apps.mail_organizer.graph.state import MailOrganizerState
from apps.mail_organizer.mcp.tools import MailOrganizerMCPTools, get_mail_organizer_mcp_tools
from apps.mail_organizer.plugin import MailOrganizerApplication
from apps.mail_organizer.pm.task_manager import PMTaskManager


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "extended_test.db"
    return MailDatabaseService(db_url=f"sqlite:///{db_file}")


def test_auth_manager_encryption_and_tokens(tmp_path):
    token_path = tmp_path / "token.enc"
    auth = GoogleAuthManager(token_storage_path=str(token_path))
    assert auth.is_authenticated() is False

    auth.encrypt_and_save_token({"access_token": "mock_at", "refresh_token": "mock_rt"})
    assert token_path.exists()
    assert auth.is_authenticated() is True

    loaded = auth.load_and_decrypt_token()
    assert loaded is not None
    assert loaded["access_token"] == "mock_at"


@pytest.mark.asyncio
async def test_calendar_node():
    state: MailOrganizerState = {
        "gmail_id": "msg_c1",
        "category": "@Meeting",
        "is_scheduling_request": True,
        "subject": "Quick coffee sync tomorrow",
    }
    res = await calendar_node(state)
    assert res["calendar_availability"] is not None
    assert "availability" in res["calendar_availability"].lower() or "available" in res["calendar_availability"].lower()


@pytest.mark.asyncio
async def test_draft_node():
    state: MailOrganizerState = {
        "gmail_id": "msg_d1",
        "sender": "partner@vendor.com",
        "subject": "Proposal pricing update",
        "category": "@Action",
        "is_reply_necessary": True,
        "responsibility_role": "PRIMARY_ACTIONEE",
    }
    res = await draft_node(state)
    assert res["suggested_reply"] is not None
    assert len(res["suggested_reply"]) > 10


@pytest.mark.asyncio
async def test_pm_extract_node():
    state: MailOrganizerState = {
        "gmail_id": "msg_pm1",
        "sender": "architect@internal.io",
        "subject": "Action Required: Please update the database schema",
        "body": "Kindly review and deploy the new migration before Friday.",
        "category": "@Action",
        "pending_pm_tasks": [],
    }
    res = await pm_extract_node(state)
    assert len(res.get("pending_pm_tasks") or []) >= 1


@pytest.mark.asyncio
async def test_execution_node_assistive(test_db):
    state: MailOrganizerState = {
        "gmail_id": "msg_ex1",
        "thread_id": "th_ex1",
        "sender": "ceo@customer.com",
        "subject": "Contract terms",
        "body": "Please review terms",
        "category": "@Action",
        "urgency_score": 8,
        "confidence_score": 0.95,
        "execution_mode": "assistive",
        "suggested_reply": "Thank you, terms confirmed.",
        "pending_pm_tasks": [
            {
                "summary": "Execute SLA contract",
                "priority": "High",
                "destination": "jira",
            }
        ],
        "gmail_actions": [{"action": "apply_label", "label": "@Action"}],
    }
    res = await execution_node(state, db_service=test_db)
    assert len(res.get("actions_taken") or []) >= 1
    assert res.get("audit_record_hash") is not None


@pytest.mark.asyncio
async def test_pm_task_manager_lifecycle(test_db):
    mgr = PMTaskManager(db_service=test_db)
    staged = mgr.stage_task(
        summary="Set up TLS certificates",
        destination="jira",
        priority="High",
    )
    assert staged.task_id is not None
    pending = mgr.get_pending_tasks()
    assert len(pending) == 1

    appr = await mgr.approve_and_export(staged.task_id, destination="jira")
    assert appr["success"] is True

    staged2 = mgr.stage_task(
        summary="Set up Linear issue",
        destination="linear",
    )
    appr2 = await mgr.approve_and_export(staged2.task_id, destination="linear")
    assert appr2["success"] is True

    staged3 = mgr.stage_task(
        summary="Internal queue item",
        destination="sqlite_queue",
    )
    appr3 = await mgr.approve_and_export(staged3.task_id, destination="sqlite_queue")
    assert appr3["success"] is True

    staged4 = mgr.stage_task(summary="Task to reject")
    assert mgr.reject_task(staged4.task_id) is True


@pytest.mark.asyncio
async def test_mcp_tools():
    tools = MailOrganizerMCPTools()
    search_res = await tools.mail_search_threads("urgent contract")
    assert isinstance(search_res, list)

    th_res = await tools.mail_get_thread_context("mock_thread_1")
    assert "found" in th_res

    draft_res = await tools.mail_stage_draft_reply("mock_thread_1", "client@corp.com", "Confirmed attendance.")
    assert draft_res["success"] is True

    cal_res = await tools.mail_check_calendar_availability("2026-09-17")
    assert cal_res["success"] is True

    tasks_res = await tools.mail_get_pending_pm_tasks()
    assert isinstance(tasks_res, list)

    appr_tool = await tools.mail_approve_pm_task("NON_EXISTENT_TASK", destination="jira")
    assert appr_tool["success"] is False

    manifests = get_mail_organizer_mcp_tools()
    assert len(manifests) == 6


def test_plugin_manifest():
    plugin = MailOrganizerApplication()
    assert plugin.app_id == "mail_organizer"
    assert plugin.name == "AI Email & Calendar Organizer"
    assert plugin.version == "1.0.0"
    wf = plugin.get_workflow()
    assert wf is not None
    tools = plugin.get_mcp_tools()
    assert len(tools) == 6
