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

"""Unit tests for the tenant-scoped entitlement repository (Plan 10, T08)."""

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine

from core_platform.app.config import settings
from core_platform.app.entitlements.models import Scope
from core_platform.app.entitlements.repository import EntitlementRepository

A = "tenant_a"
B = "tenant_b"
DIGEST = "d" * 64


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EntitlementRepository]:
    engine = create_engine(f"sqlite:///{tmp_path / 'ent.db'}")
    yield EntitlementRepository(engine=engine)
    engine.dispose()


def _bind(repo: EntitlementRepository, tenant: str, group_id: str, scope: Scope = Scope.TENANT,
          unit: str | None = None, bundle: str = "viewer") -> str:
    return repo.create_binding(tenant, group_id, "app_x", bundle, scope, unit, DIGEST, "admin1").id


# -- clean slate -------------------------------------------------------------------------

def test_empty_database_returns_empty_results(repo: EntitlementRepository) -> None:
    assert repo.list_units(A) == []
    assert repo.list_groups(A) == []
    assert repo.list_active_bindings(A) == []
    assert repo.count_active_bindings(A) == 0
    assert repo.group_ids_for_principal(A, "+10000000001", "USER") == []
    assert repo.active_bindings_for_groups(A, []) == []


# -- units ---------------------------------------------------------------------------------

def test_unit_crud_and_validation(repo: EntitlementRepository) -> None:
    root = repo.create_unit(A, "Main Campus", "Campus", None)
    child = repo.create_unit(A, "Cardiology", "Ward", root.id)
    assert child.parent_id == root.id
    assert [u.name for u in repo.list_units(A)] == ["Cardiology", "Main Campus"]
    with pytest.raises(ValueError, match="UNIT_NAME_REQUIRED"):
        repo.create_unit(A, "  ", "x", None)
    with pytest.raises(ValueError, match="PARENT_NOT_FOUND"):
        repo.create_unit(A, "Orphan", "x", "does-not-exist")


def test_parent_from_other_tenant_rejected(repo: EntitlementRepository) -> None:
    other = repo.create_unit(B, "Their Root", "Root", None)
    with pytest.raises(ValueError, match="PARENT_NOT_FOUND"):
        repo.create_unit(A, "Mine", "x", other.id)


def test_subtree_membership(repo: EntitlementRepository) -> None:
    root = repo.create_unit(A, "Root", "R", None)
    child = repo.create_unit(A, "Child", "C", root.id)
    grand = repo.create_unit(A, "Grand", "G", child.id)
    sibling = repo.create_unit(A, "Sibling", "S", root.id)
    assert repo.unit_in_subtree(A, root.id, root.id) is True
    assert repo.unit_in_subtree(A, root.id, child.id) is True
    assert repo.unit_in_subtree(A, root.id, grand.id) is True
    assert repo.unit_in_subtree(A, child.id, sibling.id) is False
    assert repo.unit_in_subtree(A, grand.id, root.id) is False
    assert repo.unit_in_subtree(A, root.id, "missing") is False


def test_subtree_is_tenant_scoped(repo: EntitlementRepository) -> None:
    root = repo.create_unit(A, "Root", "R", None)
    child = repo.create_unit(A, "Child", "C", root.id)
    assert repo.unit_in_subtree(B, root.id, child.id) is False


