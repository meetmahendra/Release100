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
SQLAlchemy 2.0 Type-Safe Declarative Models for Mail Organizer Cartridge.

Adheres strictly to Plan 04 v1.0 and GEES v1.0.
100% type-annotated with Mapped[T] and mapped_column.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for mail_organizer cartridge models."""
    pass


class EmailRecord(Base):
    """Stores raw and normalized email messages ingested from Gmail."""

    __tablename__ = "mail_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    subject: Mapped[str] = mapped_column(String, default="")
    sender: Mapped[str] = mapped_column(String, index=True)
    to_recipients: Mapped[str] = mapped_column(String, default="")
    cc_recipients: Mapped[str] = mapped_column(String, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    labels_applied: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="PROCESSED")


class EmailClassification(Base):
    """Stores LLM classification and triage results for an email."""

    __tablename__ = "mail_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_id: Mapped[str] = mapped_column(String, ForeignKey("mail_emails.gmail_id"), index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    urgency_score: Mapped[int] = mapped_column(Integer, default=5)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    context_tags: Mapped[str] = mapped_column(String, default="")
    is_reply_necessary: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_necessity_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    responsibility_role: Mapped[str] = mapped_column(String, default="PRIMARY_ACTIONEE")
    suggested_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class PMActionQueue(Base):
    """Queue of project management tasks extracted from emails awaiting human review."""

    __tablename__ = "mail_pm_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    gmail_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    email_subject: Mapped[str] = mapped_column(String, default="")
    email_sender: Mapped[str] = mapped_column(String, default="")
    summary: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String, default="Medium")
    project_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    due_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING", index=True)
    destination: Mapped[str] = mapped_column(String, default="sqlite_queue")
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MailRule(Base):
    """Deterministic whitelist and keyword routing rules."""

    __tablename__ = "mail_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_type: Mapped[str] = mapped_column(String, index=True)
    pattern: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, default="tag_vip")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class DraftRecord(Base):
    """Staged email draft replies awaiting user transmission or auto-sync."""

    __tablename__ = "mail_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_id: Mapped[str] = mapped_column(String, index=True)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    recipient: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="STAGED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
