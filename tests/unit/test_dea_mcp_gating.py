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

"""MCP tool gating tests for API-key (SERVICE) callers (Plan 10, T21b)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements import dependencies as deps
from core_platform.app.entitlements.audit import EntitlementAuditor
from core_platform.app.entitlements.evaluator import EntitlementEvaluator
from core_platform.app.entitlements.gate import EntitlementGate
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository
from core_platform.app.mcp_server import server

ROOT = Path(__file__).resolve().parents[2]
TENANT = "tenant_mcp"
KEY_ID = "key_principal_demo_1"
PHONE = "+10000000099"

Rig = Tuple[EntitlementRepository, List[str], MagicMock]


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    engine = create_engine(f"sqlite:///{tmp_path / 'mcp.db'}")
    repo = EntitlementRepository(engine=engine)
    registry = EntitlementRegistry()
    for app_id in ("mail_organizer", "temperature_marker"):
        raw = json.loads((ROOT / "apps" / app_id / "entitlements.json").read_text(encoding="utf-8"))
        assert registry.register_raw(app_id, raw)
    mode: List[str] = ["shadow"]
    sink = MagicMock()
    gate = EntitlementGate(
        EntitlementEvaluator(repo, registry), repo, EntitlementAuditor(sink), registry, lambda: mode[0]
    )
    prev_gate, prev_reg = deps._gate, deps._registry
    deps.set_gate(gate)
    deps.set_registry(registry)

    async def fake_handler(**kwargs: Any) -> Dict[str, Any]:
        return {"ran": True}

    monkeypatch.setattr(server, "get_tool_handler", lambda name: fake_handler)
    yield repo, mode, sink
    deps.set_gate(prev_gate)
    deps.set_registry(prev_reg)
    engine.dispose()


def _key_ctx(principal: str = KEY_ID) -> SecurityContext:
    return SecurityContext(principal_id=principal, tenant_id=TENANT, auth_strategy="api_key",
                           is_authenticated=True)


def _call(tool: str, ctx: SecurityContext) -> Dict[str, Any]:
    return asyncio.run(server._handle_tools_call({"name": tool, "arguments": {}}, ctx))


def _grant(repo: EntitlementRepository, kind: str, principal: str, app: str, bundle: str) -> None:
    g = repo.create_group(TENANT, f"g_{kind}_{principal}_{bundle}", None, kind)
    repo.add_member(TENANT, g.id, principal)
    repo.create_binding(TENANT, g.id, app, bundle, Scope.TENANT, None, "d" * 64, "admin")


def _is_forbidden(result: Dict[str, Any]) -> bool:
    return result.get("isError") is True and result["content"][0]["text"] == "Forbidden"


def test_shadow_executes_and_audits_diff(rig: Rig) -> None:
    _repo, mode, sink = rig
    mode[0] = "shadow"
    result = _call("mail_approve_pm_task", _key_ctx())
    assert json.loads(result["content"][0]["text"]) == {"ran": True}
    events = [c.kwargs["action_type"] for c in sink.record_event.call_args_list]
    assert "ENTITLEMENT_SHADOW_DIFF" in events


def test_off_executes_silently(rig: Rig) -> None:
    _repo, mode, sink = rig
    mode[0] = "off"
    assert "isError" not in _call("mail_approve_pm_task", _key_ctx())
    assert sink.record_event.call_count == 0


def test_enforce_key_in_no_group_forbidden(rig: Rig) -> None:
    repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "SERVICE", "some_other_key", "mail_organizer", "project_lead")  # onboards tenant
    assert _is_forbidden(_call("mail_approve_pm_task", _key_ctx()))


def test_enforce_service_group_with_bundle_executes(rig: Rig) -> None:
    repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "SERVICE", KEY_ID, "mail_organizer", "project_lead")
    result = _call("mail_approve_pm_task", _key_ctx())
    assert json.loads(result["content"][0]["text"]) == {"ran": True}
    # a tool outside the granted bundle stays forbidden
    assert _is_forbidden(_call("temperature_approve_operator", _key_ctx()))


def test_enforce_unmapped_tool_denied_when_onboarded(rig: Rig) -> None:
    repo, mode, sink = rig
    mode[0] = "enforce"
    _grant(repo, "SERVICE", KEY_ID, "mail_organizer", "project_lead")
    assert _is_forbidden(_call("tool_without_action", _key_ctx()))
    events = [c.kwargs["action_type"] for c in sink.record_event.call_args_list]
    assert "ENTITLEMENT_DENIED" in events


def test_shadow_unmapped_tool_allowed_with_diff(rig: Rig) -> None:
    _repo, mode, sink = rig
    mode[0] = "shadow"
    assert "isError" not in _call("tool_without_action", _key_ctx())
    call = sink.record_event.call_args_list[-1].kwargs
    assert call["payload_summary"]["unmapped_mcp_tool"] == "tool_without_action"


def test_enforce_not_onboarded_is_legacy(rig: Rig) -> None:
    _repo, mode, _sink = rig
    mode[0] = "enforce"
    assert "isError" not in _call("mail_approve_pm_task", _key_ctx())
    assert "isError" not in _call("tool_without_action", _key_ctx())


def test_key_does_not_inherit_human_grants(rig: Rig) -> None:
    repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "USER", PHONE, "mail_organizer", "project_lead")  # a human holds the bundle
    assert _is_forbidden(_call("mail_approve_pm_task", _key_ctx(principal=PHONE)))


def test_enforce_repository_failure_denies_unmapped(rig: Rig) -> None:
    _repo, _mode, sink = rig
    registry = deps.get_registry()
    broken = MagicMock()
    broken.count_active_bindings.side_effect = RuntimeError("db down")
    gate = EntitlementGate(
        EntitlementEvaluator(broken, registry), broken, EntitlementAuditor(sink), registry, lambda: "enforce"
    )
    deps.set_gate(gate)
    assert _is_forbidden(_call("tool_without_action", _key_ctx()))
