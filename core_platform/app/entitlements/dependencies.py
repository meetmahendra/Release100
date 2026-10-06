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

"""Module-level holders and FastAPI dependency for entitlement checks (Plan 10, T12)."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import Cookie, Header, HTTPException, Request, status

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements.audit import EntitlementAuditor
from core_platform.app.entitlements.contracts import (
    Decision,
    EntitlementDeniedError,
    ResourceRef,
)
from core_platform.app.entitlements.evaluator import EntitlementEvaluator
from core_platform.app.entitlements.gate import MODE_OFF, EntitlementGate
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository
from core_platform.app.rbac.permissions import get_web_security_context

_gate: Optional[EntitlementGate] = None
_registry: Optional[EntitlementRegistry] = None
_off_gate: Optional[EntitlementGate] = None


def set_gate(gate: Optional[EntitlementGate]) -> None:
    """Install (or clear) the process-wide gate."""
    global _gate
    _gate = gate


def set_registry(registry: Optional[EntitlementRegistry]) -> None:
    """Install (or clear) the process-wide registry."""
    global _registry
    _registry = registry


def get_registry() -> EntitlementRegistry:
    """Return the installed registry, or a new empty one when unset."""
    global _registry
    if _registry is None:
        _registry = EntitlementRegistry()
    return _registry


def _build_off_gate() -> EntitlementGate:
    """Build an inert gate used while none is installed (never touches the database)."""
    registry = get_registry()
    repo = EntitlementRepository.__new__(EntitlementRepository)
    evaluator = EntitlementEvaluator(repo, registry)
    return EntitlementGate(evaluator, repo, EntitlementAuditor(), registry, lambda: MODE_OFF)


def get_gate() -> EntitlementGate:
    """Return the installed gate; an unset gate behaves as mode ``off``."""
    global _off_gate
    if _gate is not None:
        return _gate
    if _off_gate is None:
        _off_gate = _build_off_gate()
    return _off_gate


def authorize_action(
    ctx: SecurityContext, action_id: str, resource: Optional[ResourceRef] = None
) -> Decision:
    """Authorize a non-HTTP caller; raise ``EntitlementDeniedError`` on denial."""
    return get_gate().enforce(ctx, action_id, resource)


def require_action(
    action_id: str,
    resource_resolver: Optional[Callable[[Request], ResourceRef]] = None,
) -> Callable[..., SecurityContext]:
    """FastAPI dependency factory: require that the caller may perform ``action_id``."""

    def _action_checker(
        request: Request,
        admin_token: Optional[str] = Cookie(default=None, alias="admin_token"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ) -> SecurityContext:
        ctx = get_web_security_context(
            admin_token=admin_token, authorization=authorization, api_key=api_key
        )
        resource: Optional[ResourceRef] = None
        if resource_resolver is not None:
            resource = resource_resolver(request)
        try:
            get_gate().enforce(ctx, action_id, resource)
        except EntitlementDeniedError as err:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=err.decision.reason.value,
            ) from err
        return ctx

    return _action_checker


__all__: list[str] = [
    "set_gate",
    "get_gate",
    "set_registry",
    "get_registry",
    "authorize_action",
    "require_action",
]
