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

"""Unit tests for the entitlement admin service (Plan 10, T14)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements.admin_service import EntitlementAdminService
from core_platform.app.entitlements.audit import EntitlementAuditor
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository

LOW = "demo:item:view"
HIGH = "demo:item:erase"


def _payload() -> Dict[str, Any]:
    return {
        "schema_version": 1, "namespace": "demo", "app_title": "Demo Widget Tracker",
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
             "allowed_scopes": ["SELF", "UNIT", "TENANT"], "default_scope": "SELF",
             "actions": [LOW]},
            {"bundle_id": "eraser", "title": "Eraser",
             "summary": "Can erase item records, which cannot be undone.",
             "who_its_for": "Trusted administrators only", "cannot_do": ["Cannot view reports"],
             "allowed_scopes": ["TENANT"], "default_scope": "TENANT", "actions": [HIGH]},
        ],
    }


def _ctx(tenant: str = "ta", who: str = "admin1") -> SecurityContext:
    return SecurityContext(principal_id=who, tenant_id=tenant,
                           auth_strategy="local_jwt", is_authenticated=True)


class _Env:
    def __init__(self, repo: EntitlementRepository) -> None:
        self.repo = repo
        self.engine = MagicMock()
        reg = EntitlementRegistry()
        assert reg.register_raw("app_x", _payload())
        self.svc = EntitlementAdminService(repo, reg, EntitlementAuditor(self.engine))

    def events(self) -> list[str]:
        return [c.kwargs["action_type"] for c in self.engine.record_event.call_args_list]


@pytest.fixture
def env(tmp_path: Path) -> Iterator[_Env]:
    engine = create_engine(f"sqlite:///{tmp_path / 'adm.db'}")
    yield _Env(EntitlementRepository(engine=engine))
    engine.dispose()


def test_group_member_flow_audited(env: _Env) -> None:
    g = env.svc.create_group(_ctx(), "Nurses", None, "USER")
    env.svc.add_member(_ctx(), g.id, "+10000000001")
    assert env.svc.remove_member(_ctx(), g.id, "+10000000001") is True
    assert env.svc.remove_member(_ctx(), g.id, "+10000000001") is False
    assert env.events() == ["ENTITLEMENT_GROUP_CHANGED"] * 3


def test_bind_validations(env: _Env) -> None:
    g = env.svc.create_group(_ctx(), "Nurses", None, "USER")
    with pytest.raises(ValueError, match="GROUP_NOT_FOUND"):
        env.svc.bind_bundle(_ctx(), "nope", "app_x", "viewer", Scope.TENANT, None, False)
    with pytest.raises(ValueError, match="UNKNOWN_BUNDLE"):
        env.svc.bind_bundle(_ctx(), g.id, "app_x", "ghost", Scope.TENANT, None, False)
    with pytest.raises(ValueError, match="UNKNOWN_BUNDLE"):
        env.svc.bind_bundle(_ctx(), g.id, "no_app", "viewer", Scope.TENANT, None, False)
    with pytest.raises(ValueError, match="SCOPE_NOT_ALLOWED"):
        env.svc.bind_bundle(_ctx(), g.id, "app_x", "eraser", Scope.SELF, None, True)
    with pytest.raises(ValueError, match="HIGH_RISK_CONFIRMATION_REQUIRED"):
        env.svc.bind_bundle(_ctx(), g.id, "app_x", "eraser", Scope.TENANT, None, False)


def test_high_confirm_flow_and_audit(env: _Env) -> None:
    g = env.svc.create_group(_ctx(), "Admins", None, "USER")
    b = env.svc.bind_bundle(_ctx(), g.id, "app_x", "eraser", Scope.TENANT, None, True)
    assert b.granted_by == "admin1" and len(b.bundle_digest) == 64
    call = env.engine.record_event.call_args_list[-1].kwargs
    assert call["action_type"] == "ENTITLEMENT_BINDING_CREATED"
    assert call["payload_summary"]["risk"] == "HIGH"
    assert call["payload_summary"]["digest"] == b.bundle_digest
    assert env.svc.unbind(_ctx(), b.id) is True
    assert env.svc.unbind(_ctx(), b.id) is False
    assert env.events()[-1] == "ENTITLEMENT_BINDING_REVOKED"


def test_service_group_never_holds_high_even_confirmed(env: _Env) -> None:
    g = env.svc.create_group(_ctx(), "Bots", None, "SERVICE")
    with pytest.raises(ValueError, match="SERVICE_GROUP_CANNOT_HOLD_HIGH_RISK"):
        env.svc.bind_bundle(_ctx(), g.id, "app_x", "eraser", Scope.TENANT, None, True)
    env.svc.bind_bundle(_ctx(), g.id, "app_x", "viewer", Scope.TENANT, None, False)


def test_effective_access_union_and_labels(env: _Env) -> None:
    unit = env.svc.create_unit(_ctx(), "Cardiology", "Ward", None)
    g1 = env.svc.create_group(_ctx(), "Nurses", None, "USER")
    g2 = env.svc.create_group(_ctx(), "Leads", None, "USER")
    for g in (g1, g2):
        env.svc.add_member(_ctx(), g.id, "+10000000001")
    env.svc.bind_bundle(_ctx(), g1.id, "app_x", "viewer", Scope.UNIT, unit.id, False)
    env.svc.bind_bundle(_ctx(), g2.id, "app_x", "eraser", Scope.TENANT, None, True)
    rows = env.svc.effective_access(_ctx(), "+10000000001")
    by_action = {r.action_id: r for r in rows}
    assert set(by_action) == {LOW, HIGH}
    assert by_action[LOW].scope_unit_name == "Cardiology"
    assert by_action[LOW].via_group == "Nurses" and by_action[LOW].via_bundle == "Viewer"
    assert by_action[HIGH].app_title == "Demo Widget Tracker"
    assert env.svc.effective_access(_ctx(), "+19999999999") == []


def test_effective_access_skips_unknown_bundle(env: _Env) -> None:
    g = env.svc.create_group(_ctx(), "Old", None, "USER")
    env.svc.add_member(_ctx(), g.id, "+10000000002")
    env.repo.create_binding("ta", g.id, "app_x", "removed", Scope.TENANT, None, "d" * 64, "admin1")
    assert env.svc.effective_access(_ctx(), "+10000000002") == []


def test_tenant_isolation(env: _Env) -> None:
    g = env.svc.create_group(_ctx("ta"), "Nurses", None, "USER")
    with pytest.raises(ValueError, match="GROUP_NOT_FOUND"):
        env.svc.bind_bundle(_ctx("tb"), g.id, "app_x", "viewer", Scope.TENANT, None, False)
    with pytest.raises(ValueError):
        env.svc.add_member(_ctx("tb"), g.id, "+10000000001")
