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

"""Unit tests for the entitlement admin API (Plan 10, T16)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from core_platform.app.admin_shell import entitlements_routes as er
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.entitlements import dependencies as deps
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


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(er.settings, "ENABLED_APPLICATIONS", ["demo_app"])
    engine = create_engine(f"sqlite:///{tmp_path / 'routes.db'}")
    repo = EntitlementRepository(engine=engine)
    reg = EntitlementRegistry()
    assert reg.register_raw("demo_app", _payload())
    deps.set_repository(repo)
    deps.set_registry(reg)
    app = FastAPI()
    app.include_router(er.router)
    yield TestClient(app)
    deps.set_repository(None)
    deps.set_registry(None)
    engine.dispose()


def _cookies(tenant: str = "tenant_a", role: str = "admin") -> Dict[str, str]:
    token = create_jwt_token(
        principal_id=f"{role}_{tenant}", roles=[role], permitted_apps=["demo_app"], tenant_id=tenant
    )
    return {"admin_token": token}


def test_401_without_auth(api: TestClient) -> None:
    assert api.get("/admin/entitlements/api/catalog").status_code == 401


def test_403_for_non_admin(api: TestClient) -> None:
    r = api.get("/admin/entitlements/api/catalog", cookies=_cookies(role="operator"))
    assert r.status_code == 403


def test_catalog_returns_cards(api: TestClient) -> None:
    r = api.get("/admin/entitlements/api/catalog", cookies=_cookies())
    assert r.status_code == 200
    assert {c["bundle_id"] for c in r.json()} == {"viewer", "eraser"}
    eraser = next(c for c in r.json() if c["bundle_id"] == "eraser")
    assert eraser["risk_label"] == "High governance"


def test_clean_slate_lists_are_empty(api: TestClient) -> None:
    for path in ("units", "groups", "directory"):
        assert api.get(f"/admin/entitlements/api/{path}", cookies=_cookies()).status_code == 200
    assert api.get("/admin/entitlements/api/groups", cookies=_cookies()).json() == []


def test_happy_path_and_effective_access(api: TestClient) -> None:
    c = _cookies()
    base = "/admin/entitlements/api"
    unit = api.post(f"{base}/units", json={"name": "Cardiology", "label": "Ward"}, cookies=c)
    assert unit.status_code == 200
    group = api.post(f"{base}/groups", json={"name": "Nurses", "kind": "USER"}, cookies=c).json()
    assert api.post(f"{base}/groups/{group['id']}/members",
                    json={"principal_id": "+10000000001"}, cookies=c).status_code == 200
    bind = api.post(f"{base}/bindings", cookies=c, json={
        "group_id": group["id"], "app_id": "demo_app", "bundle_id": "viewer",
        "scope": "UNIT", "scope_unit_id": unit.json()["id"]})
    assert bind.status_code == 200
    eff = api.get(f"{base}/effective-access", params={"principal_id": "+10000000001"}, cookies=c)
    assert [r["action_id"] for r in eff.json()] == [LOW]
    assert eff.json()[0]["scope_unit_name"] == "Cardiology"
    listing = api.get(f"{base}/groups", cookies=c).json()
    assert listing[0]["members"] == ["+10000000001"] and len(listing[0]["bindings"]) == 1
    assert api.post(f"{base}/bindings/{bind.json()['id']}/revoke", cookies=c).json() == {"revoked": True}
    assert api.delete(f"{base}/groups/{group['id']}/members/+10000000001", cookies=c).json() == {"removed": True}


def test_high_risk_requires_confirmation(api: TestClient) -> None:
    c = _cookies()
    base = "/admin/entitlements/api"
    g = api.post(f"{base}/groups", json={"name": "Admins"}, cookies=c).json()
    body = {"group_id": g["id"], "app_id": "demo_app", "bundle_id": "eraser", "scope": "TENANT"}
    r = api.post(f"{base}/bindings", json=body, cookies=c)
    assert r.status_code == 400 and r.json()["detail"] == {"code": "HIGH_RISK_CONFIRMATION_REQUIRED"}
    assert api.post(f"{base}/bindings", json={**body, "confirm_high_risk": True}, cookies=c).status_code == 200


def test_service_group_high_risk_rejected(api: TestClient) -> None:
    c = _cookies()
    base = "/admin/entitlements/api"
    g = api.post(f"{base}/groups", json={"name": "Bots", "kind": "SERVICE"}, cookies=c).json()
    r = api.post(f"{base}/bindings", cookies=c, json={
        "group_id": g["id"], "app_id": "demo_app", "bundle_id": "eraser",
        "scope": "TENANT", "confirm_high_risk": True})
    assert r.json()["detail"] == {"code": "SERVICE_GROUP_CANNOT_HOLD_HIGH_RISK"}


def test_tenant_isolation(api: TestClient) -> None:
    base = "/admin/entitlements/api"
    g = api.post(f"{base}/groups", json={"name": "Nurses"}, cookies=_cookies("tenant_a")).json()
    assert api.get(f"{base}/groups", cookies=_cookies("tenant_b")).json() == []
    r = api.post(f"{base}/bindings", cookies=_cookies("tenant_b"), json={
        "group_id": g["id"], "app_id": "demo_app", "bundle_id": "viewer", "scope": "TENANT"})
    assert r.status_code == 400 and r.json()["detail"] == {"code": "GROUP_NOT_FOUND"}


def test_invalid_group_kind_rejected(api: TestClient) -> None:
    r = api.post("/admin/entitlements/api/groups", json={"name": "x", "kind": "ROBOT"}, cookies=_cookies())
    assert r.status_code == 422


def test_csrf_mismatch_rejected(api: TestClient) -> None:
    c = {**_cookies(), "csrf_token": "abc"}
    r = api.post("/admin/entitlements/api/groups", json={"name": "x"}, cookies=c)
    assert r.status_code == 403
    ok = api.post("/admin/entitlements/api/groups", json={"name": "x"}, cookies=c,
                  headers={"X-CSRF-Token": "abc"})
    assert ok.status_code == 200


def test_startup_audits_rejected_and_drift(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'su.db'}")
    repo = EntitlementRepository(engine=engine)
    reg = EntitlementRegistry()
    assert reg.register_raw("demo_app", _payload())
    assert reg.register_raw("bad_app", {"nope": 1}) is False
    g = repo.create_group("t", "g", None, "USER")
    repo.create_binding("t", g.id, "demo_app", "viewer", Scope.TENANT, None, "0" * 64, "a")
    repo.create_binding("t", g.id, "demo_app", "gone", Scope.TENANT, None, "0" * 64, "a")
    sink = MagicMock()
    er.emit_startup_audits(reg, repo, EntitlementAuditor(sink))
    events: List[str] = [x.kwargs["action_type"] for x in sink.record_event.call_args_list]
    assert events.count("ENTITLEMENT_MANIFEST_REJECTED") == 1
    assert events.count("ENTITLEMENT_BUNDLE_DRIFT") == 1
    engine.dispose()


def test_startup_audit_empty_is_silent_and_never_raises() -> None:
    broken = MagicMock()
    broken.all_active_bindings.side_effect = RuntimeError("db")
    sink = MagicMock()
    er.emit_startup_audits(EntitlementRegistry(), broken, EntitlementAuditor(sink))
    assert sink.record_event.call_count == 0
