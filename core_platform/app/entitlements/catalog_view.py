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

"""Read model that turns manifests into bundle cards for the admin UI (Plan 10, T15)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Set

from pydantic import BaseModel, ConfigDict

from core_platform.app.entitlements.models import RiskLevel, Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import BindingDTO, EntitlementRepository

# UI vocabulary (presentation text, not business data).
RISK_LABELS: Dict[RiskLevel, str] = {
    RiskLevel.LOW: "Low risk",
    RiskLevel.MEDIUM: "Operational risk",
    RiskLevel.HIGH: "High governance",
}
SCOPE_LABELS: Dict[Scope, str] = {
    Scope.SELF: "Only their own records",
    Scope.UNIT: "Their department/unit and sub-units",
    Scope.TENANT: "Whole organization",
}


class BundleCardView(BaseModel):
    """Everything the UI needs to explain one bundle to a customer admin."""

    model_config = ConfigDict(frozen=True)
    app_id: str
    app_title: str
    bundle_id: str
    title: str
    summary: str
    who_its_for: str
    can_do: List[str]
    cannot_do: List[str]
    touches: List[str]
    risk: RiskLevel
    risk_label: str
    allowed_scopes: List[Scope]
    scope_labels: Dict[str, str]
    default_scope: Scope
    action_count: int
    assigned_group_count: int
    conflicts_with_titles: List[str]
    drifted_binding_count: int


def build_catalog(
    tenant_id: str,
    registry: EntitlementRegistry,
    repository: EntitlementRepository,
    enabled_app_ids: Iterable[str],
) -> List[BundleCardView]:
    """Build bundle cards for the enabled apps of a tenant (empty registry -> empty list)."""
    enabled: Set[str] = set(enabled_app_ids)
    bindings: List[BindingDTO] = repository.list_active_bindings(tenant_id)
    cards: List[BundleCardView] = []
    for app_id in registry.list_apps():
        if app_id not in enabled:
            continue
        manifest = registry.get_manifest(app_id)
        if manifest is None:
            continue
        amap = manifest.action_map()
        titles = {b.bundle_id: b.title for b in manifest.bundles}
        for bundle in manifest.bundles:
            mine = [b for b in bindings if b.app_id == app_id and b.bundle_id == bundle.bundle_id]
            current_digest = manifest.bundle_digest(bundle.bundle_id)
            touches: List[str] = []
            for action_id in bundle.actions:
                for item in amap[action_id].touches:
                    if item not in touches:
                        touches.append(item)
            risk = manifest.bundle_risk(bundle.bundle_id)
            cards.append(
                BundleCardView(
                    app_id=app_id,
                    app_title=manifest.app_title,
                    bundle_id=bundle.bundle_id,
                    title=bundle.title,
                    summary=bundle.summary,
                    who_its_for=bundle.who_its_for,
                    can_do=[amap[a].plain_title for a in bundle.actions],
                    cannot_do=list(bundle.cannot_do),
                    touches=touches,
                    risk=risk,
                    risk_label=RISK_LABELS[risk],
                    allowed_scopes=list(bundle.allowed_scopes),
                    scope_labels={s.value: SCOPE_LABELS[s] for s in bundle.allowed_scopes},
                    default_scope=bundle.default_scope,
                    action_count=len(bundle.actions),
                    assigned_group_count=len({b.group_id for b in mine}),
                    conflicts_with_titles=[
                        titles[c] for c in bundle.conflicts_with if c in titles
                    ],
                    drifted_binding_count=sum(1 for b in mine if b.bundle_digest != current_digest),
                )
            )
    return cards
