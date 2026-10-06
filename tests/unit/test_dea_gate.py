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

"""Unit tests for the entitlement gate and FastAPI dependency (Plan 10, T12)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements import dependencies as deps
from core_platform.app.entitlements.audit import EntitlementAuditor
from core_platform.app.entitlements.contracts import (
    Decision,
    DecisionReason,
    EntitlementDeniedError,
)
from core_platform.app.entitlements.evaluator import EntitlementEvaluator
from core_platform.app.entitlements.gate import EntitlementGate
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository

T = "tenant_a"
LOW = "demo:item:view"
HIGH = "demo:item:erase"
PHONE = "+10000000001"
DIGEST = "d" * 64


def _payload() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "namespace": "demo",
        "app_title": "Demo Widget Tracker",
        "actions": [
            {"action_id": LOW, "plain_title": "View the item list",
             "plain_description": "Lets the person look at the list of items.",
             "effect": "READ", "risk": "LOW"},
            {"action_id": HIGH, "plain_title": "Erase the item list",
             "plain_description": "Lets the person permanently erase item records.",
             "effect": "WRITE", "risk": "HIGH"},
        ],
        "bundles": [
            {"bundle_id": "viewer", "title": "Viewer",
             "summary": "Can look at items but not change anything at all.",
             "who_its_for": "Anyone who only needs to look",
             "allowed_scopes": ["TENANT"], "default_scope": "TENANT", "actions": [LOW]},
            {"bundle_id": "eraser", "title": "Eraser",
             "summary": "Can erase item records, which cannot be undone.",
             "who_its_for": "Trusted administrators only", "cannot_do": ["Cannot view reports"],
             "allowed_scopes": ["TENANT"], "default_scope": "TENANT", "actions": [HIGH]},
        ],
    }


class _Rig:
    def __init__(self, repo: EntitlementRepository, mode: List[str]) -> None:
        self.repo = repo
        self.mode = mode
        self.registry = EntitlementRegistry()
        assert self.registry.register_raw("app_x", _payload())
        self.engine_audit = MagicMock()
        self.auditor = EntitlementAuditor(self.engine_audit)
        self.evaluator = EntitlementEvaluator(repo, self.registry)
        self.gate = EntitlementGate(self.evaluator, repo, self.auditor, self.registry,
                                    lambda: self.mode[0])

    def events(self) -> List[str]:
        return [c.kwargs["action_type"] for c in self.engine_audit.record_event.call_args_list]


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[_Rig]:
    engine = create_engine(f"sqlite:///{tmp_path / 'gate.db'}")
    yield _Rig(EntitlementRepository(engine=engine), ["shadow"])
    engine.dispose()


def _ctx() -> SecurityContext:
    return SecurityContext(principal_id=PHONE, tenant_id=T,
                           auth_strategy="phone_biometric", is_authenticated=True)


def _grant(r: _Rig, bundle: str = "viewer") -> None:
    g = r.repo.create_group(T, f"g_{bundle}", None, "USER")
    r.repo.add_member(T, g.id, PHONE)
    r.repo.create_binding(T, g.id, "app_x", bundle, Scope.TENANT, None, DIGEST, "admin")


# -- one test per Section 4.4 row ------------------------------------------------------------

def test_row1_off_never_evaluates(rig: _Rig) -> None:
    rig.mode[0] = "off"
    spy = MagicMock()
    gate = EntitlementGate(spy, rig.repo, rig.auditor, rig.registry, lambda: "off")
    d = gate.check(_ctx(), LOW, legacy_allowed=True)
    assert d.allowed and d.reason == DecisionReason.MODE_OFF
    assert spy.evaluate.call_count == 0
    assert gate.check(_ctx(), LOW, legacy_allowed=False).allowed is False
    assert rig.events() == []


def test_row2_shadow_agreement_not_audited(rig: _Rig) -> None:
    _grant(rig)
    d = rig.gate.check(_ctx(), LOW, legacy_allowed=True)
    assert d.allowed and not d.enforced
    assert rig.events() == []


def test_row3_shadow_disagreement_audited_legacy_decides(rig: _Rig) -> None:
    d = rig.gate.check(_ctx(), LOW, legacy_allowed=True)  # entitlement would deny
    assert d.allowed is True and d.enforced is False
    assert rig.events() == ["ENTITLEMENT_SHADOW_DIFF"]


def test_row3b_shadow_legacy_denies_entitlement_allows(rig: _Rig) -> None:
    _grant(rig)
    d = rig.gate.check(_ctx(), LOW, legacy_allowed=False)
    assert d.allowed is False
    assert rig.events() == ["ENTITLEMENT_SHADOW_DIFF"]


def test_row4_enforce_not_onboarded_falls_back_once(rig: _Rig) -> None:
    rig.mode[0] = "enforce"
    d1 = rig.gate.check(_ctx(), LOW, legacy_allowed=True)
    d2 = rig.gate.check(_ctx(), LOW, legacy_allowed=True)
    assert d1.allowed and d1.reason == DecisionReason.TENANT_NOT_ONBOARDED
    assert d2.allowed
    assert rig.events() == ["ENTITLEMENT_LEGACY_FALLBACK"]


def test_row5_enforce_onboarded_deny_audited(rig: _Rig) -> None:
    rig.mode[0] = "enforce"
    _grant(rig, "viewer")
    d = rig.gate.check(_ctx(), HIGH, legacy_allowed=True)
    assert d.allowed is False and d.enforced is True
    assert rig.events() == ["ENTITLEMENT_DENIED"]
    with pytest.raises(EntitlementDeniedError) as exc:
        rig.gate.enforce(_ctx(), HIGH)
    assert exc.value.decision.reason == DecisionReason.NO_MATCHING_BINDING


def test_row6_enforce_allow_low_not_audited(rig: _Rig) -> None:
    rig.mode[0] = "enforce"
    _grant(rig, "viewer")
    d = rig.gate.enforce(_ctx(), LOW)
    assert d.allowed and d.enforced
    assert rig.events() == []


def test_row7_enforce_allow_high_audited(rig: _Rig) -> None:
    rig.mode[0] = "enforce"
    _grant(rig, "eraser")
    assert rig.gate.check(_ctx(), HIGH).allowed
    assert rig.events() == ["ENTITLEMENT_ALLOWED_HIGH"]


# -- failures ----------------------------------------------------------------------------------

def test_enforce_evaluation_error_denies(rig: _Rig) -> None:
    rig.mode[0] = "enforce"
    _grant(rig)
    boom = MagicMock()
    boom.evaluate.side_effect = RuntimeError("db down")
    gate = EntitlementGate(boom, rig.repo, rig.auditor, rig.registry, lambda: "enforce")
    d = gate.check(_ctx(), LOW)
    assert not d.allowed and d.reason == DecisionReason.EVALUATION_ERROR
    assert rig.events() == ["ENTITLEMENT_DENIED"]


def test_enforce_repository_error_denies(rig: _Rig) -> None:
    broken = MagicMock()
    broken.count_active_bindings.side_effect = RuntimeError("db down")
    gate = EntitlementGate(rig.evaluator, broken, rig.auditor, rig.registry, lambda: "enforce")
    assert gate.check(_ctx(), LOW).reason == DecisionReason.EVALUATION_ERROR


def test_shadow_evaluation_error_legacy_decides(rig: _Rig) -> None:
    boom = MagicMock()
    boom.evaluate.side_effect = RuntimeError("db down")
    gate = EntitlementGate(boom, rig.repo, rig.auditor, rig.registry, lambda: "shadow")
    assert gate.check(_ctx(), LOW, legacy_allowed=True).allowed is True
    assert gate.enforce(_ctx(), LOW, legacy_allowed=True).allowed is True


# -- dependencies ------------------------------------------------------------------------------

@pytest.fixture
def client(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> Iterator[Tuple[TestClient, _Rig]]:
    monkeypatch.setattr(deps, "get_web_security_context", lambda **kw: _ctx())
    deps.set_gate(rig.gate)
    app = FastAPI()

    @app.get("/probe")
    def probe(ctx: SecurityContext = Depends(deps.require_action(LOW))) -> Dict[str, str]:
        return {"who": ctx.principal_id}

    yield TestClient(app), rig
    deps.set_gate(None)


def test_require_action_403_body_is_reason_only(client: Tuple[TestClient, _Rig]) -> None:
    c, r = client
    r.mode[0] = "enforce"
    _grant(r, "eraser")  # onboarded, but no grant for LOW
    resp = c.get("/probe")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "NO_MATCHING_BINDING"}


def test_require_action_allows(client: Tuple[TestClient, _Rig]) -> None:
    c, r = client
    r.mode[0] = "enforce"
    _grant(r, "viewer")
    assert c.get("/probe").status_code == 200


def test_unset_gate_behaves_as_off(monkeypatch: pytest.MonkeyPatch) -> None:
    deps.set_gate(None)
    d = deps.get_gate().check(_ctx(), LOW)
    assert d.allowed and d.reason == DecisionReason.MODE_OFF
    assert deps.authorize_action(_ctx(), LOW).allowed


def test_resource_resolver_is_used(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    from core_platform.app.entitlements.contracts import ResourceRef

    monkeypatch.setattr(deps, "get_web_security_context", lambda **kw: _ctx())
    rig.mode[0] = "enforce"
    g = rig.repo.create_group(T, "self_g", None, "USER")
    rig.repo.add_member(T, g.id, PHONE)
    rig.repo.create_binding(T, g.id, "app_x", "viewer", Scope.TENANT, None, DIGEST, "admin")
    deps.set_gate(rig.gate)
    seen: List[ResourceRef] = []

    def resolver(request: Any) -> ResourceRef:
        ref = ResourceRef(owner_principal_id=PHONE)
        seen.append(ref)
        return ref

    app = FastAPI()

    @app.get("/r")
    def r(ctx: SecurityContext = Depends(deps.require_action(LOW, resolver))) -> Dict[str, str]:
        return {"ok": "1"}

    try:
        assert TestClient(app).get("/r").status_code == 200
        assert len(seen) == 1
    finally:
        deps.set_gate(None)


def test_registry_holder() -> None:
    reg = EntitlementRegistry()
    deps.set_registry(reg)
    assert deps.get_registry() is reg
    deps.set_registry(None)
    assert isinstance(deps.get_registry(), EntitlementRegistry)
    deps.set_registry(None)


def test_decision_model_unchanged_by_gate() -> None:
    d = Decision(allowed=True, reason=DecisionReason.ALLOWED, action_id=LOW)
    assert d.enforced is False
