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
Layer 2: Deterministic Post-Execution Boundary & Quality Gate.

Adheres strictly to GEES v1.0 (Pillar 1) and Plan 02 v1.3.
Enforces:
1. Confidence threshold evaluation (Confidence < 85% diverted to Admin Review).
2. Zero-destructive command interception (prohibits autonomous deletions/drops).
3. Fail-safe defaults & Shadow/Dry-Run mode enforcement.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core_platform.app.config import settings
from core_platform.app.errors import PlatformErrorCode, SafetyGateViolation


class PostGateDisposition(str, Enum):
    """Result status of the Layer 2 post-execution boundary."""

    APPROVED_AUTONOMOUS = "approved_autonomous"  # Confidence >= 85% and autonomous mode enabled
    DIVERTED_TO_REVIEW = "diverted_to_review"  # Confidence < 85%, placed in Admin Queue
    SIMULATED_SHADOW = "simulated_shadow"  # Dry-run active, simulated in audit log only
    BLOCKED_DESTRUCTIVE = "blocked_destructive"  # Intercepted unauthorized destructive action


class Layer2PostExecutionGate:
    """Deterministic Post-Execution Safety Gate (Layer 2)."""

    DESTRUCTIVE_KEYWORDS: List[str] = [
        "delete",
        "drop",
        "truncate",
        "purge",
        "remove",
        "destroy",
        "format",
    ]

    @classmethod
    def evaluate_confidence(
        cls,
        confidence_score: float,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, PostGateDisposition, str]:
        """Evaluate whether a model confidence score meets autonomous execution standards.

        If confidence is below threshold (default: 85%), automatically diverts to human review.

        Args:
            confidence_score: Model-reported confidence between 0.0 and 1.0.
            threshold: Optional custom threshold, defaults to settings.CONFIDENCE_THRESHOLD (0.85).

        Returns:
            Tuple of (is_pass: bool, disposition: PostGateDisposition, reason: str).
        """
        effective_threshold = threshold if threshold is not None else settings.CONFIDENCE_THRESHOLD

        if confidence_score < effective_threshold:
            reason = (
                f"Confidence {confidence_score * 100:.1f}% is below required "
                f"threshold of {effective_threshold * 100:.1f}%. Diverted to Admin Approval Gate."
            )
            return False, PostGateDisposition.DIVERTED_TO_REVIEW, reason

        if settings.DRY_RUN or settings.EXECUTION_MODE == "shadow":
            reason = "Confidence verified, but operating in Shadow Mode (DRY_RUN=True). Mutation simulated."
            return True, PostGateDisposition.SIMULATED_SHADOW, reason

        return True, PostGateDisposition.APPROVED_AUTONOMOUS, "Confidence verified. Approved for autonomous commit."

    @classmethod
    def intercept_destructive_actions(cls, action_name: str, payload: Dict[str, Any]) -> bool:
        """Inspect proposed actions and block unauthorized destructive operations.

        Enforces the Zero-Deletion Policy mandated by GEES v1.0.

        Args:
            action_name: Proposed operation name (e.g. 'update_temperature', 'delete_record').
            payload: Parameters of the action.

        Returns:
            True if action is non-destructive and permitted.

        Raises:
            SafetyGateViolation: If action contains destructive keywords.
        """
        action_lower = action_name.lower()
        for kw in cls.DESTRUCTIVE_KEYWORDS:
            if kw in action_lower:
                raise SafetyGateViolation(
                    message=f"Destructive action '{action_name}' is barred from autonomous execution.",
                    code=PlatformErrorCode.DESTRUCTIVE_COMMAND_INTERCEPTED,
                    context={"action_name": action_name, "intercepted_keyword": kw},
                )
        return True
