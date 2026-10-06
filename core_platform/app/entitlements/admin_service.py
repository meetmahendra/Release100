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

"""Customer-admin operations on groups, units and bundle bindings (Plan 10, T14).

Every method derives the tenant and the actor from the ``SecurityContext`` so a
caller can never act on another tenant. Failures are ``ValueError`` with a stable code.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements.audit import AuditEvent, EntitlementAuditor
from core_platform.app.entitlements.models import RiskLevel, Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import (
    BindingDTO,
    EntitlementRepository,
    GroupDTO,
    MemberDTO,
    UnitDTO,
)

KIND_SERVICE = "SERVICE"
KIND_USER = "USER"


class EffectiveActionDTO(BaseModel):
    """One row of "what can this person do", expanded from bindings."""

    model_config = ConfigDict(frozen=True)
    action_id: str
    plain_title: str
    app_title: str
    scope: Scope
    scope_unit_name: Optional[str]
    via_bundle: str
    via_group: str


class EntitlementAdminService:
    """Validated write operations plus the effective-access read model."""

    def __init__(
        self,
        repository: EntitlementRepository,
        registry: EntitlementRegistry,
        auditor: EntitlementAuditor,
    ) -> None:
        """Create the service.

        Args:
            repository: Entitlement persistence.
            registry: Loaded cartridge manifests.
            auditor: Audit sink.
        """
        self._repo = repository
        self._registry = registry
        self._auditor = auditor

    def _audit(
        self, ctx: SecurityContext, event: AuditEvent, detail: Dict[str, object], denied: bool = False
    ) -> None:
        """Emit an audit event for the acting admin."""
        self._auditor.emit(event.value, ctx.tenant_id, ctx.principal_id, detail, denied)

    def create_unit(
        self, ctx: SecurityContext, name: str, label: str, parent_id: Optional[str]
    ) -> UnitDTO:
        """Create an organizational unit in the caller's tenant."""
        unit = self._repo.create_unit(ctx.tenant_id, name, label, parent_id)
        self._audit(ctx, AuditEvent.ENTITLEMENT_GROUP_CHANGED, {"change": "unit_created", "unit_id": unit.id})
        return unit

    def create_group(
        self, ctx: SecurityContext, name: str, description: Optional[str], kind: str
    ) -> GroupDTO:
        """Create a group (kind USER or SERVICE) in the caller's tenant."""
        group = self._repo.create_group(ctx.tenant_id, name, description, kind)
        self._audit(
            ctx,
            AuditEvent.ENTITLEMENT_GROUP_CHANGED,
            {"change": "group_created", "group_id": group.id, "kind": group.kind},
        )
        return group

    def add_member(self, ctx: SecurityContext, group_id: str, principal_id: str) -> MemberDTO:
        """Add a principal to a group."""
        member = self._repo.add_member(ctx.tenant_id, group_id, principal_id)
        self._audit(
            ctx,
            AuditEvent.ENTITLEMENT_GROUP_CHANGED,
            {"change": "member_added", "group_id": group_id, "member": principal_id},
        )
        return member

    def remove_member(self, ctx: SecurityContext, group_id: str, principal_id: str) -> bool:
        """Remove a principal from a group; returns whether a membership was removed."""
        removed = self._repo.remove_member(ctx.tenant_id, group_id, principal_id)
        if removed:
            self._audit(
                ctx,
                AuditEvent.ENTITLEMENT_GROUP_CHANGED,
                {"change": "member_removed", "group_id": group_id, "member": principal_id},
            )
        return removed

    def bind_bundle(
        self,
        ctx: SecurityContext,
        group_id: str,
        app_id: str,
        bundle_id: str,
        scope: Scope,
        scope_unit_id: Optional[str],
        confirm_high_risk: bool,
    ) -> BindingDTO:
        """Grant a bundle to a group after all validations.

        Raises:
            ValueError: ``GROUP_NOT_FOUND``, ``UNKNOWN_BUNDLE``,
                ``SERVICE_GROUP_CANNOT_HOLD_HIGH_RISK``, ``SCOPE_NOT_ALLOWED``,
                ``HIGH_RISK_CONFIRMATION_REQUIRED`` or a repository code.
        """
        group = self._repo.get_group(ctx.tenant_id, group_id)
        if group is None:
            raise ValueError("GROUP_NOT_FOUND")
        manifest = self._registry.get_manifest(app_id)
        bundle = self._registry.get_bundle(app_id, bundle_id)
        if manifest is None or bundle is None:
            raise ValueError("UNKNOWN_BUNDLE")
        risk = manifest.bundle_risk(bundle_id)
        if group.kind == KIND_SERVICE and risk == RiskLevel.HIGH:
            raise ValueError("SERVICE_GROUP_CANNOT_HOLD_HIGH_RISK")
        if scope not in bundle.allowed_scopes:
            raise ValueError("SCOPE_NOT_ALLOWED")
        if risk == RiskLevel.HIGH and not confirm_high_risk:
            raise ValueError("HIGH_RISK_CONFIRMATION_REQUIRED")
        digest = manifest.bundle_digest(bundle_id)
        binding = self._repo.create_binding(
            ctx.tenant_id, group_id, app_id, bundle_id, scope, scope_unit_id, digest, ctx.principal_id
        )
        self._audit(
            ctx,
            AuditEvent.ENTITLEMENT_BINDING_CREATED,
            {
                "binding_id": binding.id,
                "group_id": group_id,
                "app_id": app_id,
                "bundle_id": bundle_id,
                "scope": scope.value,
                "risk": risk.value,
                "digest": digest,
            },
        )
        return binding

    def unbind(self, ctx: SecurityContext, binding_id: str) -> bool:
        """Revoke a binding (soft); returns whether it was active."""
        revoked = self._repo.revoke_binding(ctx.tenant_id, binding_id, ctx.principal_id)
        if revoked:
            self._audit(ctx, AuditEvent.ENTITLEMENT_BINDING_REVOKED, {"binding_id": binding_id})
        return revoked

    def effective_access(self, ctx: SecurityContext, principal_id: str) -> List[EffectiveActionDTO]:
        """Expand every active binding of a principal's groups into per-action rows."""
        group_ids: List[str] = []
        for kind in (KIND_USER, KIND_SERVICE):
            group_ids.extend(self._repo.group_ids_for_principal(ctx.tenant_id, principal_id, kind))
        if not group_ids:
            return []
        groups = {g.id: g for g in self._repo.list_groups(ctx.tenant_id)}
        units = {u.id: u.name for u in self._repo.list_units(ctx.tenant_id)}
        rows: List[EffectiveActionDTO] = []
        for binding in self._repo.active_bindings_for_groups(ctx.tenant_id, group_ids):
            manifest = self._registry.get_manifest(binding.app_id)
            bundle = self._registry.get_bundle(binding.app_id, binding.bundle_id)
            if manifest is None or bundle is None:
                continue
            amap = manifest.action_map()
            group = groups.get(binding.group_id)
            for action_id in bundle.actions:
                action = amap.get(action_id)
                if action is None:
                    continue
                rows.append(
                    EffectiveActionDTO(
                        action_id=action_id,
                        plain_title=action.plain_title,
                        app_title=manifest.app_title,
                        scope=binding.scope,
                        scope_unit_name=units.get(binding.scope_unit_id or ""),
                        via_bundle=bundle.title,
                        via_group=group.name if group else binding.group_id,
                    )
                )
        return rows
