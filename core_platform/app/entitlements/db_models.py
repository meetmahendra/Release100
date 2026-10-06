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

"""SQLAlchemy tables for the Decentralized Entitlement Architecture (Plan 10, 4.3).

Every table carries ``tenant_id``; the repository filters on it in every query.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
import uuid

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Table

from core_platform.app.db.base import Base, TimestampMixin


def _uuid() -> str:
    """Return a new 36-character UUID string."""
    return str(uuid.uuid4())


class OrgUnitRow(Base, TimestampMixin):
    """A node in the customer's own organizational tree (label is the customer's word)."""

    __tablename__ = "platform_ent_org_units"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)
    label: Mapped[str] = mapped_column(String(60), nullable=False, default="")


class GroupRow(Base, TimestampMixin):
    """A customer group; kind separates people (USER) from API keys / AI agents (SERVICE)."""

    __tablename__ = "platform_ent_groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ent_group_tenant_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="USER")
    external_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class GroupMemberRow(Base, TimestampMixin):
    """Membership of a principal (phone number or API-key principal id) in a group."""

    __tablename__ = "platform_ent_group_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "group_id", "principal_id", name="uq_ent_member_group_principal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    group_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    principal_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)


class BindingRow(Base, TimestampMixin):
    """Grant of a cartridge bundle to a group at a scope; revoked softly for audit history."""

    __tablename__ = "platform_ent_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    group_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_id: Mapped[str] = mapped_column(String(48), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_unit_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    bundle_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


def entitlement_tables() -> List[Table]:
    """Return exactly the entitlement tables (used for scoped ``create_all``)."""
    return [
        OrgUnitRow.__table__,  # type: ignore[list-item]
        GroupRow.__table__,  # type: ignore[list-item]
        GroupMemberRow.__table__,  # type: ignore[list-item]
        BindingRow.__table__,  # type: ignore[list-item]
    ]
