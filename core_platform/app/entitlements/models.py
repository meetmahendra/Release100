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

"""Entitlement manifest contract (Plan 10, section 4.1).

Pydantic models that validate the ``entitlements.json`` file shipped by every
cartridge. Validation is strict: a malformed manifest is rejected as a whole.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ACTION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}:[a-z][a-z0-9_]{1,31}:[a-z][a-z0-9_]{1,31}$")
NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
BUNDLE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,47}$")


class RiskLevel(str, Enum):
    """Risk classification of an action or (derived) bundle."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


RISK_RANK: Dict[RiskLevel, int] = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}


class ActionEffect(str, Enum):
    """What an action does; drives the minimum allowed risk level."""

    READ = "READ"
    WRITE = "WRITE"
    APPROVE = "APPROVE"
    CONFIGURE = "CONFIGURE"
    EXPORT = "EXPORT"
    EXTERNAL_EFFECT = "EXTERNAL_EFFECT"


MIN_RISK_FOR_EFFECT: Dict[ActionEffect, RiskLevel] = {
    ActionEffect.READ: RiskLevel.LOW,
    ActionEffect.WRITE: RiskLevel.LOW,
    ActionEffect.APPROVE: RiskLevel.MEDIUM,
    ActionEffect.EXTERNAL_EFFECT: RiskLevel.MEDIUM,
    ActionEffect.CONFIGURE: RiskLevel.HIGH,
    ActionEffect.EXPORT: RiskLevel.HIGH,
}


class Scope(str, Enum):
    """Breadth of a granted bundle."""

    SELF = "SELF"
    UNIT = "UNIT"
    TENANT = "TENANT"


class ActionDef(BaseModel):
    """A single granular capability declared by a cartridge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    plain_title: str = Field(min_length=8, max_length=80)
    plain_description: str = Field(min_length=20, max_length=300)
    effect: ActionEffect
    risk: RiskLevel
    touches: List[str] = Field(default_factory=list)
    mcp_tools: List[str] = Field(default_factory=list)  # MCP tool names this action authorizes (D15)


class BundleDef(BaseModel):
    """A pre-packaged, human-readable set of actions assignable to a group."""

    model_config = ConfigDict(extra="forbid", frozen=True)  # declaring "risk" here is a validation error (D10)

    bundle_id: str
    title: str = Field(min_length=3, max_length=60)
    summary: str = Field(min_length=20, max_length=200)
    who_its_for: str = Field(min_length=10, max_length=160)
    cannot_do: List[str] = Field(default_factory=list)
    allowed_scopes: List[Scope] = Field(min_length=1)
    default_scope: Scope
    actions: List[str] = Field(min_length=1)
    conflicts_with: List[str] = Field(default_factory=list)


class EntitlementManifest(BaseModel):
    """Complete entitlement declaration of one cartridge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    namespace: str
    app_title: str = Field(min_length=3, max_length=80)
    actions: List[ActionDef] = Field(min_length=1)
    bundles: List[BundleDef] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_cross_references(self) -> "EntitlementManifest":
        """Validate namespace, risk floors, and bundle/action cross references."""
        errors: List[str] = []
        if not NAMESPACE_PATTERN.match(self.namespace):
            errors.append(f"namespace '{self.namespace}' invalid")
        action_ids = [a.action_id for a in self.actions]
        if len(set(action_ids)) != len(action_ids):
            errors.append("duplicate action_id")
        for a in self.actions:
            if not ACTION_ID_PATTERN.match(a.action_id):
                errors.append(f"action_id '{a.action_id}' malformed")
            elif not a.action_id.startswith(self.namespace + ":"):
                errors.append(f"action_id '{a.action_id}' outside namespace '{self.namespace}'")
            if RISK_RANK[a.risk] < RISK_RANK[MIN_RISK_FOR_EFFECT[a.effect]]:
                errors.append(f"action '{a.action_id}' risk {a.risk.value} below floor for effect {a.effect.value}")
        bundle_ids = [b.bundle_id for b in self.bundles]
        if len(set(bundle_ids)) != len(bundle_ids):
            errors.append("duplicate bundle_id")
        declared = set(action_ids)
        used: set[str] = set()
        by_id = {a.action_id: a for a in self.actions}
        for b in self.bundles:
            if not BUNDLE_ID_PATTERN.match(b.bundle_id):
                errors.append(f"bundle_id '{b.bundle_id}' malformed")
            if b.default_scope not in b.allowed_scopes:
                errors.append(f"bundle '{b.bundle_id}' default_scope not in allowed_scopes")
            if len(set(b.actions)) != len(b.actions):
                errors.append(f"bundle '{b.bundle_id}' has duplicate actions")
            for aid in b.actions:
                if aid not in declared:
                    errors.append(f"bundle '{b.bundle_id}' references undeclared action '{aid}'")
                else:
                    used.add(aid)
            for other in b.conflicts_with:
                if other not in bundle_ids or other == b.bundle_id:
                    errors.append(f"bundle '{b.bundle_id}' conflicts_with unknown/self '{other}'")
            risks = [RISK_RANK[by_id[x].risk] for x in b.actions if x in by_id]
            if risks and max(risks) >= RISK_RANK[RiskLevel.MEDIUM] and not b.cannot_do:
                errors.append(f"bundle '{b.bundle_id}' is MEDIUM/HIGH risk and must list cannot_do")
        for aid in sorted(declared - used):
            errors.append(f"action '{aid}' is not in any bundle")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def action_map(self) -> Dict[str, ActionDef]:
        """Return actions indexed by action_id."""
        return {a.action_id: a for a in self.actions}

    def bundle_risk(self, bundle_id: str) -> RiskLevel:
        """Return the derived risk of a bundle: the maximum risk among its actions."""
        amap = self.action_map()
        bundle = next(b for b in self.bundles if b.bundle_id == bundle_id)
        return max((amap[x].risk for x in bundle.actions), key=lambda r: RISK_RANK[r])

    def bundle_digest(self, bundle_id: str) -> str:
        """Return a stable SHA-256 digest of the bundle's sorted action ids."""
        bundle = next(b for b in self.bundles if b.bundle_id == bundle_id)
        return hashlib.sha256("|".join(sorted(bundle.actions)).encode("utf-8")).hexdigest()
