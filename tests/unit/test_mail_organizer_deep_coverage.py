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

"""GEES v1.0 Deep Coverage Tests for Mail Organizer Poller, Services, and Extraction."""

import json
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from apps.mail_organizer.services.poller_manager import MailPollerManager
from apps.mail_organizer.graph.nodes.pm_extract_node import pm_extract_node
from apps.mail_organizer.services.org_context_service import (
    resolve_sender_persona,
    is_org_vip,
    build_org_context_for_prompt,
    resolve_active_projects,
)


# ============================================================================
# 1. Poller Manager Lifecycle Tests
# ============================================================================

def test_poller_manager_lifecycle() -> None:
    """Test start, status, and stop operations on MailPollerManager."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = MailPollerManager(root_dir=Path(tmp_dir))
        assert manager.is_running() is False

        # Status inspection
        status = manager.get_status()
        assert status["is_running"] is False
        assert status["status"] == "STOPPED"

        # Start manager in test (mocking thread)
        with patch("threading.Thread.start") as mock_start:
            started = manager.start(poll_interval_seconds=60)
            assert started is True

        # Stop manager
        stopped = manager.stop(timeout=1.0)
        assert stopped is True


# ============================================================================
# 2. PM Extraction Node Tests
# ============================================================================

@pytest.mark.asyncio
async def test_pm_extract_node_with_gateway_mock() -> None:
    """Test task extraction node with mocked LLM gateway response."""
    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(return_value={
        "tasks": [
            {
                "summary": "Fix temperature sensor at Pune",
                "description": "Replace thermocouple in kiosk NODE-PUNE-04",
                "priority": "High",
                "due_date": "Today",
                "assignee": "Field Tech Lead",
            }
        ]
    })

    state = {
        "gmail_id": "msg_pm_123",
        "sender": "ops@apex.com",
        "subject": "Urgent Chiller Sensor Maintenance",
        "body": "Please replace thermocouple in kiosk NODE-PUNE-04 immediately.",
        "category": "MAINTENANCE",
    }

    with patch("core_platform.app.llm.gateway.get_platform_llm_gateway", return_value=mock_gateway):
        result = await pm_extract_node(state)  # type: ignore[arg-type]
        assert "pending_pm_tasks" in result
        assert len(result["pending_pm_tasks"]) == 1
        assert result["pending_pm_tasks"][0]["summary"] == "Fix temperature sensor at Pune"


@pytest.mark.asyncio
async def test_pm_extract_node_fallback_regex() -> None:
    """Test heuristic regex fallback when gateway raises exception."""
    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(side_effect=RuntimeError("Gateway offline"))

    state = {
        "gmail_id": "msg_pm_456",
        "sender": "lead@apex.com",
        "subject": "Action Required: Complete monthly fleet audit",
        "body": "Action Required: Complete monthly fleet audit by tomorrow EOD.",
        "category": "OPERATIONS",
    }

    with patch("core_platform.app.llm.gateway.get_platform_llm_gateway", return_value=mock_gateway):
        result = await pm_extract_node(state)  # type: ignore[arg-type]
        assert "pending_pm_tasks" in result
        assert len(result["pending_pm_tasks"]) >= 1


# ============================================================================
# 3. Organization Context Service Tests
# ============================================================================

def test_org_context_service_operations() -> None:
    """Test organization context resolution, VIP lookup, and prompt block rendering."""
    # 1. Unregistered sender
    persona = resolve_sender_persona("random_stranger@example.com")
    assert persona is None

    # 2. VIP check for random
    is_vip = is_org_vip("random@external.org")
    assert isinstance(is_vip, bool)

    # 3. Resolve active projects from keyword text
    projs = resolve_active_projects("Discussion regarding Project Phoenix deployment")
    assert isinstance(projs, list)

    # 4. Prompt context block builder
    prompt_block = build_org_context_for_prompt(
        sender_raw="ops@apex.com",
        subject="Chiller Calibration",
        body="Reviewing temperature logs.",
    )
    assert "ORGANIZATIONAL CONTEXT" in prompt_block
