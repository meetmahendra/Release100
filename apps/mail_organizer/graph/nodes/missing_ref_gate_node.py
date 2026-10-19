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
Tier 2 Stage B: Missing-Reference & Attachment Detector Gate (`missing_ref_gate_node`).

Adheres strictly to v1.3.0 Section 7.2 (Stage B) and REV-12.
Detects when an inbound email references an attachment, spreadsheet, or external call/document
that is absent from both the email payload and the Hybrid Neuro-Symbolic Context Bundle.
Places the thread in WAITING_FOR_USER_ARTIFACT instead of hallucinating a draft.
"""

import re
import time
from typing import Any, Optional

from apps.mail_organizer.graph.state import MailOrganizerState


# [CODE-MARKER: MO-TIER2-01] Stage B Missing-Reference & Attachment Detector Gate
async def missing_ref_gate_node(
    state: MailOrganizerState,
    db_service: Optional[Any] = None,
) -> MailOrganizerState:
    """Detect missing attachments or ungrounded external references before draft synthesis."""
    t0 = time.perf_counter()

    body = state.get("body") or ""
    subject = state.get("subject") or ""
    gmail_id = state.get("gmail_id") or ""
    thread_id = state.get("thread_id") or ""
    attachments = list(state.get("attachments_present") or [])
    bundle = state.get("hybrid_context_bundle") or {}

    has_retrieved_context = bool(
        bundle.get("entity_facts")
        or bundle.get("fts_matches")
        or bundle.get("semantic_matches")
    )

    body_lower = body.lower()
    missing_detected = False
    artifact_type: Optional[str] = None
    artifact_desc: Optional[str] = None

    # 1. Missing attachment reference (sender claims attachment/file is attached or asks for figures from an unattached file)
    attachment_patterns = [
        r"(?:see|review|approve|check|in)\s+(?:the\s+)?attached\s+([a-zA-Z0-9_\-\.\s]{3,40})",
        r"please\s+find\s+attached\s+([a-zA-Z0-9_\-\.\s]{3,40})",
        r"([\w\-]+\.(?:xlsx|pdf|docx|csv|pptx))\b",
    ]
    if not attachments:
        for pat in attachment_patterns:
            m = re.search(pat, body, re.IGNORECASE)
            if m and any(trigger in body_lower for trigger in ("attached", "spreadsheet", "deck", "model", "confirm the figure", "approve the number")):
                missing_detected = True
                artifact_type = "ATTACHMENT_MISSING"
                artifact_desc = f"Referenced artifact not found in email or context: {m.group(1).strip()[:120]}"
                break

    # 2. Ungrounded external call / verbal agreement reference with zero omnichannel context
    if not missing_detected and not has_retrieved_context:
        call_ref = re.search(
            r"(?:as\s+(?:we\s+)?(?:discussed|agreed)\s+on\s+(?:our|the|yesterday's)\s+(?:call|whatsapp|meeting)|per\s+our\s+verbal\s+agreement)([^\.\n]{0,80})",
            body,
            re.IGNORECASE,
        )
        if call_ref:
            missing_detected = True
            artifact_type = "EXTERNAL_CALL_OR_CHAT_CONTEXT"
            artifact_desc = f"Ungrounded verbal/call reference with no matching record: {call_ref.group(0).strip()[:120]}"

    state["missing_artifact_detected"] = missing_detected
    state["missing_artifact_type"] = artifact_type
    state["missing_artifact_description"] = artifact_desc

    if missing_detected:
        if db_service is not None and gmail_id:
            try:
                db_service.create_missing_artifact_request(
                    gmail_id=gmail_id,
                    artifact_type=artifact_type or "ATTACHMENT_MISSING",
                    artifact_description=artifact_desc or subject,
                    thread_id=thread_id,
                    tenant_id=state.get("tenant_id"),
                    user_id=state.get("user_id"),
                )
            except Exception:
                pass
        actions = list(state.get("gmail_actions") or [])
        if not any(a.get("label") == "_LLM/WaitingForArtifact" for a in actions):
            actions.append({"action": "apply_label", "label": "_LLM/WaitingForArtifact"})
        state["gmail_actions"] = actions

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "missing_ref_gate",
        "duration_ms": duration_ms,
        "missing_artifact_detected": missing_detected,
        "missing_artifact_type": artifact_type,
    })
    state["pipeline_trace"] = trace
    return state
