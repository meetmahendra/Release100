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

"""Tenant-scoped persistence for the Decentralized Entitlement Architecture (Plan 10, T08).

Every public method takes ``tenant_id`` first and filters on it in every query, so
data from one tenant is never readable or writable through another tenant's calls.
All methods return immutable DTOs, never ORM objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from core_platform.app.config import settings
from core_platform.app.db.base import Base
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.entitlements.db_models import (
    BindingRow,
    GroupMemberRow,
    GroupRow,
    OrgUnitRow,
    entitlement_tables,
)
from core_platform.app.entitlements.models import Scope

GROUP_KINDS = ("USER", "SERVICE")


class UnitDTO(BaseModel):
    """Organizational unit."""

    model_config = ConfigDict(frozen=True)
    id: str
    tenant_id: str
    name: str
    label: str
    parent_id: Optional[str]


class GroupDTO(BaseModel):
    """Customer group."""

    model_config = ConfigDict(frozen=True)
    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    kind: str
    external_ref: Optional[str]


class MemberDTO(BaseModel):
    """Group membership."""

    model_config = ConfigDict(frozen=True)
    id: int
    tenant_id: str
    group_id: str
    principal_id: str


class BindingDTO(BaseModel):
    """Bundle grant to a group."""

    model_config = ConfigDict(frozen=True)
    id: str
    tenant_id: str
    group_id: str
    app_id: str
    bundle_id: str
    scope: Scope
    scope_unit_id: Optional[str]
    bundle_digest: str
    granted_by: str
    revoked_at: Optional[datetime]


def _unit_dto(row: OrgUnitRow) -> UnitDTO:
    return UnitDTO(id=row.id, tenant_id=row.tenant_id, name=row.name, label=row.label, parent_id=row.parent_id)


def _group_dto(row: GroupRow) -> GroupDTO:
    return GroupDTO(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        kind=row.kind,
        external_ref=row.external_ref,
    )


def _member_dto(row: GroupMemberRow) -> MemberDTO:
    return MemberDTO(id=row.id, tenant_id=row.tenant_id, group_id=row.group_id, principal_id=row.principal_id)


def _binding_dto(row: BindingRow) -> BindingDTO:
    return BindingDTO(
        id=row.id,
        tenant_id=row.tenant_id,
        group_id=row.group_id,
        app_id=row.app_id,
        bundle_id=row.bundle_id,
        scope=Scope(row.scope),
        scope_unit_id=row.scope_unit_id,
        bundle_digest=row.bundle_digest,
        granted_by=row.granted_by,
        revoked_at=row.revoked_at,
    )


class EntitlementRepository:
    """Tenant-scoped CRUD over units, groups, memberships and bindings."""

    def __init__(self, engine: Optional[Engine] = None) -> None:
        """Bind to ``engine`` (or the platform engine) and create only the entitlement tables."""
        self._engine: Engine = engine if engine is not None else DatabaseManager.get_instance().get_engine()
        self._session_factory: sessionmaker[Session] = sessionmaker(bind=self._engine, expire_on_commit=False)
        Base.metadata.create_all(bind=self._engine, tables=entitlement_tables())

    # -- org units -----------------------------------------------------------------

    def _parent_map(self, session: Session, tenant_id: str) -> Dict[str, Optional[str]]:
        rows = session.execute(
            select(OrgUnitRow.id, OrgUnitRow.parent_id).where(OrgUnitRow.tenant_id == tenant_id)
        ).all()
        return {r[0]: r[1] for r in rows}

    def _depth_of(self, parent_map: Dict[str, Optional[str]], unit_id: Optional[str]) -> int:
        """Number of nodes on the path from ``unit_id`` to its root (0 for None)."""
        depth = 0
        current = unit_id
        seen: set[str] = set()
        while current is not None and current in parent_map:
            if current in seen:
                raise ValueError("UNIT_CYCLE_DETECTED")
            seen.add(current)
            depth += 1
            current = parent_map[current]
        return depth

    def create_unit(self, tenant_id: str, name: str, label: str, parent_id: Optional[str]) -> UnitDTO:
        """Create a unit under ``parent_id`` (same tenant) and return it.

        Raises:
            ValueError: ``UNIT_NAME_REQUIRED``, ``PARENT_NOT_FOUND`` or ``UNIT_DEPTH_EXCEEDED``.
        """
        if not name.strip():
            raise ValueError("UNIT_NAME_REQUIRED")
        with self._session_factory() as session:
            parent_map = self._parent_map(session, tenant_id)
            if parent_id is not None and parent_id not in parent_map:
                raise ValueError("PARENT_NOT_FOUND")
            if self._depth_of(parent_map, parent_id) + 1 > settings.ENTITLEMENT_MAX_UNIT_DEPTH:
                raise ValueError("UNIT_DEPTH_EXCEEDED")
            row = OrgUnitRow(tenant_id=tenant_id, name=name.strip(), label=label.strip(), parent_id=parent_id)
            session.add(row)
            session.commit()
            return _unit_dto(row)

    def move_unit(self, tenant_id: str, unit_id: str, new_parent_id: Optional[str]) -> UnitDTO:
        """Re-parent a unit, rejecting cycles and depth overflow.

        Raises:
            ValueError: ``UNIT_NOT_FOUND``, ``PARENT_NOT_FOUND``, ``UNIT_CYCLE_DETECTED``
                or ``UNIT_DEPTH_EXCEEDED``.
        """
        with self._session_factory() as session:
            parent_map = self._parent_map(session, tenant_id)
            if unit_id not in parent_map:
                raise ValueError("UNIT_NOT_FOUND")
            if new_parent_id is not None and new_parent_id not in parent_map:
                raise ValueError("PARENT_NOT_FOUND")
            cursor = new_parent_id
            hops = 0
            while cursor is not None and hops <= len(parent_map):
                if cursor == unit_id:
                    raise ValueError("UNIT_CYCLE_DETECTED")
                cursor = parent_map.get(cursor)
                hops += 1
            if self._depth_of(parent_map, new_parent_id) + 1 > settings.ENTITLEMENT_MAX_UNIT_DEPTH:
                raise ValueError("UNIT_DEPTH_EXCEEDED")
            row = session.scalars(
                select(OrgUnitRow).where(OrgUnitRow.tenant_id == tenant_id, OrgUnitRow.id == unit_id)
            ).one()
            row.parent_id = new_parent_id
            session.commit()
            return _unit_dto(row)

    def list_units(self, tenant_id: str) -> List[UnitDTO]:
        """Return all units of the tenant ordered by name."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(OrgUnitRow).where(OrgUnitRow.tenant_id == tenant_id).order_by(OrgUnitRow.name)
            ).all()
            return [_unit_dto(r) for r in rows]

    def unit_in_subtree(self, tenant_id: str, root: str, candidate: str) -> bool:
        """Return True if ``candidate`` equals ``root`` or is one of its descendants (same tenant)."""
        with self._session_factory() as session:
            parent_map = self._parent_map(session, tenant_id)
        if candidate not in parent_map or root not in parent_map:
            return False
        current: Optional[str] = candidate
        for _ in range(settings.ENTITLEMENT_MAX_UNIT_DEPTH):
            if current is None:
                return False
            if current == root:
                return True
            current = parent_map.get(current)
        return False

    # -- groups & members ------------------------------------------------------------

    def create_group(self, tenant_id: str, name: str, description: Optional[str], kind: str) -> GroupDTO:
        """Create a group.

        Raises:
            ValueError: ``GROUP_NAME_REQUIRED``, ``GROUP_KIND_INVALID`` or ``GROUP_NAME_EXISTS``.
        """
        if not name.strip():
            raise ValueError("GROUP_NAME_REQUIRED")
        if kind not in GROUP_KINDS:
            raise ValueError("GROUP_KIND_INVALID")
        with self._session_factory() as session:
            row = GroupRow(tenant_id=tenant_id, name=name.strip(), description=description, kind=kind)
            session.add(row)
            try:
                session.commit()
            except IntegrityError as err:
                session.rollback()
                raise ValueError("GROUP_NAME_EXISTS") from err
            return _group_dto(row)

    def get_group(self, tenant_id: str, group_id: str) -> Optional[GroupDTO]:
        """Return a group of the tenant or None."""
        with self._session_factory() as session:
            row = session.scalars(
                select(GroupRow).where(GroupRow.tenant_id == tenant_id, GroupRow.id == group_id)
            ).first()
            return _group_dto(row) if row is not None else None

    def list_groups(self, tenant_id: str) -> List[GroupDTO]:
        """Return all groups of the tenant ordered by name."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(GroupRow).where(GroupRow.tenant_id == tenant_id).order_by(GroupRow.name)
            ).all()
            return [_group_dto(r) for r in rows]

    def add_member(self, tenant_id: str, group_id: str, principal_id: str) -> MemberDTO:
        """Add a principal to a group (idempotent).

        Raises:
            ValueError: ``GROUP_NOT_FOUND`` or ``PRINCIPAL_REQUIRED``.
        """
        if not principal_id.strip():
            raise ValueError("PRINCIPAL_REQUIRED")
        with self._session_factory() as session:
            group = session.scalars(
                select(GroupRow).where(GroupRow.tenant_id == tenant_id, GroupRow.id == group_id)
            ).first()
            if group is None:
                raise ValueError("GROUP_NOT_FOUND")
            existing = session.scalars(
                select(GroupMemberRow).where(
                    GroupMemberRow.tenant_id == tenant_id,
                    GroupMemberRow.group_id == group_id,
                    GroupMemberRow.principal_id == principal_id.strip(),
                )
            ).first()
            if existing is not None:
                return _member_dto(existing)
            row = GroupMemberRow(tenant_id=tenant_id, group_id=group_id, principal_id=principal_id.strip())
            session.add(row)
            session.commit()
            return _member_dto(row)

    def remove_member(self, tenant_id: str, group_id: str, principal_id: str) -> bool:
        """Remove a principal from a group; True if a membership was deleted."""
        with self._session_factory() as session:
            row = session.scalars(
                select(GroupMemberRow).where(
                    GroupMemberRow.tenant_id == tenant_id,
                    GroupMemberRow.group_id == group_id,
                    GroupMemberRow.principal_id == principal_id,
                )
            ).first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def list_members(self, tenant_id: str, group_id: str) -> List[MemberDTO]:
        """Return members of a group within the tenant."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(GroupMemberRow)
                .where(GroupMemberRow.tenant_id == tenant_id, GroupMemberRow.group_id == group_id)
                .order_by(GroupMemberRow.principal_id)
            ).all()
            return [_member_dto(r) for r in rows]

    def group_ids_for_principal(self, tenant_id: str, principal_id: str, kind: str) -> List[str]:
        """Return ids of groups of the given ``kind`` that contain the principal (same tenant only)."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(GroupRow.id)
                .join(GroupMemberRow, GroupMemberRow.group_id == GroupRow.id)
                .where(
                    GroupRow.tenant_id == tenant_id,
                    GroupMemberRow.tenant_id == tenant_id,
                    GroupMemberRow.principal_id == principal_id,
                    GroupRow.kind == kind,
                )
            ).all()
            return list(rows)

    # -- bindings -----------------------------------------------------------------------

    def create_binding(
        self,
        tenant_id: str,
        group_id: str,
        app_id: str,
        bundle_id: str,
        scope: Scope,
        scope_unit_id: Optional[str],
        bundle_digest: str,
        granted_by: str,
    ) -> BindingDTO:
        """Grant a bundle to a group.

        Raises:
            ValueError: ``GROUP_NOT_FOUND``, ``SCOPE_UNIT_REQUIRED``, ``SCOPE_UNIT_NOT_ALLOWED``,
                ``SCOPE_UNIT_NOT_FOUND`` or ``BINDING_ALREADY_EXISTS``.
        """
        with self._session_factory() as session:
            group = session.scalars(
                select(GroupRow).where(GroupRow.tenant_id == tenant_id, GroupRow.id == group_id)
            ).first()
            if group is None:
                raise ValueError("GROUP_NOT_FOUND")
            if scope == Scope.UNIT:
                if scope_unit_id is None:
                    raise ValueError("SCOPE_UNIT_REQUIRED")
                unit = session.scalars(
                    select(OrgUnitRow.id).where(OrgUnitRow.tenant_id == tenant_id, OrgUnitRow.id == scope_unit_id)
                ).first()
                if unit is None:
                    raise ValueError("SCOPE_UNIT_NOT_FOUND")
            elif scope_unit_id is not None:
                raise ValueError("SCOPE_UNIT_NOT_ALLOWED")
            duplicate = session.scalars(
                select(BindingRow.id).where(
                    BindingRow.tenant_id == tenant_id,
                    BindingRow.group_id == group_id,
                    BindingRow.app_id == app_id,
                    BindingRow.bundle_id == bundle_id,
                    BindingRow.scope == scope.value,
                    BindingRow.scope_unit_id.is_(scope_unit_id) if scope_unit_id is None
                    else BindingRow.scope_unit_id == scope_unit_id,
                    BindingRow.revoked_at.is_(None),
                )
            ).first()
            if duplicate is not None:
                raise ValueError("BINDING_ALREADY_EXISTS")
            row = BindingRow(
                tenant_id=tenant_id,
                group_id=group_id,
                app_id=app_id,
                bundle_id=bundle_id,
                scope=scope.value,
                scope_unit_id=scope_unit_id,
                bundle_digest=bundle_digest,
                granted_by=granted_by,
            )
            session.add(row)
            session.commit()
            return _binding_dto(row)

    def get_binding(self, tenant_id: str, binding_id: str) -> Optional[BindingDTO]:
        """Return a binding (active or revoked) of the tenant or None."""
        with self._session_factory() as session:
            row = session.scalars(
                select(BindingRow).where(BindingRow.tenant_id == tenant_id, BindingRow.id == binding_id)
            ).first()
            return _binding_dto(row) if row is not None else None

    def revoke_binding(self, tenant_id: str, binding_id: str, revoked_by: str) -> bool:
        """Soft-revoke an active binding; True if one was revoked."""
        with self._session_factory() as session:
            row = session.scalars(
                select(BindingRow).where(
                    BindingRow.tenant_id == tenant_id,
                    BindingRow.id == binding_id,
                    BindingRow.revoked_at.is_(None),
                )
            ).first()
            if row is None:
                return False
            row.revoked_at = datetime.now(timezone.utc)
            row.revoked_by = revoked_by
            session.commit()
            return True

    def active_bindings_for_groups(self, tenant_id: str, group_ids: Sequence[str]) -> List[BindingDTO]:
        """Return active bindings of the tenant for any of ``group_ids``."""
        if not group_ids:
            return []
        with self._session_factory() as session:
            rows = session.scalars(
                select(BindingRow).where(
                    BindingRow.tenant_id == tenant_id,
                    BindingRow.group_id.in_(list(group_ids)),
                    BindingRow.revoked_at.is_(None),
                )
            ).all()
            return [_binding_dto(r) for r in rows]

    def list_active_bindings(self, tenant_id: str) -> List[BindingDTO]:
        """Return all active bindings of the tenant."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(BindingRow).where(BindingRow.tenant_id == tenant_id, BindingRow.revoked_at.is_(None))
            ).all()
            return [_binding_dto(r) for r in rows]

    def bindings_for_group(self, tenant_id: str, group_id: str) -> List[BindingDTO]:
        """Return active bindings of one group."""
        return self.active_bindings_for_groups(tenant_id, [group_id])

    def count_active_bindings(self, tenant_id: str) -> int:
        """Return the number of active bindings of the tenant (0 means not onboarded)."""
        with self._session_factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(BindingRow)
                .where(BindingRow.tenant_id == tenant_id, BindingRow.revoked_at.is_(None))
            )
            return int(count or 0)
