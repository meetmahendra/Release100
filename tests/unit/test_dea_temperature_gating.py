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

"""Gating tests for temperature_marker routes and the check-in guard (Plan 10, T21)."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Set, Tuple
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from apps.temperature_marker.graph.nodes.layer0_auth_guard import layer0_auth_guard_node
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.entitlements import dependencies as deps
from core_platform.app.entitlements.audit import EntitlementAuditor
from core_platform.app.entitlements.evaluator import EntitlementEvaluator
from core_platform.app.entitlements.gate import EntitlementGate
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository
from core_platform.main import app

APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "temperature_marker"
MANIFEST = APP_DIR / "entitlements.json"
TENANT = "tenant_temp"
PHONE = "+10000000088"
BASE = "/admin/apps/temperature-marker"

Rig = Tuple[TestClient, EntitlementRepository, List[str], MagicMock]


def _literals(path: Path) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if name == "require_action" and node.args and isinstance(node.args[0], ast.Constant):
            found.add(str(node.args[0].value))
        if name == "authorize_action" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            found.add(str(node.args[1].value))
    return found


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    engine = create_engine(f"sqlite:///{tmp_path / 'gate_temp.db'}")
    repo = EntitlementRepository(engine=engine)
    registry = EntitlementRegistry()
    assert registry.register_raw("temperature_marker", json.loads(MANIFEST.read_text(encoding="utf-8")))
    mode: List[str] = ["shadow"]
    sink = MagicMock()
    gate = EntitlementGate(
        EntitlementEvaluator(repo, registry), repo, EntitlementAuditor(sink), registry, lambda: mode[0]
    )
    previous = deps._gate
    deps.set_gate(gate)
    client = TestClient(app)
    client.cookies.set(
        "admin_token", create_jwt_token(PHONE, ["admin"], ["all", "temperature_marker"], tenant_id=TENANT)
    )
    yield client, repo, mode, sink
    deps.set_gate(previous)
    engine.dispose()


def _grant(repo: EntitlementRepository, bundle: str, scope: Scope, principal: str = PHONE) -> None:
    g = repo.create_group(TENANT, f"g_{bundle}_{principal}", None, "USER")
    repo.add_member(TENANT, g.id, principal)
    repo.create_binding(TENANT, g.id, "temperature_marker", bundle, scope, None, "d" * 64, "admin")


def test_all_route_and_guard_literals_are_declared() -> None:
    declared = {a["action_id"] for a in json.loads(MANIFEST.read_text(encoding="utf-8"))["actions"]}
    used = _literals(APP_DIR / "ui" / "routes.py") | _literals(
        APP_DIR / "graph" / "nodes" / "layer0_auth_guard.py"
    )
    assert used <= declared, used - declared
    assert "temperature:telemetry:record" in used


@pytest.mark.parametrize("mode_name", ["off", "shadow"])
def test_off_and_shadow_unchanged(rig: Rig, mode_name: str) -> None:
    client, _repo, mode, _sink = rig
    mode[0] = mode_name
    assert client.get(f"{BASE}/fleet").status_code == 200
    assert client.get(f"{BASE}/monitoring").status_code == 200


def test_enforce_onboarded_without_binding_forbidden(rig: Rig) -> None:
    client, repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "shift_supervisor", Scope.TENANT, principal="+19990000002")
    assert client.get(f"{BASE}/fleet").status_code == 403
    assert client.post(f"{BASE}/api/kiosks", json={}).status_code == 403


def test_enforce_supervisor_views_but_cannot_manage_kiosks(rig: Rig) -> None:
    client, repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "shift_supervisor", Scope.TENANT)
    assert client.get(f"{BASE}/fleet").status_code == 200
    assert client.post(f"{BASE}/api/kiosks", json={}).status_code == 403


def test_enforce_not_onboarded_uses_legacy(rig: Rig) -> None:
    client, _repo, mode, _sink = rig
    mode[0] = "enforce"
    assert client.get(f"{BASE}/fleet").status_code == 200


# -- WhatsApp check-in guard ---------------------------------------------------------------------

def _employee(status: str = "ACTIVE") -> SimpleNamespace:
    return SimpleNamespace(
        status=status, emp_code="E100", full_name="Demo Operator",
        assigned_kiosk_id="KIOSK_1", tenant_id=TENANT,
    )


def _run_guard(employee: Any) -> Dict[str, Any]:
    db = MagicMock()
    db.get_employee_by_phone.return_value = employee
    state: Dict[str, Any] = {"sender_phone": PHONE}
    result = asyncio.run(layer0_auth_guard_node(state, db))  # type: ignore[arg-type]
    return dict(result)


def test_guard_shadow_identical_result_and_diff_audit(rig: Rig) -> None:
    _client, _repo, mode, sink = rig
    mode[0] = "shadow"
    result = _run_guard(_employee())
    assert result["layer_0_passed"] is True and result["operator_status"] == "ACTIVE"
    events = [c.kwargs["action_type"] for c in sink.record_event.call_args_list]
    assert "ENTITLEMENT_SHADOW_DIFF" in events


def test_guard_off_identical_and_silent(rig: Rig) -> None:
    _client, _repo, mode, sink = rig
    mode[0] = "off"
    assert _run_guard(_employee())["layer_0_passed"] is True
    assert sink.record_event.call_count == 0


def test_guard_enforce_denies_without_binding(rig: Rig) -> None:
    _client, repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "field_operator", Scope.SELF, principal="+19990000003")
    result = _run_guard(_employee())
    assert result["layer_0_passed"] is False and result["operator_status"] == "NOT_ENTITLED"


def test_guard_enforce_allows_field_operator_self(rig: Rig) -> None:
    _client, repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "field_operator", Scope.SELF)
    assert _run_guard(_employee())["layer_0_passed"] is True


def test_guard_enforce_not_onboarded_is_legacy(rig: Rig) -> None:
    _client, _repo, mode, _sink = rig
    mode[0] = "enforce"
    assert _run_guard(_employee())["layer_0_passed"] is True


def test_guard_legacy_failures_untouched(rig: Rig) -> None:
    _client, _repo, mode, _sink = rig
    mode[0] = "enforce"
    assert _run_guard(None)["operator_status"] == "UNREGISTERED"
    assert _run_guard(_employee("PENDING"))["operator_status"] == "PENDING"
