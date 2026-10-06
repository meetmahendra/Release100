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

"""Unit tests for entitlement DB models (Plan 10, T07)."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core_platform.app.db.base import Base
from core_platform.app.entitlements.db_models import (
    GroupMemberRow,
    GroupRow,
    entitlement_tables,
)

EXPECTED = {
    "platform_ent_org_units",
    "platform_ent_groups",
    "platform_ent_group_members",
    "platform_ent_bindings",
}


def _engine(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite:///{tmp_path / 'ent.db'}")
    Base.metadata.create_all(bind=engine, tables=entitlement_tables())
    return engine


def test_create_all_creates_exactly_entitlement_tables(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    assert set(inspect(engine).get_table_names()) == EXPECTED
    engine.dispose()


def test_group_name_unique_per_tenant(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as s:
        s.add(GroupRow(tenant_id="t1", name="Nurses"))
        s.add(GroupRow(tenant_id="t1", name="Nurses"))
        with pytest.raises(IntegrityError):
            s.commit()
    engine.dispose()


def test_same_group_name_allowed_in_two_tenants(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as s:
        s.add(GroupRow(tenant_id="t1", name="Nurses"))
        s.add(GroupRow(tenant_id="t2", name="Nurses"))
        s.commit()
    engine.dispose()


def test_duplicate_membership_rejected(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as s:
        s.add(GroupMemberRow(tenant_id="t1", group_id="g1", principal_id="+10000000001"))
        s.add(GroupMemberRow(tenant_id="t1", group_id="g1", principal_id="+10000000001"))
        with pytest.raises(IntegrityError):
            s.commit()
    engine.dispose()


def test_group_kind_defaults_to_user(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as s:
        row = GroupRow(tenant_id="t1", name="Default kind")
        s.add(row)
        s.commit()
        assert row.kind == "USER"
    engine.dispose()
