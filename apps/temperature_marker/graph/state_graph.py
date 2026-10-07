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
State Graph Assembly for Temperature & Attendance Marker.

Adheres strictly to Plan 03 v1.3 and GEES v1.0.
Connects discrete nodes with conditional routing edges:
  AuthGuard -> Location -> FaceMatch -> OCR -> Sanity -> ConfidenceGate -> HACCP -> Audit -> Outbox -> Reply
"""

from typing import Any, Callable, Dict

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.graph.nodes.audit_node import audit_node
from apps.temperature_marker.graph.nodes.haccp_node import haccp_node
from apps.temperature_marker.graph.nodes.ingest_node import ingest_node
from apps.temperature_marker.graph.nodes.layer0_auth_guard import layer0_auth_guard_node
from apps.temperature_marker.graph.nodes.layer0_location_node import layer0_location_node
from apps.temperature_marker.graph.nodes.layer0_sanity_node import layer0_sanity_node
from apps.temperature_marker.graph.nodes.layer1_face_node import layer1_face_node
from apps.temperature_marker.graph.nodes.layer1_ocr_node import layer1_ocr_node
from apps.temperature_marker.graph.nodes.layer2_confidence_node import layer2_confidence_node
from apps.temperature_marker.graph.nodes.outbox_node import outbox_node
from apps.temperature_marker.graph.nodes.reply_node import reply_node
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.telemetry.audit_engine import AuditEngine


class TemperatureMarkerWorkflow:
    """Executes the deterministic state-driven workflow for KioskNode attendance & chiller checks."""

    def __init__(
        self,
        db_service: DatabaseService,
        kg_service: KnowledgeGraphService,
        audit_engine: AuditEngine,
    ) -> None:
        """Initialize workflow with dependencies."""
        self.db_service = db_service
        self.kg_service = kg_service
        self.audit_engine = audit_engine

    async def execute(self, initial_state: TemperatureMarkerState) -> TemperatureMarkerState:
        """Run the complete multi-stage pipeline with fail-safe conditional gates.

        Args:
            initial_state: Inbound interaction state.

        Returns:
            Final processed TemperatureMarkerState.
        """
        state = initial_state

        # Step 0: Ingest & Image Pre-Processing (CLAHE + mirror correction + glare suppression)
        state = await ingest_node(state)

        # Step 1: Layer 0 Auth Guard
        state = await layer0_auth_guard_node(state, self.db_service)
        if not state.get("layer_0_passed", False):
            return await reply_node(state)

        # Step 2: Layer 0 Geofence & Location Verification
        state = await layer0_location_node(state, self.kg_service, self.db_service)
        if not state.get("geofence_verified", False):
            return await reply_node(state)

        # Step 3: Layer 1 Biometric Face Match
        state = await layer1_face_node(state, self.db_service)
        if not state.get("layer_0_passed", True) or state.get("layer_2_disposition") == "diverted_to_review":
            state = await audit_node(state, self.audit_engine)
            return await reply_node(state)
        if state.get("reply_message") and state.get("chiller_temp_c") is None:
            return await reply_node(state)

        # Step 4: Layer 1 Dual-Engine Display OCR
        state = await layer1_ocr_node(state)

        # Step 5: Layer 0 Physical Temperature Sanity
        state = await layer0_sanity_node(state)
        if not state.get("layer_0_passed", True):
            state = await audit_node(state, self.audit_engine)
            return await reply_node(state)

        # Step 6: Layer 2 Post-Execution Confidence Gate (Biometrics & OCR Quality)
        state = await layer2_confidence_node(state)
        if state.get("layer_2_disposition") == "diverted_to_review":
            state = await audit_node(state, self.audit_engine)
            return await reply_node(state)

        # Step 7: HACCP Chiller Temperature Evaluation
        state = await haccp_node(state, self.kg_service)

        # Step 8: Cryptographic SHA-256 Audit Record
        state = await audit_node(state, self.audit_engine)

        # Step 9: Edge Outbox Persistence
        state = await outbox_node(state, self.db_service)

        # Step 10: Compose Outbound WhatsApp Notification
        state = await reply_node(state)

        return state
