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
Layer 2 Deterministic Post-Execution Safety Gate (`guardrail_node`).

Adheres strictly to GEES v1.0 (Layer 2) and Plan 04 v1.0.
Enforces the mandatory 85% confidence threshold:
Any classification or intent extraction with confidence < 0.85 is automatically
diverted to the human review gate with label `_LLM/NeedsReview`.
"""

import time
from typing import Any, Dict
from apps.mail_organizer.graph.state import MailOrganizerState


async def guardrail_node(
    state: MailOrganizerState,
    confidence_threshold: float = 0.85,
) -> MailOrganizerState:
    """Evaluate confidence threshold and divert sub-threshold classifications."""
    t0 = time.perf_counter()

    conf = float(state.get("confidence_score") or 1.0)
    gmail_actions = list(state.get("gmail_actions") or [])

    if conf < confidence_threshold:
        state["safety_override"] = True
        state["override_reason"] = (
            f"Confidence {conf:.2f} is below mandatory threshold {confidence_threshold:.2f}; diverted to human review."
        )
        # Apply safety review label
        gmail_actions.append({"action": "apply_label", "label": "_LLM/NeedsReview"})
        state["gmail_actions"] = gmail_actions
    else:
        state["safety_override"] = False
        state["override_reason"] = None

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "guardrail",
        "duration_ms": duration_ms,
        "confidence": conf,
        "safety_override": state["safety_override"],
        "override_reason": state.get("override_reason"),
    })
    state["pipeline_trace"] = trace

    return state
