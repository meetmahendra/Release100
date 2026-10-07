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

"""
Core Database Declarative Base & Universal Entity Mixins.

Adheres strictly to GEES v2.0 Pillar 3 (Microkernel Isolation) & Pillar 5 (Type Discipline).
Provides reusable, dialect-agnostic mixins for multi-tenancy, audit timestamps, and UUIDs.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative Base class for core_platform models."""
    pass


class TimestampMixin:
    """Universal mixin injecting UTC creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """Universal mixin injecting a 36-character string UUID primary key."""

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )


class TenantIsolationMixin:
    """Universal mixin for multi-tenant isolation across SQL databases."""

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
        default="default",
    )
