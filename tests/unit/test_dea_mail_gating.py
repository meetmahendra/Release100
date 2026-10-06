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

"""Gating tests for mail_organizer routes under each rollout mode (Plan 10, T19)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, List, Tuple
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.entitlements import dependencies as deps
from core_platform.app.entitlements.audit import EntitlementAuditor
from core_platform.app.entitlements.evaluator import EntitlementEvaluator
from core_platform.app.entitlements.gate import EntitlementGate
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository
from core_platform.main import app

MANIFEST = Path(__file__).resolve().parents[2] / "apps" / "mail_organizer" / "entitlements.json"
TENANT = "tenant_gate"
PHONE = "+10000000077"
REJECT = "/admin/apps/mail-organizer/api/pm-tasks/987654/reject"
RULES = "/admin/apps/mail-organizer/rules"

Rig = Tuple[TestClient, EntitlementRepository, List[str], MagicMock]


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    engine = create_engine(f"sqlite:///{tmp_path / 'gate_mail.db'}")
    repo = EntitlementRepository(engine=engine)
    registry = EntitlementRegistry()
    assert registry.register_raw("mail_organizer", json.loads(MANIFEST.read_text(encoding="utf-8")))
    mode: List[str] = ["shadow"]
    sink = MagicMock()
    gate = EntitlementGate(
        EntitlementEvaluator(repo, registry), repo, EntitlementAuditor(sink), registry, lambda: mode[0]
    )
    previous = deps._gate
    deps.set_gate(gate)
    client = TestClient(app)
    token = create_jwt_token(PHONE, ["admin"], ["all", "mail_organizer"], tenant_id=TENANT)
    client.cookies.set("admin_token", token)
    yield client, repo, mode, sink
    deps.set_gate(previous)
    engine.dispose()


def _grant(repo: EntitlementRepository, bundle: str, principal: str = PHONE) -> None:
    g = repo.create_group(TENANT, f"g_{bundle}_{principal}", None, "USER")
    repo.add_member(TENANT, g.id, principal)
    repo.create_binding(TENANT, g.id, "mail_organizer", bundle, Scope.TENANT, None, "d" * 64, "admin")


@pytest.mark.parametrize("mode_name", ["off", "shadow"])
def test_off_and_shadow_do_not_change_behaviour(rig: Rig, mode_name: str) -> None:
    client, _repo, mode, _sink = rig
    mode[0] = mode_name
    assert client.get(RULES).status_code == 200
    assert client.post(REJECT).status_code == 404  # reaches the handler: task does not exist


def test_shadow_audits_disagreement(rig: Rig) -> None:
    client, _repo, mode, sink = rig
    mode[0] = "shadow"
    client.post(REJECT)
    events = [c.kwargs["action_type"] for c in sink.record_event.call_args_list]
    assert "ENTITLEMENT_SHADOW_DIFF" in events


def test_enforce_onboarded_without_binding_is_forbidden(rig: Rig) -> None:
    client, repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "inbox_user", principal="+19990000001")  # tenant onboarded, but not for PHONE
    assert client.post(REJECT).status_code == 403
    assert client.get(RULES).status_code == 403


def test_enforce_with_project_lead_binding_passes_gate(rig: Rig) -> None:
    client, repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "project_lead")
    assert client.post(REJECT).status_code == 404  # gate passed; handler: task not found
    assert client.get(RULES).status_code == 200


def test_enforce_inbox_user_cannot_reject(rig: Rig) -> None:
    client, repo, mode, _sink = rig
    mode[0] = "enforce"
    _grant(repo, "inbox_user")
    assert client.get(RULES).status_code == 200
    assert client.post(REJECT).status_code == 403


def test_enforce_not_onboarded_uses_legacy(rig: Rig) -> None:
    client, _repo, mode, _sink = rig
    mode[0] = "enforce"
    assert client.get(RULES).status_code == 200
    assert client.post(REJECT).status_code == 404
