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

"""Tests for the entitlement audit wrapper."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

from core_platform.app.entitlements.audit import AuditEvent, EntitlementAuditor
from core_platform.app.telemetry.audit_engine import AuditEngine


def test_denied_event_kwargs() -> None:
    """A denial maps to DENIED statuses and carries tenant_id in the payload."""
    engine = MagicMock()
    EntitlementAuditor(cast(AuditEngine, engine)).emit(
        AuditEvent.ENTITLEMENT_DENIED.value, "t1", "p1", {"action": "demo:x"}, True
    )
    kw: Any = engine.record_event.call_args.kwargs
    assert kw["action_type"] == "ENTITLEMENT_DENIED"
    assert kw["payload_summary"] == {"tenant_id": "t1", "action": "demo:x"}
    assert kw["operator_id"] == "p1"
    assert kw["layer_0_status"] == "DENIED"
    assert kw["layer_2_gate_status"] == "DENIED"
    assert kw["layer_1_model"] == "deterministic_rbac"
    assert kw["layer_1_confidence"] == 1.0


def test_allowed_event_kwargs() -> None:
    """A non-denial maps to PASSED / APPROVED."""
    engine = MagicMock()
    EntitlementAuditor(cast(AuditEngine, engine)).emit(
        AuditEvent.ENTITLEMENT_ALLOWED_HIGH, "t1", "p1", {}, False
    )
    kw: Any = engine.record_event.call_args.kwargs
    assert kw["action_type"] == "ENTITLEMENT_ALLOWED_HIGH"
    assert kw["layer_0_status"] == "PASSED"
    assert kw["layer_2_gate_status"] == "APPROVED"


def test_engine_exception_is_swallowed() -> None:
    """An exception inside the engine never propagates."""
    engine = MagicMock()
    engine.record_event.side_effect = RuntimeError("disk full")
    EntitlementAuditor(cast(AuditEngine, engine)).emit("X", "t1", "p1", {}, True)


def test_default_engine_is_singleton(monkeypatch: Any) -> None:
    """Without an injected engine, the singleton is used."""
    engine = MagicMock()
    monkeypatch.setattr(AuditEngine, "get_instance", classmethod(lambda cls: engine))
    EntitlementAuditor().emit("X", "t1", "p1", {}, False)
    assert engine.record_event.called


def test_event_names_complete() -> None:
    """All nine plan event names exist."""
    assert len(list(AuditEvent)) == 9
