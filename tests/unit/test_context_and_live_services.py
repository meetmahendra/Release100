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

"""Targeted Unit Tests for Context Services, PM Adapters, Vision OCR, and Live Connectors."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pytest
from starlette.testclient import TestClient

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.services.history_context_service import (
    build_non_chained_topic_history,
    build_thread_history,
    clean_email_body_for_history,
    format_history_for_prompt,
)
from apps.mail_organizer.services.org_context_service import (
    build_org_context_block,
    reload_org_context,
    resolve_active_projects,
    resolve_sender_persona,
)
from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.connectors.calendar_connector import CalendarConnector
from apps.mail_organizer.pm.jira_adapter import JiraAdapter
from apps.mail_organizer.pm.linear_adapter import LinearAdapter
from apps.mail_organizer.pm.task_manager import PMTaskManager
from apps.temperature_marker.downstream.in_house_rest import InHouseRESTConnector
from core_platform.app.skills.display_ocr import DisplayOCRSkill
from core_platform.app.skills.image_enhancer import ImageEnhancerSkill
from core_platform.app.ingress.relay_client import CloudRelayClient
from core_platform.app.outbox.synchronizer import OutboxSynchronizer
from core_platform.main import app


@pytest.fixture
def mem_db(tmp_path: Path):
    db_file = tmp_path / "context_test.db"
    return MailDatabaseService(db_url=f"sqlite:///{db_file}")


def test_org_context_service_operations():
    reload_org_context()

    # Test unknown sender
    unknown = resolve_sender_persona("random_stranger@external.xyz")
    assert unknown is None or isinstance(unknown, dict)

    # Test internal employee resolution
    emp = resolve_sender_persona("Victoria Sterling <victoria.sterling@yourcompany.com>")
    if emp:
        assert emp["type"] == "internal_employee"
        assert emp["is_vip"] is True

    # Test employee with assigned projects
    emp_proj = resolve_sender_persona("Arjun Mehta <arjun.mehta@yourcompany.com>")
    if emp_proj:
        assert emp_proj.get("assigned_projects") is not None

    # Test external strategic client resolution
    client = resolve_sender_persona("David Chen <david.chen@yourclient.com>")
    if client:
        assert client["type"] == "strategic_client"
        assert client["is_vip"] is True

    # Test project resolution
    projs = resolve_active_projects("Urgent review for Project Titan and database scaling")
    assert isinstance(projs, list)

    # Test prompt block formatting for employee
    block_emp = build_org_context_block(
        sender_raw="Victoria Sterling <victoria.sterling@yourcompany.com>",
        subject="Board Review",
        body="Executive agenda item.",
    )
    assert "ORGANIZATIONAL CONTEXT" in block_emp

    # Test prompt block formatting for employee with projects
    block_proj = build_org_context_block(
        sender_raw="Arjun Mehta <arjun.mehta@yourcompany.com>",
        subject="Payments Gateway API",
        body="Discussing PROJECT_APOLLO integration.",
    )
    assert "ORGANIZATIONAL CONTEXT" in block_proj

    # Test prompt block formatting for client
    block_client = build_org_context_block(
        sender_raw="David Chen <david.chen@yourclient.com>",
        subject="Contract SLA Renewal",
        body="Discussing Platinum SLA.",
    )
    assert "ORGANIZATIONAL CONTEXT" in block_client

    # Test prompt block formatting for unknown sender with detected projects
    block_unknown = build_org_context_block(
        sender_raw="contractor@vendor.io",
        subject="Project Titan deliverables",
        body="Delivering Project Titan milestone updates.",
    )
    assert "Unregistered Sender" in block_unknown


def test_history_context_service(mem_db):
    # Test body cleaning
    raw_body = "Hi team,\nHere is the report.\n\nOn Mon, Jan 1 wrote:\n> Old text"
    cleaned = clean_email_body_for_history(raw_body)
    assert "report" in cleaned
    assert "Old text" not in cleaned

    # Test thread history with None creds
    assert build_thread_history(None, "t-123") == []

    # Test thread history with mocked discovery module
    mock_discovery = MagicMock()
    mock_service = MagicMock()
    mock_discovery.build.return_value = mock_service
    mock_service.users().threads().get().execute.return_value = {
        "messages": [
            {
                "id": "m1",
                "snippet": "First turn snippet",
                "payload": {"headers": [{"name": "From", "value": "boss@corp.com"}, {"name": "Date", "value": "Today"}]},
            },
            {
                "id": "m2",
                "snippet": "Second turn snippet",
                "payload": {"headers": [{"name": "From", "value": "dev@corp.com"}, {"name": "Date", "value": "Today"}]},
            },
        ]
    }
    with patch.dict(sys.modules, {"googleapiclient": MagicMock(), "googleapiclient.discovery": mock_discovery}):
        turns = build_thread_history(creds=MagicMock(), thread_id="t-123", current_msg_id="m2")
        assert len(turns) == 1
        assert turns[0]["sender"] == "boss@corp.com"

    # Test non-chained topic history with database
    mem_db.store_email(
        gmail_id="hist_1",
        thread_id="t_hist_1",
        subject="Q3 Quarterly Review",
        sender="partner@vendor.com",
        body="Past proposal details.",
    )
    with patch("apps.mail_organizer.database.db_service.MailDatabaseService.get_instance", return_value=mem_db):
        records = build_non_chained_topic_history(sender="partner@vendor.com", subject="Q3 Review", limit=3)
        assert len(records) >= 1
        assert records[0]["subject"] == "Q3 Quarterly Review"

    # Test format_history_for_prompt
    formatted = format_history_for_prompt(
        thread_turns=[{"turn": 1, "sender": "partner@vendor.com", "date": "Yesterday", "snippet": "Hey"}],
        topic_memories=[{"date": "2026-09-01", "subject": "Prior talk", "category": "@Action", "urgency": 5, "reasoning": "Agreed"}],
    )
    assert "CONVERSATION & TOPIC HISTORY" in formatted
    assert "Prior talk" in formatted


@pytest.mark.asyncio
async def test_jira_adapter_execution():
    adapter = JiraAdapter(email="dev@company.com", api_token="secret_token_123")
    
    mock_resp = MagicMock()
    mock_resp.status = 201
    mock_resp.read.return_value = json.dumps({"key": "PROJ-101"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = await adapter.create_issue(
            summary="Fix OAuth token race",
            description="Needs lock",
            project_key="ENG",
            issue_type="Bug",
            priority="High",
        )
        assert res.get("success") is True
        assert res.get("issue_id") == "PROJ-101"


@pytest.mark.asyncio
async def test_linear_adapter_execution():
    adapter = LinearAdapter(api_key="lin_api_valid_mock_token_123")
    
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({
        "data": {"issueCreate": {"success": True, "issue": {"id": "lin-123", "identifier": "LIN-123", "url": "https://linear.app/issue/123"}}}
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = await adapter.create_issue(
            title="Implement HACCP sensor check",
            description="Details",
            priority=2,
        )
        assert res.get("success") is True
        assert res.get("issue_id") == "LIN-123"


def test_gmail_connector_live_methods():
    connector = GmailConnector(mock_mode=False)

    def fake_api_request(endpoint, method="GET", data=None):
        if endpoint == "labels" and method == "GET":
            return {"labels": [{"id": "Label_Existing", "name": "Urgent"}]}
        if endpoint == "labels" and method == "POST":
            return {"id": "Label_New", "name": data.get("name")}
        if "modify" in endpoint and method == "POST":
            return {"id": "msg-1", "labelIds": ["Label_Existing"]}
        if endpoint == "drafts" and method == "POST":
            return {"id": "draft-99"}
        return {}

    with patch.object(connector, "_api_request", side_effect=fake_api_request):
        # Existing label
        lid = connector._ensure_label_exists("Urgent")
        assert lid == "Label_Existing"

        # New label creation
        lid2 = connector._ensure_label_exists("VIP-Customer")
        assert lid2 == "Label_New"

        # Apply labels
        ok = connector._apply_labels_live("msg-1", ["Urgent"], ["UNREAD"])
        assert ok is True

        # Create draft live
        payload = {"draft_id": "d-1", "thread_id": "th-1", "recipient": "dest@domain.com", "subject": "Subject", "body": "Body", "status": "STAGED"}
        draft_res = connector._create_draft_live("th-1", "dest@domain.com", "Subject", "Body", "", payload)
        assert draft_res.get("draft_id") == "draft-99"


@pytest.mark.asyncio
async def test_calendar_connector_live_methods():
    connector = CalendarConnector(mock_mode=False)

    def fake_api(endpoint, method="GET", data=None):
        if "freeBusy" in endpoint:
            return {
                "calendars": {
                    "primary": {
                        "busy": [
                            {"start": "2026-09-17T10:00:00Z", "end": "2026-09-17T11:00:00Z"}
                        ]
                    }
                }
            }
        if "events" in endpoint:
            return {
                "items": [
                    {"id": "ev-1", "summary": "Product Review", "start": {"dateTime": "2026-09-17T14:00:00Z"}, "end": {"dateTime": "2026-09-17T15:00:00Z"}}
                ]
            }
        return {}

    with patch.object(connector, "_api_request", side_effect=fake_api):
        with patch.object(connector.auth_manager, "is_authenticated", return_value=True):
            events = await connector.get_upcoming_events(max_results=2)
            assert len(events) == 1
            assert events[0]["summary"] == "Product Review"

            proposal = await connector.synthesize_availability_proposal()
            assert "available" in proposal.lower() or "connect" in proposal.lower() or len(proposal) > 0


@pytest.mark.asyncio
async def test_display_ocr_skill_live_parsing():
    skill = DisplayOCRSkill()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({
        "candidates": [{
            "content": {
                "parts": [{"text": '{"value": 3.6, "confidence": 0.98, "display_type": "lcd_screen"}'}]
            }
        }]
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("core_platform.app.skills.display_ocr.settings.GEMINI_API_KEY", "test_key_123"):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = await skill.extract_display_reading(b"arbitrary_bytes_fallback", force_cloud=True)
            assert res.value == 3.6
            assert res.confidence == 0.98
            assert res.engine_used == "cloud_gemini_vision"


@pytest.mark.asyncio
async def test_in_house_rest_connector_dispatch():
    connector = InHouseRESTConnector(endpoint_url="https://api.internal.com/v1/telemetry", mock_mode=False)
    
    # Test HTTP 200 success
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client.__aenter__.return_value.post.return_value = mock_resp

    with patch("httpx.AsyncClient", return_value=mock_client):
        ok, msg = await connector.dispatch({"temp": 3.2})
        assert ok is True
        assert "200" in msg

    # Test HTTP 500 failure
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 500
    mock_client.__aenter__.return_value.post.return_value = mock_resp_fail

    with patch("httpx.AsyncClient", return_value=mock_client):
        ok, msg = await connector.dispatch({"temp": 3.2})
        assert ok is False
        assert "500" in msg

    # Test network exception
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.side_effect = Exception("Connection dropped")
        ok, msg = await connector.dispatch({"temp": 3.2})
        assert ok is False
        assert "Connection dropped" in msg


@pytest.mark.asyncio
async def test_image_enhancer_skill():
    skill = ImageEnhancerSkill()
    await skill.initialize()
    assert skill.is_available() is True

    img = np.full((50, 50, 3), 120, dtype=np.uint8)
    clahe_res = await skill.enhance_contrast_clahe(img)
    assert clahe_res is not None

    flipped, was_flipped = await skill.correct_selfie_mirror(img, force_flip=True)
    assert was_flipped is True

    glare_res = await skill.suppress_panel_glare(img)
    assert glare_res is not None

    status = skill.get_health_status()
    assert "clahe_clip_limit" in status


@pytest.mark.asyncio
async def test_pm_task_manager_edge_cases(mem_db):
    mgr = PMTaskManager(db_service=mem_db)
    assert mgr.reject_task("fake_id") is False
    res_jira = await mgr.approve_and_export("fake_id", destination="jira")
    assert res_jira["success"] is False
    res_linear = await mgr.approve_and_export("fake_id", destination="linear")
    assert res_linear["success"] is False


def test_pm_task_manager_sync_wrapper(mem_db):
    mgr = PMTaskManager(db_service=mem_db)
    # Not found
    assert mgr.approve_and_sync_task("not_found")["success"] is False

    # Staged and approved
    staged = mgr.stage_task(summary="Fix certs", destination="jira")
    res = mgr.approve_and_sync_task(staged.task_id, target="jira")
    assert res["success"] is True


def test_core_platform_health_and_redirects():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "healthy"

    resp_red = client.get("/", follow_redirects=False)
    assert resp_red.status_code in (302, 307)

    resp_loc = client.get("/loc")
    assert resp_loc.status_code == 200


@pytest.mark.asyncio
async def test_relay_client_lifecycle():
    client = CloudRelayClient(relay_url="wss://mock.relay.canectar.com/ws")
    client.start()
    assert client.is_running is True
    await client.stop()
    assert client.is_running is False


@pytest.mark.asyncio
async def test_main_outbox_sync_worker():
    sync = OutboxSynchronizer(drain_interval_seconds=0.01)
    synced, failed = await sync._drain_cycle()
    assert isinstance(synced, int)
    assert isinstance(failed, int)


@pytest.mark.asyncio
async def test_layer1_face_node_with_embedding(tmp_path: Path):
    from apps.temperature_marker.database.db_service import DatabaseService
    from apps.temperature_marker.graph.nodes.layer1_face_node import layer1_face_node
    from core_platform.app.skills.face_recognizer import FaceRecognizerSkill
    from core_platform.app.skills.registry import SkillRegistry

    db = DatabaseService(db_url=f"sqlite:///{tmp_path}/face_test.db")
    skill = FaceRecognizerSkill()
    SkillRegistry.get_instance().register_skill("face_recognizer", skill)

    # Register employee with encrypted embedding
    raw_vec = np.full((128,), 0.1, dtype=np.float32)
    enc_vec = skill.encrypt_embedding(raw_vec)
    db.register_employee("EMP-FACE-01", "Face Tester", "Store", enc_vec)

    state = {"operator_emp_code": "EMP-FACE-01", "raw_image_bytes": b"sample_face_bytes"}
    with patch.object(skill, "compute_embedding", return_value=(True, raw_vec, "OK")):
        res = await layer1_face_node(state, db_service=db)
        assert res["face_confidence"] >= 0.9


def test_knowledge_graph_service_fleet_queries() -> None:
    """Test KnowledgeGraphService real fleet lookup and topology queries against canebot_fleet_roster.json."""
    from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService

    kg = KnowledgeGraphService()

    # List all kiosks
    all_kiosks = kg.list_all_kiosks()
    assert len(all_kiosks) >= 3

    # Details for known kiosk
    kiosk_id = "CANEBOT-PUNE-04"
    details = kg.get_kiosk_details(kiosk_id)
    assert details is not None
    assert details["kiosk_id"] == kiosk_id
    assert "Phoenix Marketcity" in details["name"]

    # Coordinates
    coords = kg.get_kiosk_coordinates(kiosk_id)
    assert coords is not None
    lat, lon, rad = coords
    assert abs(lat - 18.56) < 0.1
    assert abs(lon - 73.91) < 0.1
    assert rad > 0

    # Kiosk by ID
    resolved = kg.get_kiosk_by_id(kiosk_id)
    assert resolved is not None
    assert resolved["site_id"] == "SITE-PUNE-PHOENIX"

    # HACCP limits
    haccp = kg.get_haccp_limits(kiosk_id)
    assert haccp.min_safe_temp <= haccp.max_safe_temp

    # Phone resolution
    profile = kg.get_kiosk_profile(kiosk_id)
    assert profile is not None
    if profile.primary_operator_phones:
        phone = profile.primary_operator_phones[0]
        matched = kg.resolve_kiosk_by_phone(phone)
        assert matched == kiosk_id

    # Nonexistent kiosk lookups
    assert kg.get_kiosk_profile("NONEXISTENT_999") is None
    assert kg.get_location_for_kiosk("NONEXISTENT_999") is None
    assert kg.get_kiosk_coordinates("NONEXISTENT_999") is None
    assert kg.get_kiosk_by_id("NONEXISTENT_999") is None
    assert kg.get_kiosk_details("NONEXISTENT_999") is None
    assert kg.resolve_kiosk_by_phone("+10000000000") is None

