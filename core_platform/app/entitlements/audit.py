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

"""Audit wrapper for entitlement events (Plan 10, T10).

Routes every entitlement event into the SHA-256 chained ``AuditEngine``.
Failures inside the audit engine are logged and swallowed here only, because
auditing must never crash a request.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Mapping, Optional

from core_platform.app.telemetry.audit_engine import AuditEngine

logger = logging.getLogger(__name__)


class AuditEvent(str, Enum):
    """Event names written to the audit trail."""

    ENTITLEMENT_DENIED = "ENTITLEMENT_DENIED"
    ENTITLEMENT_SHADOW_DIFF = "ENTITLEMENT_SHADOW_DIFF"
    ENTITLEMENT_LEGACY_FALLBACK = "ENTITLEMENT_LEGACY_FALLBACK"
    ENTITLEMENT_ALLOWED_HIGH = "ENTITLEMENT_ALLOWED_HIGH"
    ENTITLEMENT_BINDING_CREATED = "ENTITLEMENT_BINDING_CREATED"
    ENTITLEMENT_BINDING_REVOKED = "ENTITLEMENT_BINDING_REVOKED"
    ENTITLEMENT_GROUP_CHANGED = "ENTITLEMENT_GROUP_CHANGED"
    ENTITLEMENT_BUNDLE_DRIFT = "ENTITLEMENT_BUNDLE_DRIFT"
    ENTITLEMENT_MANIFEST_REJECTED = "ENTITLEMENT_MANIFEST_REJECTED"


class EntitlementAuditor:
    """Thin, failure-isolating wrapper over ``AuditEngine.record_event``."""

    def __init__(self, engine: Optional[AuditEngine] = None) -> None:
        """Create the auditor.

        Args:
            engine: Audit engine to use; the process singleton when omitted.
        """
        self._engine = engine

    def _resolve_engine(self) -> AuditEngine:
        """Return the injected engine or the singleton (resolved lazily)."""
        if self._engine is not None:
            return self._engine
        return AuditEngine.get_instance()

    def emit(
        self,
        event: str,
        tenant_id: str,
        principal_id: str,
        detail: Mapping[str, Any],
        denied: bool,
    ) -> None:
        """Record one audit event; never raises.

        Args:
            event: Event name (an ``AuditEvent`` value).
            tenant_id: Tenant the event belongs to.
            principal_id: Acting principal.
            detail: Extra non-secret fields.
            denied: True when the event represents a denial.
        """
        event_name = event.value if isinstance(event, AuditEvent) else str(event)
        payload = {"tenant_id": tenant_id, **dict(detail)}
        try:
            self._resolve_engine().record_event(
                action_type=event_name,
                payload_summary=payload,
                operator_id=principal_id,
                layer_0_status="DENIED" if denied else "PASSED",
                layer_1_model="deterministic_rbac",
                layer_1_confidence=1.0,
                layer_2_gate_status="DENIED" if denied else "APPROVED",
            )
        except Exception as err:  # noqa: BLE001 - auditing must never crash a request
            logger.error("Entitlement audit emit failed for %s: %s", event_name, err)
