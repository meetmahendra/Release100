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

"""Entitlement gate: the only place the rollout mode is interpreted (Plan 10, 4.4)."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional, Set

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements.audit import AuditEvent, EntitlementAuditor
from core_platform.app.entitlements.contracts import (
    AuthorizationPort,
    Decision,
    DecisionReason,
    EntitlementDeniedError,
    ResourceRef,
)
from core_platform.app.entitlements.models import RiskLevel
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository

logger = logging.getLogger(__name__)

MODE_OFF = "off"
MODE_SHADOW = "shadow"


class EntitlementGate:
    """Combine legacy role outcome and entitlement evaluation according to the rollout mode."""

    def __init__(
        self,
        evaluator: AuthorizationPort,
        repository: EntitlementRepository,
        auditor: EntitlementAuditor,
        registry: EntitlementRegistry,
        mode_provider: Callable[[], str],
    ) -> None:
        """Create the gate.

        Args:
            evaluator: Authorization engine.
            repository: Used only to decide whether a tenant is onboarded.
            auditor: Audit sink.
            registry: Used to look up an action's risk for audit decisions.
            mode_provider: Returns the current mode (off, shadow or enforce).
        """
        self._evaluator = evaluator
        self._repo = repository
        self._auditor = auditor
        self._registry = registry
        self._mode_provider = mode_provider
        self._fallback_logged: Set[str] = set()
        self._lock = threading.Lock()

    def _audit_denied(self, ctx: SecurityContext, decision: Decision) -> None:
        """Audit an enforced denial."""
        self._auditor.emit(
            AuditEvent.ENTITLEMENT_DENIED.value,
            ctx.tenant_id,
            ctx.principal_id,
            {"action_id": decision.action_id, "reason": decision.reason.value},
            True,
        )

    def _audit_fallback_once(self, ctx: SecurityContext, action_id: str) -> None:
        """Audit the legacy fallback once per tenant per process."""
        with self._lock:
            if ctx.tenant_id in self._fallback_logged:
                return
            self._fallback_logged.add(ctx.tenant_id)
        self._auditor.emit(
            AuditEvent.ENTITLEMENT_LEGACY_FALLBACK.value,
            ctx.tenant_id,
            ctx.principal_id,
            {"action_id": action_id},
            False,
        )

    def _shadow(
        self,
        ctx: SecurityContext,
        action_id: str,
        resource: Optional[ResourceRef],
        legacy_allowed: bool,
    ) -> Decision:
        """Shadow mode: legacy decides; disagreements are audited."""
        try:
            evaluated = self._evaluator.evaluate(ctx, action_id, resource)
        except Exception as err:  # noqa: BLE001 - shadow must never affect the outcome
            logger.error("Entitlement shadow evaluation failed: %s", err)
            return Decision(
                allowed=legacy_allowed, reason=DecisionReason.EVALUATION_ERROR, action_id=action_id
            )
        if evaluated.allowed != legacy_allowed:
            self._auditor.emit(
                AuditEvent.ENTITLEMENT_SHADOW_DIFF.value,
                ctx.tenant_id,
                ctx.principal_id,
                {
                    "action_id": action_id,
                    "legacy_allowed": legacy_allowed,
                    "entitlement_allowed": evaluated.allowed,
                    "reason": evaluated.reason.value,
                },
                not evaluated.allowed,
            )
        return Decision(
            allowed=legacy_allowed,
            reason=evaluated.reason,
            action_id=action_id,
            matched_binding_ids=list(evaluated.matched_binding_ids),
        )

    def _enforce(
        self,
        ctx: SecurityContext,
        action_id: str,
        resource: Optional[ResourceRef],
        legacy_allowed: bool,
    ) -> Decision:
        """Enforce mode: onboarded tenants are decided by the evaluator, fail-closed."""
        try:
            onboarded = self._repo.count_active_bindings(ctx.tenant_id) > 0
            if not onboarded:
                self._audit_fallback_once(ctx, action_id)
                return Decision(
                    allowed=legacy_allowed,
                    reason=DecisionReason.TENANT_NOT_ONBOARDED,
                    action_id=action_id,
                )
            evaluated = self._evaluator.evaluate(ctx, action_id, resource)
        except Exception as err:  # noqa: BLE001 - fail closed on any evaluation failure
            logger.error("Entitlement evaluation failed (denying): %s", err)
            denied = Decision(
                allowed=False,
                reason=DecisionReason.EVALUATION_ERROR,
                action_id=action_id,
                enforced=True,
            )
            self._audit_denied(ctx, denied)
            return denied

        decision = evaluated.model_copy(update={"enforced": True})
        if not decision.allowed:
            self._audit_denied(ctx, decision)
        else:
            action = self._registry.get_action(action_id)
            if action is not None and action.risk == RiskLevel.HIGH:
                self._auditor.emit(
                    AuditEvent.ENTITLEMENT_ALLOWED_HIGH.value,
                    ctx.tenant_id,
                    ctx.principal_id,
                    {"action_id": action_id},
                    False,
                )
        return decision

    def check(
        self,
        ctx: SecurityContext,
        action_id: str,
        resource: Optional[ResourceRef] = None,
        legacy_allowed: bool = True,
    ) -> Decision:
        """Return the final decision for this request according to the rollout mode."""
        mode = self._mode_provider()
        if mode == MODE_OFF:
            return Decision(allowed=legacy_allowed, reason=DecisionReason.MODE_OFF, action_id=action_id)
        if mode == MODE_SHADOW:
            return self._shadow(ctx, action_id, resource, legacy_allowed)
        return self._enforce(ctx, action_id, resource, legacy_allowed)

    def enforce(
        self,
        ctx: SecurityContext,
        action_id: str,
        resource: Optional[ResourceRef] = None,
        legacy_allowed: bool = True,
    ) -> Decision:
        """Like ``check`` but raise ``EntitlementDeniedError`` when the outcome is a denial."""
        decision = self.check(ctx, action_id, resource, legacy_allowed)
        if not decision.allowed:
            raise EntitlementDeniedError(decision)
        return decision

    def enforce_unmapped_tool(self, ctx: SecurityContext, tool_name: str) -> Decision:
        """Decide a tool call whose MCP tool has no declared action (fail closed under enforce).

        ``off``: allow silently. ``shadow``: allow and audit a diff. ``enforce``: deny for an
        onboarded tenant, legacy fallback for a tenant with no bindings.
        """
        action_id = "unmapped_mcp_tool"
        mode = self._mode_provider()
        if mode == MODE_OFF:
            return Decision(allowed=True, reason=DecisionReason.MODE_OFF, action_id=action_id)
        if mode == MODE_SHADOW:
            self._auditor.emit(
                AuditEvent.ENTITLEMENT_SHADOW_DIFF.value,
                ctx.tenant_id,
                ctx.principal_id,
                {"unmapped_mcp_tool": tool_name},
                True,
            )
            return Decision(allowed=True, reason=DecisionReason.UNKNOWN_ACTION, action_id=action_id)
        try:
            onboarded = self._repo.count_active_bindings(ctx.tenant_id) > 0
        except Exception as err:  # noqa: BLE001 - fail closed
            logger.error("Entitlement onboarding lookup failed (denying): %s", err)
            onboarded = True
        if not onboarded:
            return Decision(allowed=True, reason=DecisionReason.TENANT_NOT_ONBOARDED, action_id=action_id)
        denied = Decision(
            allowed=False, reason=DecisionReason.UNKNOWN_ACTION, action_id=action_id, enforced=True
        )
        self._auditor.emit(
            AuditEvent.ENTITLEMENT_DENIED.value,
            ctx.tenant_id,
            ctx.principal_id,
            {"unmapped_mcp_tool": tool_name, "reason": denied.reason.value},
            True,
        )
        raise EntitlementDeniedError(denied)