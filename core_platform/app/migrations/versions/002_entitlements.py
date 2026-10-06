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

"""Entitlement tables: org units, groups, group members, bindings.

Revision ID: 002_entitlements
Revises: 001_initial_schema
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_entitlements"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    """Return the created_at / updated_at column pair."""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    """Create the four entitlement tables."""
    op.create_table(
        "platform_ent_org_units",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True, index=True),
        sa.Column("label", sa.String(60), nullable=False, server_default=""),
        *_timestamps(),
    )
    op.create_table(
        "platform_ent_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="USER"),
        sa.Column("external_ref", sa.String(255), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ent_group_tenant_name"),
    )
    op.create_table(
        "platform_ent_group_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("group_id", sa.String(36), nullable=False, index=True),
        sa.Column("principal_id", sa.String(64), nullable=False, index=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id", "group_id", "principal_id", name="uq_ent_member_group_principal"
        ),
    )
    op.create_table(
        "platform_ent_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("group_id", sa.String(36), nullable=False, index=True),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("bundle_id", sa.String(48), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_unit_id", sa.String(36), nullable=True),
        sa.Column("bundle_digest", sa.String(64), nullable=False),
        sa.Column("granted_by", sa.String(64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(64), nullable=True),
        *_timestamps(),
    )


def downgrade() -> None:
    """Drop the four entitlement tables."""
    op.drop_table("platform_ent_bindings")
    op.drop_table("platform_ent_group_members")
    op.drop_table("platform_ent_groups")
    op.drop_table("platform_ent_org_units")
