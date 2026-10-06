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

"""Authorization contracts shared by the evaluator, gate and callers (Plan 10, 4.2)."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from core_platform.app.auth.models import SecurityContext


class ResourceRef(BaseModel):
    """Reference to the resource being acted upon; supplied by the cartridge call site."""

    model_config = ConfigDict(frozen=True)

    owner_principal_id: Optional[str] = None
    unit_id: Optional[str] = None


class DecisionReason(str, Enum):
    """Stable machine-readable reason codes for an authorization decision."""

    ALLOWED = "ALLOWED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    NO_MATCHING_BINDING = "NO_MATCHING_BINDING"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    EVALUATION_ERROR = "EVALUATION_ERROR"
    TENANT_NOT_ONBOARDED = "TENANT_NOT_ONBOARDED"
    MODE_OFF = "MODE_OFF"


class Decision(BaseModel):
    """Outcome of an authorization check."""

    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason: DecisionReason
    action_id: str
    matched_binding_ids: List[str] = Field(default_factory=list)
    enforced: bool = False  # True only when this decision actually decided the outcome


class AuthorizationPort(Protocol):
    """Swap-in point so OpenFGA/Cedar can replace the evaluator later without touching cartridges."""

    def evaluate(
        self,
        ctx: SecurityContext,
        action_id: str,
        resource: Optional[ResourceRef] = None,
    ) -> Decision:
        """Evaluate whether ``ctx`` may perform ``action_id`` on ``resource``."""
        ...


class EntitlementDeniedError(Exception):
    """Raised when an enforced entitlement check denies the request."""

    def __init__(self, decision: Decision) -> None:
        """Store the denying decision for callers and audit."""
        super().__init__(f"Entitlement denied: {decision.reason.value} ({decision.action_id})")
        self.decision = decision