def test_depth_limit_enforced(repo: EntitlementRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENTITLEMENT_MAX_UNIT_DEPTH", 3)
    u1 = repo.create_unit(A, "L1", "x", None)
    u2 = repo.create_unit(A, "L2", "x", u1.id)
    u3 = repo.create_unit(A, "L3", "x", u2.id)
    with pytest.raises(ValueError, match="UNIT_DEPTH_EXCEEDED"):
        repo.create_unit(A, "L4", "x", u3.id)
    assert repo.unit_in_subtree(A, u1.id, u3.id) is True


def test_subtree_false_when_walk_exceeds_depth(repo: EntitlementRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    u1 = repo.create_unit(A, "L1", "x", None)
    u2 = repo.create_unit(A, "L2", "x", u1.id)
    u3 = repo.create_unit(A, "L3", "x", u2.id)
    monkeypatch.setattr(settings, "ENTITLEMENT_MAX_UNIT_DEPTH", 2)
    assert repo.unit_in_subtree(A, u1.id, u3.id) is False


def test_move_unit_rejects_cycles(repo: EntitlementRepository) -> None:
    root = repo.create_unit(A, "Root", "R", None)
    child = repo.create_unit(A, "Child", "C", root.id)
    grand = repo.create_unit(A, "Grand", "G", child.id)
    with pytest.raises(ValueError, match="UNIT_CYCLE_DETECTED"):
        repo.move_unit(A, root.id, grand.id)
    with pytest.raises(ValueError, match="UNIT_CYCLE_DETECTED"):
        repo.move_unit(A, child.id, child.id)
    moved = repo.move_unit(A, grand.id, root.id)
    assert moved.parent_id == root.id
    with pytest.raises(ValueError, match="UNIT_NOT_FOUND"):
        repo.move_unit(A, "ghost", None)
    with pytest.raises(ValueError, match="PARENT_NOT_FOUND"):
        repo.move_unit(A, grand.id, "ghost")


# -- groups & members ----------------------------------------------------------------------

def test_group_and_member_lifecycle(repo: EntitlementRepository) -> None:
    g = repo.create_group(A, "Nurses", "Floor nurses", "USER")
    assert repo.get_group(A, g.id) is not None
    m1 = repo.add_member(A, g.id, "+10000000001")
    m2 = repo.add_member(A, g.id, "+10000000001")
    assert m1.id == m2.id  # idempotent
    assert [m.principal_id for m in repo.list_members(A, g.id)] == ["+10000000001"]
    assert repo.remove_member(A, g.id, "+10000000001") is True
    assert repo.remove_member(A, g.id, "+10000000001") is False


def test_group_validation(repo: EntitlementRepository) -> None:
    repo.create_group(A, "Nurses", None, "USER")
    with pytest.raises(ValueError, match="GROUP_NAME_EXISTS"):
        repo.create_group(A, "Nurses", None, "USER")
    with pytest.raises(ValueError, match="GROUP_NAME_REQUIRED"):
        repo.create_group(A, " ", None, "USER")
    with pytest.raises(ValueError, match="GROUP_KIND_INVALID"):
        repo.create_group(A, "Bots", None, "ROBOT")
    repo.create_group(B, "Nurses", None, "USER")  # same name, other tenant is fine


def test_add_member_validation(repo: EntitlementRepository) -> None:
    g = repo.create_group(A, "Nurses", None, "USER")
    with pytest.raises(ValueError, match="PRINCIPAL_REQUIRED"):
        repo.add_member(A, g.id, " ")
    with pytest.raises(ValueError, match="GROUP_NOT_FOUND"):
        repo.add_member(B, g.id, "+10000000001")  # group belongs to tenant A


def test_group_ids_for_principal_separates_kinds(repo: EntitlementRepository) -> None:
    users = repo.create_group(A, "People", None, "USER")
    bots = repo.create_group(A, "Assistants", None, "SERVICE")
    same_id = "+10000000001"
    repo.add_member(A, users.id, same_id)
    repo.add_member(A, bots.id, same_id)
    assert repo.group_ids_for_principal(A, same_id, "USER") == [users.id]
    assert repo.group_ids_for_principal(A, same_id, "SERVICE") == [bots.id]


def test_group_ids_for_principal_is_tenant_scoped(repo: EntitlementRepository) -> None:
    g = repo.create_group(A, "People", None, "USER")
    repo.add_member(A, g.id, "+10000000001")
    assert repo.group_ids_for_principal(B, "+10000000001", "USER") == []


# -- bindings --------------------------------------------------------------------------------

def test_binding_lifecycle_and_duplicate_rules(repo: EntitlementRepository) -> None:
    g = repo.create_group(A, "People", None, "USER")
    first = _bind(repo, A, g.id)
    assert repo.count_active_bindings(A) == 1
    with pytest.raises(ValueError, match="BINDING_ALREADY_EXISTS"):
        _bind(repo, A, g.id)
    assert repo.revoke_binding(A, first, "admin2") is True
    assert repo.revoke_binding(A, first, "admin2") is False
    assert repo.count_active_bindings(A) == 0
    second = _bind(repo, A, g.id)  # allowed again after revoke
    assert second != first
    assert repo.get_binding(A, first) is not None
    assert repo.get_binding(A, first).revoked_at is not None  # type: ignore[union-attr]


def test_unit_scope_rules(repo: EntitlementRepository) -> None:
    g = repo.create_group(A, "People", None, "USER")
    unit = repo.create_unit(A, "Ward", "Ward", None)
    with pytest.raises(ValueError, match="SCOPE_UNIT_REQUIRED"):
        _bind(repo, A, g.id, Scope.UNIT, None)
    with pytest.raises(ValueError, match="SCOPE_UNIT_NOT_FOUND"):
        _bind(repo, A, g.id, Scope.UNIT, "ghost")
    with pytest.raises(ValueError, match="SCOPE_UNIT_NOT_ALLOWED"):
        _bind(repo, A, g.id, Scope.TENANT, unit.id)
    ok = repo.get_binding(A, _bind(repo, A, g.id, Scope.UNIT, unit.id))
    assert ok is not None and ok.scope == Scope.UNIT and ok.scope_unit_id == unit.id


def test_binding_with_unit_from_other_tenant_rejected(repo: EntitlementRepository) -> None:
    g = repo.create_group(A, "People", None, "USER")
    foreign_unit = repo.create_unit(B, "Their Ward", "Ward", None)
    with pytest.raises(ValueError, match="SCOPE_UNIT_NOT_FOUND"):
        _bind(repo, A, g.id, Scope.UNIT, foreign_unit.id)


def test_binding_with_group_from_other_tenant_rejected(repo: EntitlementRepository) -> None:
    foreign_group = repo.create_group(B, "Theirs", None, "USER")
    with pytest.raises(ValueError, match="GROUP_NOT_FOUND"):
        _bind(repo, A, foreign_group.id)


def test_active_bindings_for_groups_excludes_revoked_and_foreign(repo: EntitlementRepository) -> None:
    ga = repo.create_group(A, "People", None, "USER")
    gb = repo.create_group(B, "People", None, "USER")
    keep = _bind(repo, A, ga.id, bundle="viewer")
    gone = _bind(repo, A, ga.id, bundle="approver")
    _bind(repo, B, gb.id, bundle="viewer")
    repo.revoke_binding(A, gone, "admin")
    found = repo.active_bindings_for_groups(A, [ga.id, gb.id])
    assert [b.id for b in found] == [keep]
    assert [b.id for b in repo.bindings_for_group(A, ga.id)] == [keep]
    assert repo.count_active_bindings(B) == 1


def test_cross_tenant_binding_reads_and_revokes_blocked(repo: EntitlementRepository) -> None:
    ga = repo.create_group(A, "People", None, "USER")
    binding_id = _bind(repo, A, ga.id)
    assert repo.get_binding(B, binding_id) is None
    assert repo.revoke_binding(B, binding_id, "attacker") is False
    assert repo.count_active_bindings(A) == 1
    assert repo.get_group(B, ga.id) is None
    assert repo.list_groups(B) == []
    assert repo.list_active_bindings(B) == []
