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

"""GEES v1.0 Deep Coverage Tests for Temperature Marker Graph Nodes."""

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
from PIL import Image
import pytest

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.nodes.haccp_node import haccp_node
from apps.temperature_marker.graph.nodes.layer1_face_node import (
    layer1_face_node,
    _enqueue_mismatch_incident,
)
from apps.temperature_marker.graph.nodes.layer1_ocr_node import layer1_ocr_node
from apps.temperature_marker.graph.nodes.layer2_confidence_node import layer2_confidence_node
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.skills.registry import SkillRegistry, get_platform_skill
from core_platform.app.skills.display_ocr import DisplayOCRSkill
from core_platform.app.skills.face_recognizer import FaceRecognizerSkill


@pytest.fixture
def db_service(tmp_path: Path) -> DatabaseService:
    """Create isolated SQLite database service instance."""
    db_file = tmp_path / "test_nodes_marker.db"
    return DatabaseService(db_url=f"sqlite:///{db_file}")


# ============================================================================
# 1. HACCP Node Tests
# ============================================================================

@pytest.mark.asyncio
async def test_haccp_node_branches() -> None:
    """Test safe, acceptable, hazard, freezing, and missing temp branches."""
    kg_service = KnowledgeGraphService()

    # 1. Safe range (e.g. 3.0°C)
    s1 = {"kiosk_id": "NODE-PUNE-04", "chiller_temp_c": 3.0}
    r1 = await haccp_node(s1, kg_service)  # type: ignore[arg-type]
    assert r1["haccp_status"] == "SAFE_RANGE"
    assert r1["haccp_compliant"] is True

    # 2. Critical hazard (e.g. 15.0°C)
    s2 = {"kiosk_id": "NODE-PUNE-04", "chiller_temp_c": 15.0}
    r2 = await haccp_node(s2, kg_service)  # type: ignore[arg-type]
    assert r2["haccp_status"] == "CRITICAL_HAZARD"
    assert r2["haccp_compliant"] is False

    # 3. Freezing hazard (e.g. -1.5°C)
    s3 = {"kiosk_id": "NODE-PUNE-04", "chiller_temp_c": -1.5}
    r3 = await haccp_node(s3, kg_service)  # type: ignore[arg-type]
    assert r3["haccp_status"] == "FREEZING_HAZARD"
    assert r3["haccp_compliant"] is False

    # 4. Acceptable range (e.g. 5.5°C)
    s4 = {"kiosk_id": "NODE-PUNE-04", "chiller_temp_c": 5.5}
    r4 = await haccp_node(s4, kg_service)  # type: ignore[arg-type]
    assert r4["haccp_status"] == "ACCEPTABLE_RANGE"
    assert r4["haccp_compliant"] is True

    # 5. Missing temperature reading
    s5 = {"kiosk_id": "NODE-PUNE-04", "chiller_temp_c": None, "is_duty_checkin": False}
    r5 = await haccp_node(s5, kg_service)  # type: ignore[arg-type]
    assert r5["haccp_compliant"] is False


# ============================================================================
# 2. Layer 2 Confidence Node Tests
# ============================================================================

@pytest.mark.asyncio
async def test_layer2_confidence_node_branches() -> None:
    """Test confidence gating for face match and OCR readings."""
    # 1. Prior disposition already diverted
    s1 = {"layer_2_disposition": "diverted_to_review"}
    r1 = await layer2_confidence_node(s1)  # type: ignore[arg-type]
    assert r1["layer_2_disposition"] == "diverted_to_review"

    # 2. Face confidence low (< 0.82)
    s2 = {"face_confidence": 0.50, "chiller_temp_c": 3.5, "ocr_confidence": 0.95}
    r2 = await layer2_confidence_node(s2)  # type: ignore[arg-type]
    assert r2["layer_2_disposition"] == "diverted_to_review"
    assert "Biometric Face Match Low" in r2["reply_message"]

    # 3. OCR confidence low (< 0.85)
    s3 = {"face_confidence": 0.95, "chiller_temp_c": 3.5, "ocr_confidence": 0.60}
    r3 = await layer2_confidence_node(s3)  # type: ignore[arg-type]
    assert r3["layer_2_disposition"] == "diverted_to_review"
    assert "Temperature Display Reading Low" in r3["reply_message"]

    # 4. All passing
    s4 = {"face_confidence": 0.95, "chiller_temp_c": 3.5, "ocr_confidence": 0.95}
    r4 = await layer2_confidence_node(s4)  # type: ignore[arg-type]
    assert r4["layer_2_disposition"] == "approved_autonomous"


# ============================================================================
# 3. Layer 1 Face Node & Incident Enqueue Tests
# ============================================================================

@pytest.mark.asyncio
async def test_layer1_face_node_and_mismatch(db_service: DatabaseService) -> None:
    """Test layer1_face_node execution and supervisor incident alert queuing."""
    SkillRegistry.get_instance().register_skill("face_recognizer", FaceRecognizerSkill())
    SkillRegistry.get_instance().register_skill("display_ocr", DisplayOCRSkill())

    # Register employee with dummy embedding
    emp = db_service.register_employee(
        emp_code="EMP-1042",
        full_name="Rajesh Pawar",
        phone_number="+919800011122",
        assigned_kiosk_id="NODE-PUNE-04",
        status="ACTIVE",
    )

    # 1. Enqueue mismatch incident directly
    state = {
        "correlation_id": "test-corr-1",
        "kiosk_id": "NODE-PUNE-04",
        "sender_phone": "+919800011122",
    }
    _enqueue_mismatch_incident(state, db_service, emp, similarity=0.45)  # type: ignore[arg-type]
    msgs = db_service.get_recent_internal_messages(limit=10)
    assert len(msgs) == 1
    assert "Biometric Mismatch" in msgs[0].message_text

    # 2. Simulated reading with high confidence
    state_sim = {
        "operator_emp_code": "EMP-1042",
        "face_confidence": 0.92,
        "is_duty_checkin": True,
    }
    res_face = await layer1_face_node(state_sim, db_service)  # type: ignore[arg-type]
    assert res_face["face_confidence"] == 0.92
