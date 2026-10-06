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

"""Deterministic entitlement evaluator (Plan 10, 4.5).

No I/O other than repository reads. Normal denials never raise; repository
exceptions propagate so the gate can convert them into fail-closed decisions.
"""

from __future__ import annotations

from typing import List, Optional

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements.contracts import Decision, DecisionReason, ResourceRef
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import BindingDTO, EntitlementRepository

API_KEY_STRATEGY = "api_key"
KIND_SERVICE = "SERVICE"
KIND_USER = "USER"


class EntitlementEvaluator:
    """Resolve group bindings against the registry to allow or deny an action."""

    def __init__(self, repository: EntitlementRepository, registry: EntitlementRegistry) -> None:
        """Create the evaluator.

        Args:
            repository: Entitlement persistence.
            registry: Loaded cartridge manifests.
        """
        self._repo = repository
        self._registry = registry

    @staticmethod
    def _deny(action_id: str, reason: DecisionReason) -> Decision:
        """Build a denying decision."""
        return Decision(allowed=False, reason=reason, action_id=action_id)

    def _scope_allows(
        self, ctx: SecurityContext, binding: BindingDTO, resource: Optional[ResourceRef]
    ) -> bool:
        """Return True if the binding's scope covers the resource."""
        if binding.scope == Scope.TENANT:
            return True
        if binding.scope == Scope.SELF:
            return resource is not None and resource.owner_principal_id == ctx.principal_id
        if binding.scope == Scope.UNIT:
            if resource is None or not resource.unit_id or not binding.scope_unit_id:
                return False
            return self._repo.unit_in_subtree(
                ctx.tenant_id, binding.scope_unit_id, resource.unit_id
            )
        return False

    def evaluate(
        self,
        ctx: SecurityContext,
        action_id: str,
        resource: Optional[ResourceRef] = None,
    ) -> Decision:
        """Decide whether ``ctx`` may perform ``action_id`` on ``resource``."""
        if not ctx.is_authenticated:
            return self._deny(action_id, DecisionReason.UNAUTHENTICATED)
        if self._registry.get_action(action_id) is None:
            return self._deny(action_id, DecisionReason.UNKNOWN_ACTION)

        kind = KIND_SERVICE if ctx.auth_strategy == API_KEY_STRATEGY else KIND_USER
        group_ids = self._repo.group_ids_for_principal(ctx.tenant_id, ctx.principal_id, kind)
        bindings = self._repo.active_bindings_for_groups(ctx.tenant_id, group_ids)
        candidates: List[BindingDTO] = [
            b
            for b in bindings
            if self._registry.bundle_contains(b.app_id, b.bundle_id, action_id)
        ]
        if not candidates:
            return self._deny(action_id, DecisionReason.NO_MATCHING_BINDING)

        matched = [b.id for b in candidates if self._scope_allows(ctx, b, resource)]
        if matched:
            return Decision(
                allowed=True,
                reason=DecisionReason.ALLOWED,
                action_id=action_id,
                matched_binding_ids=matched,
            )
        return self._deny(action_id, DecisionReason.SCOPE_MISMATCH)
