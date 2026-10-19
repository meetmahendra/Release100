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

Adheres strictly to Plan 04 v1.0 and GEES v1.0 / v2.0.
Universal SQL dialect compatibility across SQLite, PostgreSQL, and MySQL/MariaDB.
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
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    gmail_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    subject: Mapped[str] = mapped_column(String(512), default="")
    sender: Mapped[str] = mapped_column(String(255), index=True)
    to_recipients: Mapped[str] = mapped_column(String(1024), default="")
    cc_recipients: Mapped[str] = mapped_column(String(1024), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    labels_applied: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(64), default="PROCESSED")
    rfc_headers_json: Mapped[str] = mapped_column(Text, default="{}")
    resolved_contact_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)


class EmailClassification(Base):
    """Stores LLM classification and triage results for an email."""

    __tablename__ = "mail_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    gmail_id: Mapped[str] = mapped_column(String(128), ForeignKey("mail_emails.gmail_id"), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    urgency_score: Mapped[int] = mapped_column(Integer, default=5)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    context_tags: Mapped[str] = mapped_column(String(255), default="")
    is_reply_necessary: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_necessity_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    responsibility_role: Mapped[str] = mapped_column(String(64), default="PRIMARY_ACTIONEE")
    suggested_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    speech_act: Mapped[str] = mapped_column(String(64), default="INFORM")
    salutation_extracted: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    was_promoted_from_cc: Mapped[bool] = mapped_column(Boolean, default=False)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class PMActionQueue(Base):
    """Queue of project management tasks extracted from emails awaiting human review."""

    __tablename__ = "mail_pm_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    task_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    gmail_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    email_subject: Mapped[str] = mapped_column(String(512), default="")
    email_sender: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(String(512))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(32), default="Medium")
    project_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    due_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="PENDING", index=True)
    destination: Mapped[str] = mapped_column(String(64), default="sqlite_queue")
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
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    rule_type: Mapped[str] = mapped_column(String(64), index=True)
    pattern: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(64), default="tag_vip")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class DraftRecord(Base):
    """Staged email draft replies awaiting user transmission or auto-sync."""

    __tablename__ = "mail_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    gmail_id: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    recipient: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="STAGED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class WorkspacePollerConfig(Base):
    """Tenant-wide mail poller configuration managed by Customer (Tenant) Admin."""

    __tablename__ = "mail_workspace_poller_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    is_master_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UserPollerConfig(Base):
    """Per-user mail poller configuration managed by Customer (Tenant) Admin."""

    __tablename__ = "mail_user_poller_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    is_poller_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    active_window: Mapped[str] = mapped_column(String(64), default="24x7", nullable=False)
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_cycles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_emails_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ContactEntity(Base):
    """Canonical unified contact identity across Email, WhatsApp, and Meeting transcripts (v1.3.0 Section 5.1)."""

    __tablename__ = "mail_contact_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    organization: Mapped[str] = mapped_column(String(255), default="")
    org_relationship: Mapped[str] = mapped_column(String(64), default="UNKNOWN", index=True)
    vip_override: Mapped[bool] = mapped_column(Boolean, default=False)
    learned_salutations_json: Mapped[str] = mapped_column(Text, default="[]")
    provisional_salutations_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ContactChannelAlias(Base):
    """Channel-specific handle mapped to a ContactEntity with 3-Layer confidence & quarantine status."""

    __tablename__ = "mail_contact_channel_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("mail_contact_entities.id"), index=True)
    channel_type: Mapped[str] = mapped_column(String(32), default="EMAIL", index=True)
    raw_identifier: Mapped[str] = mapped_column(String(255), index=True)
    display_name_seen: Mapped[str] = mapped_column(String(255), default="")
    resolution_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    resolution_status: Mapped[str] = mapped_column(String(32), default="VERIFIED", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class RoleTaxonomyTemplate(Base):
    """Pre-configured role taxonomy templates (SWE_IC, ENG_MANAGER, PROCUREMENT_FINANCE, EXECUTIVE_FOUNDER, SALES_ACCOUNT)."""

    __tablename__ = "mail_role_taxonomy_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    role_key: Mapped[str] = mapped_column(String(64), index=True)
    role_display_name: Mapped[str] = mapped_column(String(128))
    categories_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class UserActiveCategory(Base):
    """Per-user active triage categories with parent domain mapping for coarse-to-fine Jev routing."""

    __tablename__ = "mail_user_active_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    role_key: Mapped[str] = mapped_column(String(64), default="EXECUTIVE_FOUNDER")
    category_name: Mapped[str] = mapped_column(String(64), index=True)
    parent_domain: Mapped[str] = mapped_column(String(64), default="WORK_DELIVERABLE", index=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    default_urgency: Mapped[int] = mapped_column(Integer, default=6)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


# [CODE-MARKER: MO-DB-01] Hybrid Neuro-Symbolic Data Layer ORM Models
class CommitmentLedger(Base):
    """Language-Action (Winograd/Flores) bidirectional commitment ledger (OWED_BY_ME vs OWED_TO_ME)."""

    __tablename__ = "mail_commitment_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    commitment_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_channel: Mapped[str] = mapped_column(String(32), default="EMAIL", index=True)
    source_msg_id: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    direction: Mapped[str] = mapped_column(String(32), default="OWED_BY_ME", index=True)
    speech_act: Mapped[str] = mapped_column(String(32), default="REQUEST")
    counterparty_contact_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    counterparty_handle: Mapped[str] = mapped_column(String(255), default="")
    deliverable_summary: Mapped[str] = mapped_column(String(512))
    raw_deadline_text: Mapped[str] = mapped_column(String(128), default="Next Business Day")
    resolved_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class EntityFactGraph(Base):
    """Symbolic temporal fact triples (Subject, Predicate, Object) with supersession tracking."""

    __tablename__ = "mail_entity_fact_graph"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    subject_entity: Mapped[str] = mapped_column(String(255), index=True)
    predicate: Mapped[str] = mapped_column(String(128), index=True)
    object_value: Mapped[str] = mapped_column(Text)
    source_channel: Mapped[str] = mapped_column(String(32), default="EMAIL")
    source_msg_id: Mapped[str] = mapped_column(String(128), index=True)
    is_superseded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    superseded_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class MissingArtifactRequest(Base):
    """Tracks emails paused in WAITING_FOR_USER_ARTIFACT due to missing attachments or unresolved facts."""

    __tablename__ = "mail_missing_artifact_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    gmail_id: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), default="MISSING_ATTACHMENT")
    artifact_description: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(64), default="WAITING_FOR_USER_ARTIFACT", index=True)
    resolved_content_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ConsentAuditLog(Base):
    """Cryptographic CIPA / GDPR / India DPDP multi-party recording & transcript consent ledger."""

    __tablename__ = "mail_consent_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    channel_type: Mapped[str] = mapped_column(String(32), default="MEETING_TRANSCRIPT")
    jurisdiction_policy: Mapped[str] = mapped_column(String(64), default="ALL_PARTY_CIPA")
    participants_json: Mapped[str] = mapped_column(Text, default="[]")
    all_parties_consented: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_proof_hash: Mapped[str] = mapped_column(String(128))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class SemanticChunkRecord(Base):
    """Cross-channel semantic chunk store for hybrid neuro-symbolic retrieval."""

    __tablename__ = "mail_semantic_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="public", server_default="public", index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source_channel: Mapped[str] = mapped_column(String(32), default="EMAIL", index=True)
    msg_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_tags: Mapped[str] = mapped_column(String(512), default="")
    chunk_text: Mapped[str] = mapped_column(Text)
    token_vector_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


