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

"""Unit tests for the entitlement evaluator (Plan 10, T11)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import pytest
from sqlalchemy import create_engine

from core_platform.app.auth.models import SecurityContext
from core_platform.app.entitlements.contracts import DecisionReason, ResourceRef
from core_platform.app.entitlements.evaluator import EntitlementEvaluator
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository

T1 = "tenant_a"
T2 = "tenant_b"
ACT = "demo:item:view"
DIGEST = "d" * 64
PHONE = "+10000000001"


def _payload() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "namespace": "demo",
        "app_title": "Demo Widget Tracker",
        "actions": [
            {
                "action_id": ACT,
                "plain_title": "View the item list",
                "plain_description": "Lets the person look at the list of items.",
                "effect": "READ",
                "risk": "LOW",
            }
        ],
        "bundles": [
            {
                "bundle_id": "viewer",
                "title": "Viewer",
                "summary": "Can look at items but not change anything at all.",
                "who_its_for": "Anyone who only needs to look",
                "allowed_scopes": ["SELF", "UNIT", "TENANT"],
                "default_scope": "SELF",
                "actions": [ACT],
            }
        ],
    }


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EntitlementRepository]:
    engine = create_engine(f"sqlite:///{tmp_path / 'ev.db'}")
    yield EntitlementRepository(engine=engine)
    engine.dispose()


@pytest.fixture
def ev(repo: EntitlementRepository) -> EntitlementEvaluator:
    reg = EntitlementRegistry()
    assert reg.register_raw("app_x", _payload())
    return EntitlementEvaluator(repo, reg)


def _ctx(tenant: str = T1, principal: str = PHONE, strategy: str = "phone_biometric",
         auth: bool = True) -> SecurityContext:
    return SecurityContext(principal_id=principal, tenant_id=tenant,
                           auth_strategy=strategy, is_authenticated=auth)


def _grant(repo: EntitlementRepository, tenant: str = T1, kind: str = "USER",
           scope: Scope = Scope.TENANT, unit: Optional[str] = None, bundle: str = "viewer",
           principal: str = PHONE, gname: str = "g") -> str:
    g = repo.create_group(tenant, gname, None, kind)
    repo.add_member(tenant, g.id, principal)
    return repo.create_binding(tenant, g.id, "app_x", bundle, scope, unit, DIGEST, "admin").id


def test_unauthenticated_denied(ev: EntitlementEvaluator) -> None:
    d = ev.evaluate(_ctx(auth=False), ACT)
    assert not d.allowed and d.reason == DecisionReason.UNAUTHENTICATED


def test_unknown_action_denied(ev: EntitlementEvaluator) -> None:
    d = ev.evaluate(_ctx(), "demo:nope:do")
    assert d.reason == DecisionReason.UNKNOWN_ACTION


def test_no_groups_denied(ev: EntitlementEvaluator) -> None:
    assert ev.evaluate(_ctx(), ACT).reason == DecisionReason.NO_MATCHING_BINDING


def test_group_without_binding_denied(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    g = repo.create_group(T1, "empty", None, "USER")
    repo.add_member(T1, g.id, PHONE)
    assert ev.evaluate(_ctx(), ACT).reason == DecisionReason.NO_MATCHING_BINDING


def test_tenant_scope_allows_and_lists_binding(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    bid = _grant(repo)
    d = ev.evaluate(_ctx(), ACT)
    assert d.allowed and d.reason == DecisionReason.ALLOWED
    assert d.matched_binding_ids == [bid]


def test_self_scope(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    _grant(repo, scope=Scope.SELF)
    assert ev.evaluate(_ctx(), ACT, ResourceRef(owner_principal_id=PHONE)).allowed
    other = ev.evaluate(_ctx(), ACT, ResourceRef(owner_principal_id="+19999999999"))
    assert not other.allowed and other.reason == DecisionReason.SCOPE_MISMATCH
    assert not ev.evaluate(_ctx(), ACT, None).allowed


def test_unit_scope_subtree(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    root = repo.create_unit(T1, "Root", "Site", None)
    child = repo.create_unit(T1, "Child", "Ward", root.id)
    grand = repo.create_unit(T1, "Grand", "Bay", child.id)
    sibling = repo.create_unit(T1, "Sibling", "Ward", root.id)
    _grant(repo, scope=Scope.UNIT, unit=child.id)
    for allowed_unit in (child.id, grand.id):
        assert ev.evaluate(_ctx(), ACT, ResourceRef(unit_id=allowed_unit)).allowed
    assert not ev.evaluate(_ctx(), ACT, ResourceRef(unit_id=sibling.id)).allowed
    assert not ev.evaluate(_ctx(), ACT, ResourceRef(unit_id=root.id)).allowed
    assert not ev.evaluate(_ctx(), ACT, ResourceRef(unit_id=None)).allowed
    assert not ev.evaluate(_ctx(), ACT, None).allowed


def test_unit_allow_at_root(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    root = repo.create_unit(T1, "Root", "Site", None)
    _grant(repo, scope=Scope.UNIT, unit=root.id)
    assert ev.evaluate(_ctx(), ACT, ResourceRef(unit_id=root.id)).allowed


def test_service_and_user_groups_are_separate(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    _grant(repo, kind="SERVICE", principal="shared-id", gname="svc")
    api = _ctx(principal="shared-id", strategy="api_key")
    human = _ctx(principal="shared-id")
    assert ev.evaluate(api, ACT).allowed
    assert not ev.evaluate(human, ACT).allowed
    # and the reverse: a USER group never serves an API key
    _grant(repo, kind="USER", principal="other-id", gname="usr")
    assert ev.evaluate(_ctx(principal="other-id"), ACT).allowed
    assert not ev.evaluate(_ctx(principal="other-id", strategy="api_key"), ACT).allowed


def test_binding_for_missing_bundle_ignored(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    _grant(repo, bundle="removed_bundle")
    assert ev.evaluate(_ctx(), ACT).reason == DecisionReason.NO_MATCHING_BINDING


def test_revoked_binding_ignored(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    bid = _grant(repo)
    assert ev.evaluate(_ctx(), ACT).allowed
    repo.revoke_binding(T1, bid, "admin")
    assert not ev.evaluate(_ctx(), ACT).allowed


def test_union_of_two_groups(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    _grant(repo, scope=Scope.SELF, gname="g1")
    tenant_bid = _grant(repo, scope=Scope.TENANT, gname="g2")
    d = ev.evaluate(_ctx(), ACT, ResourceRef(owner_principal_id="+19999999999"))
    assert d.allowed and d.matched_binding_ids == [tenant_bid]


def test_cross_tenant_isolation(ev: EntitlementEvaluator, repo: EntitlementRepository) -> None:
    _grant(repo, tenant=T1)
    assert ev.evaluate(_ctx(tenant=T1), ACT).allowed
    assert not ev.evaluate(_ctx(tenant=T2), ACT).allowed
