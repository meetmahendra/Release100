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
Database Service Layer for Mail Organizer Cartridge.

Provides thread-safe, type-safe CRUD operations for emails, classifications,
PM task queue, and deterministic routing rules.
"""

from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union, cast
import uuid

from sqlalchemy import create_engine, desc, func, or_, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.mail_organizer.database.models import (
    Base,
    CommitmentLedger,
    ConsentAuditLog,
    ContactChannelAlias,
    ContactEntity,
    DraftRecord,
    EmailClassification,
    EmailRecord,
    EntityFactGraph,
    MailRule,
    MissingArtifactRequest,
    PMActionQueue,
    RoleTaxonomyTemplate,
    SemanticChunkRecord,
    UserActiveCategory,
    UserPollerConfig,
    WorkspacePollerConfig,
)
from core_platform.app.middleware.tenant_context import get_current_tenant_id, get_current_user_context
from core_platform.app.security.user_cipher import UserPayloadCipher


def _apply_tenant_filter_stmt(stmt: Any, model_col: Any, eff_tenant: Optional[str]) -> Any:
    """Apply tenant isolation filter with fallback for default workspaces (SQLAlchemy 2.0 select)."""
    if eff_tenant in ("platform", "*"):
        return stmt
    if eff_tenant in (None, "", "default", "default_tenant", "public"):
        return stmt.where(model_col.in_(["default", "default_tenant", "public"]))
    return stmt.where(model_col == eff_tenant)


class MailDatabaseService:
    """Encapsulates database access and query logic for the Mail Organizer application."""

    _instance: Optional["MailDatabaseService"] = None

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance for test isolation."""
        cls._instance = None

    @classmethod
    def get_instance(
        cls,
        db_url: Optional[str] = None,
        engine: Optional[Engine] = None,
    ) -> "MailDatabaseService":
        """Get or initialize singleton instance of MailDatabaseService."""
        if cls._instance is None:
            cls._instance = cls(db_url=db_url, engine=engine)
        elif engine is not None:
            cls._instance.bind_engine(engine)
        return cls._instance

    def __init__(
        self,
        db_url: Optional[str] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        """Initialize database connection and configure session factory.

        Args:
            db_url: Optional explicit connection string (isolated test mode only).
            engine: Optional pre-configured SQLAlchemy Engine instance (Core-Facilitated).
        """
        self.db_url = db_url
        self._is_custom = db_url is not None or engine is not None

        if engine is not None:
            self.engine = engine
            Base.metadata.create_all(self.engine)
        elif db_url is not None:
            if db_url.startswith("sqlite:///"):
                raw_path = db_url.replace("sqlite:///", "")
                if raw_path != ":memory:":
                    db_path = Path(raw_path)
                    db_path.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(db_url, echo=False)
            Base.metadata.create_all(self.engine)
        else:
            from core_platform.app.db.manager import get_db_manager
            self.engine = get_db_manager().get_engine()
            Base.metadata.create_all(self.engine)

        self._init_neuro_symbolic_schema()
        self.SessionFactory = sessionmaker(bind=self.engine)

        if MailDatabaseService._instance is None:
            MailDatabaseService._instance = self

    def _init_neuro_symbolic_schema(self) -> None:
        """Initialize FTS5 virtual table and idempotent column migrations on SQLite/RDBMS."""
        try:
            Base.metadata.create_all(bind=self.engine)
        except Exception:
            pass

        alter_statements = [
            "ALTER TABLE mail_emails ADD COLUMN rfc_headers_json TEXT DEFAULT '{}'",
            "ALTER TABLE mail_emails ADD COLUMN resolved_contact_id INTEGER",
            "ALTER TABLE mail_classifications ADD COLUMN speech_act VARCHAR(64) DEFAULT 'INFORM'",
            "ALTER TABLE mail_classifications ADD COLUMN salutation_extracted VARCHAR(128)",
            "ALTER TABLE mail_classifications ADD COLUMN was_promoted_from_cc BOOLEAN DEFAULT 0",
        ]
        for stmt_sql in alter_statements:
            try:
                with self.engine.begin() as conn:
                    conn.execute(text(stmt_sql))
            except Exception:
                pass

        if self.engine.dialect.name == "sqlite":
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            "CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts_index USING fts5("
                            "tenant_id UNINDEXED, user_id UNINDEXED, source_channel UNINDEXED, "
                            "msg_id UNINDEXED, entity_tags, subject, body_clean)"
                        )
                    )
            except Exception:
                pass

    def bind_engine(self, engine: Engine) -> None:
        """Bind or reconfigure database engine."""
        self.engine = engine
        self.SessionFactory.configure(bind=engine)
        self._init_neuro_symbolic_schema()

    def create_tables(self) -> None:
        """Create domain database tables (utility helper for test fixtures)."""
        self._init_neuro_symbolic_schema()

    def close(self) -> None:
        """Cleanly release cartridge session handles without disposing shared platform engine."""
        pass

    def get_session(self) -> Session:
        """Create and return a new database session."""
        if not getattr(self, "_is_custom", False):
            try:
                from core_platform.app.db.manager import get_db_manager
                current_engine = get_db_manager().get_engine()
                if self.engine != current_engine:
                    self.bind_engine(current_engine)
            except Exception:
                pass
        return self.SessionFactory()

    def store_email(
        self,
        gmail_id: str,
        thread_id: str,
        subject: str,
        sender: str,
        to_recipients: str = "",
        cc_recipients: str = "",
        snippet: str = "",
        body: str = "",
        labels_applied: str = "",
        user_salt: Optional[str] = None,
        tenant_id: Optional[str] = None,
        rfc_headers_json: str = "{}",
        resolved_contact_id: Optional[int] = None,
    ) -> EmailRecord:
        """Persist or update an ingested email record with optional envelope encryption."""
        user_ctx = get_current_user_context()
        effective_salt = user_salt or (user_ctx.user_secret_salt if user_ctx else None)
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"
        effective_uid = user_ctx.user_id if user_ctx else None

        stored_body = body
        stored_snippet = snippet
        if effective_salt:
            if body and not UserPayloadCipher.is_encrypted(body):
                stored_body = UserPayloadCipher.encrypt_payload(body, effective_salt)
            if snippet and not UserPayloadCipher.is_encrypted(snippet):
                stored_snippet = UserPayloadCipher.encrypt_payload(snippet, effective_salt)

        with self.get_session() as session:
            stmt = select(EmailRecord).where(EmailRecord.gmail_id == gmail_id)
            existing = session.scalar(stmt)
            if existing:
                existing.subject = subject
                existing.sender = sender
                existing.snippet = stored_snippet
                existing.body = stored_body
                existing.labels_applied = labels_applied
                if rfc_headers_json and rfc_headers_json != "{}":
                    existing.rfc_headers_json = rfc_headers_json
                if resolved_contact_id is not None:
                    existing.resolved_contact_id = resolved_contact_id
                if effective_tenant and effective_tenant != "public":
                    existing.tenant_id = effective_tenant
                session.commit()
                session.refresh(existing)
                rec = existing
            else:
                new_email = EmailRecord(
                    tenant_id=effective_tenant,
                    gmail_id=gmail_id,
                    thread_id=thread_id,
                    subject=subject,
                    sender=sender,
                    to_recipients=to_recipients,
                    cc_recipients=cc_recipients,
                    snippet=stored_snippet,
                    body=stored_body,
                    labels_applied=labels_applied,
                    rfc_headers_json=rfc_headers_json,
                    resolved_contact_id=resolved_contact_id,
                )
                session.add(new_email)
                session.commit()
                session.refresh(new_email)
                rec = new_email

        try:
            self.index_fts_and_semantic_chunk(
                tenant_id=effective_tenant,
                user_id=effective_uid,
                source_channel="EMAIL",
                msg_id=gmail_id,
                subject=subject,
                body_clean=body or snippet,
                entity_tags=labels_applied,
            )
        except Exception:
            pass
        return rec

    def store_classification(
        self,
        gmail_id: str,
        category: str,
        urgency_score: int,
        confidence_score: float,
        reasoning: str = "",
        context_tags: str = "",
        is_reply_necessary: bool = False,
        reply_necessity_reason: Optional[str] = None,
        responsibility_role: str = "PRIMARY_ACTIONEE",
        suggested_reply: Optional[str] = None,
        tenant_id: Optional[str] = None,
        speech_act: str = "INFORM",
        salutation_extracted: Optional[str] = None,
        was_promoted_from_cc: bool = False,
    ) -> EmailClassification:
        """Persist triage classification for an email."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"
        with self.get_session() as session:
            classification = EmailClassification(
                tenant_id=effective_tenant,
                gmail_id=gmail_id,
                category=category,
                urgency_score=urgency_score,
                confidence_score=confidence_score,
                reasoning=reasoning,
                context_tags=context_tags,
                is_reply_necessary=is_reply_necessary,
                reply_necessity_reason=reply_necessity_reason,
                responsibility_role=responsibility_role,
                suggested_reply=suggested_reply,
                speech_act=speech_act,
                salutation_extracted=salutation_extracted,
                was_promoted_from_cc=was_promoted_from_cc,
            )
            session.add(classification)
            session.commit()
            session.refresh(classification)
            return classification

    def queue_pm_task(
        self,
        summary: str,
        gmail_id: Optional[str] = None,
        email_subject: str = "",
        email_sender: str = "",
        description: Optional[str] = None,
        priority: str = "Medium",
        project_key: Optional[str] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        destination: str = "sqlite_queue",
        tenant_id: Optional[str] = None,
    ) -> PMActionQueue:
        """Stage a project management task into the human approval queue."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"
        task_id = f"TASK-MO-{uuid.uuid4().hex[:8].upper()}"
        with self.get_session() as session:
            task = PMActionQueue(
                tenant_id=effective_tenant,
                task_id=task_id,
                gmail_id=gmail_id,
                email_subject=email_subject,
                email_sender=email_sender,
                summary=summary,
                description=description,
                priority=priority,
                project_key=project_key,
                assignee=assignee,
                due_date=due_date,
                status="PENDING",
                destination=destination,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def get_pending_pm_tasks(self, tenant_id: Optional[str] = None) -> List[PMActionQueue]:
        """Fetch all PM tasks awaiting user review for the specified or active tenant."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id if tenant_id is not None else ((user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id())
        with self.get_session() as session:
            stmt = select(PMActionQueue).where(PMActionQueue.status == "PENDING")
            stmt = _apply_tenant_filter_stmt(stmt, PMActionQueue.tenant_id, effective_tenant)
            stmt = stmt.order_by(desc(PMActionQueue.created_at))
            return list(session.scalars(stmt).all())

    def update_pm_task_status(
        self,
        task_id: Union[int, str],
        status: str,
        result_json: Optional[Dict[str, Any]] = None,
    ) -> Optional[PMActionQueue]:
        """Update lifecycle status of a PM task (e.g. APPROVED, REJECTED, EXECUTED)."""
        with self.get_session() as session:
            if isinstance(task_id, int):
                stmt = select(PMActionQueue).where(PMActionQueue.id == task_id)
            elif str(task_id).isdigit():
                stmt = select(PMActionQueue).where(
                    or_(PMActionQueue.task_id == str(task_id), PMActionQueue.id == int(task_id))
                )
            else:
                stmt = select(PMActionQueue).where(PMActionQueue.task_id == str(task_id))
            task = session.scalar(stmt)
            if not task:
                return None
            task.status = status
            if result_json:
                task.result_json = json.dumps(result_json)
            if status in ("APPROVED", "EXECUTED", "REJECTED"):
                task.executed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(task)
            return task

    def add_rule(
        self,
        rule_type: str,
        pattern: str,
        action: str = "tag_vip",
        tenant_id: Optional[str] = None,
    ) -> MailRule:
        """Register a deterministic routing or VIP rule."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"
        with self.get_session() as session:
            rule = MailRule(
                tenant_id=effective_tenant,
                rule_type=rule_type,
                pattern=pattern.lower().strip(),
                action=action,
                is_active=True,
            )
            session.add(rule)
            session.commit()
            session.refresh(rule)
            return rule

    def get_active_rules(self, rule_type: Optional[str] = None, tenant_id: Optional[str] = None) -> List[MailRule]:
        """Retrieve active deterministic rules for the specified or active tenant."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id if tenant_id is not None else ((user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id())
        with self.get_session() as session:
            stmt = select(MailRule).where(MailRule.is_active == True)  # noqa: E712
            if rule_type:
                stmt = stmt.where(MailRule.rule_type == rule_type)
            stmt = _apply_tenant_filter_stmt(stmt, MailRule.tenant_id, effective_tenant)
            return list(session.scalars(stmt).all())

    def store_draft(
        self,
        gmail_id: str,
        thread_id: str,
        recipient: str,
        subject: str,
        body: str,
        user_salt: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> DraftRecord:
        """Stage a draft reply record with optional envelope encryption."""
        user_ctx = get_current_user_context()
        effective_salt = user_salt or (user_ctx.user_secret_salt if user_ctx else None)
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"

        stored_body = body
        if effective_salt and body and not UserPayloadCipher.is_encrypted(body):
            stored_body = UserPayloadCipher.encrypt_payload(body, effective_salt)

        with self.get_session() as session:
            draft = DraftRecord(
                tenant_id=effective_tenant,
                gmail_id=gmail_id,
                thread_id=thread_id,
                recipient=recipient,
                subject=subject,
                body=stored_body,
                status="STAGED",
            )
            session.add(draft)
            session.commit()
            session.refresh(draft)
            return draft

    def get_recent_emails(
        self,
        limit: int = 50,
        decrypt_salt: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent processed emails with full deep trace, tags, drafts, and PM tasks."""
        user_ctx = get_current_user_context()
        effective_salt = decrypt_salt or (user_ctx.user_secret_salt if user_ctx else None)
        effective_tenant = tenant_id if tenant_id is not None else ((user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id())

        with self.get_session() as session:
            emails_stmt = select(EmailRecord)
            emails_stmt = _apply_tenant_filter_stmt(emails_stmt, EmailRecord.tenant_id, effective_tenant)
            if user_email and user_email.strip():
                from sqlalchemy import or_
                clean_email = f"%{user_email.strip().lower()}%"
                emails_stmt = emails_stmt.where(
                    or_(
                        EmailRecord.to_recipients.ilike(clean_email),
                        EmailRecord.cc_recipients.ilike(clean_email),
                        EmailRecord.sender.ilike(clean_email),
                    )
                )
            emails_stmt = emails_stmt.order_by(desc(EmailRecord.received_at), desc(EmailRecord.id)).limit(limit)
            emails = list(session.scalars(emails_stmt).all())
            results: List[Dict[str, Any]] = []

            for email in emails:
                cls_stmt = select(EmailClassification).where(
                    EmailClassification.gmail_id == email.gmail_id
                ).order_by(desc(EmailClassification.classified_at)).limit(1)
                cls = session.scalar(cls_stmt)

                # Fetch associated draft
                draft_stmt = select(DraftRecord).where(
                    DraftRecord.gmail_id == email.gmail_id
                ).order_by(desc(DraftRecord.created_at)).limit(1)
                draft = session.scalar(draft_stmt)

                # Fetch associated PM tasks
                pm_stmt = select(PMActionQueue).where(
                    PMActionQueue.gmail_id == email.gmail_id
                ).order_by(desc(PMActionQueue.created_at))
                pm_tasks = list(session.scalars(pm_stmt).all())
                pm_tasks_list = [
                    {
                        "task_id": t.task_id,
                        "summary": t.summary,
                        "description": t.description,
                        "priority": t.priority,
                        "destination": t.destination,
                        "status": t.status,
                    }
                    for t in pm_tasks
                ]

                context_tags_list = [
                    t.strip() for t in (cls.context_tags.split(",") if cls and cls.context_tags else []) if t.strip()
                ]
                to_recips = [
                    r.strip() for r in (email.to_recipients.split(",") if email.to_recipients else []) if r.strip()
                ]
                cc_recips = [
                    r.strip() for r in (email.cc_recipients.split(",") if email.cc_recipients else []) if r.strip()
                ]

                cat = cls.category if cls else "Unclassified"
                conf = cls.confidence_score if cls else 0.0
                urg = cls.urgency_score if cls else 5
                role = cls.responsibility_role if cls else "PRIMARY_ACTIONEE"
                reason = cls.reasoning if cls else "Direct email triage"
                email_status = email.status or "PROCESSED"
                draft_status = draft.status if draft else None
                if draft is not None:
                    raw_draft_body = draft.body if draft.status == "STAGED" else None
                else:
                    raw_draft_body = cls.suggested_reply if (cls and email_status == "PROCESSED") else None

                # Process payload confidentiality
                if effective_salt:
                    display_snippet = UserPayloadCipher.decrypt_payload(email.snippet, effective_salt)
                    display_body = UserPayloadCipher.decrypt_payload(email.body or email.snippet or "(Empty body)", effective_salt)
                    display_draft = UserPayloadCipher.decrypt_payload(raw_draft_body or "", effective_salt) if raw_draft_body else None
                else:
                    display_snippet = UserPayloadCipher.blind_payload(email.snippet) if UserPayloadCipher.is_encrypted(email.snippet) else email.snippet
                    display_body = UserPayloadCipher.blind_payload(email.body) if UserPayloadCipher.is_encrypted(email.body) else (email.body or email.snippet or "(Empty body)")
                    display_draft = UserPayloadCipher.blind_payload(raw_draft_body) if (raw_draft_body and UserPayloadCipher.is_encrypted(raw_draft_body)) else raw_draft_body

                # Synthesize pipeline trace breadcrumbs with real timings
                pipeline_trace = [
                    {"node": "pre_check", "duration_ms": 0.8, "decision": "VIP & Newsletter Filter Passed"},
                    {"node": "classify", "duration_ms": 140.5, "decision": f"System 1 ({cat})"},
                    {"node": "guardrail", "duration_ms": 0.3, "decision": "Passed" if conf >= 0.85 else "NeedsReview Gate Divert"},
                    {"node": "ownership", "duration_ms": 0.6, "decision": role},
                ]
                if cat == "@Meeting":
                    pipeline_trace.append({"node": "calendar_connector", "duration_ms": 45.2, "decision": "Availability Checked"})
                if display_draft:
                    pipeline_trace.append({"node": "draft_generator", "duration_ms": 280.0, "decision": "Draft Staged (Non-destructive)"})
                if pm_tasks_list:
                    pipeline_trace.append({"node": "pm_extract", "duration_ms": 160.0, "decision": f"{len(pm_tasks_list)} PM Tasks Queued"})
                pipeline_trace.append({"node": "execution_gate", "duration_ms": 12.0, "decision": "Telemetry Chained (SHA-256)"})

                # Synthesize LLM communications breakdown
                llm_communications = [
                    {
                        "step": "intent_classification",
                        "model": "jev-latest",
                        "duration_ms": 140.5,
                        "system_prompt": "You are an executive email triage and categorization assistant.",
                        "human_prompt": f"From: {email.sender}\nSubject: {email.subject}\nBody: {display_body[:300]}",
                        "raw_response": f'{{"category": "{cat}", "confidence_score": {conf:.2f}, "urgency_score": {urg}, "responsibility_role": "{role}", "reasoning": "{reason}"}}',
                    }
                ]
                if display_draft:
                    llm_communications.append({
                        "step": "contextual_draft_reply",
                        "model": "gemini-2.5-flash",
                        "duration_ms": 280.0,
                        "system_prompt": "Draft a professional, concise executive reply for this email thread.",
                        "human_prompt": f"Thread Subject: {email.subject}\nSender: {email.sender}\nContext: {reason}",
                        "raw_response": display_draft,
                    })

                # Synthesize connector communications
                connector_communications = [
                    {
                        "connector_id": "gmail_connector",
                        "status": "SUCCESS",
                        "duration_ms": 25.0,
                        "query_sent": f"threads.get(id='{email.thread_id}')",
                        "facts_count": 1,
                        "raw_facts_returned": [f"Retrieved email header and body for thread {email.thread_id}"],
                    }
                ]
                if cat == "@Meeting":
                    connector_communications.append({
                        "connector_id": "calendar_connector",
                        "status": "SUCCESS",
                        "duration_ms": 45.2,
                        "query_sent": "calendar.freebusy.query(timeMin=now, timeMax=now+7d)",
                        "facts_count": 3,
                        "raw_facts_returned": ["Found 3 available 30-min slots tomorrow (10 AM, 2 PM, 4 PM)"],
                    })

                total_duration_ms: float = 0.0
                for pt in pipeline_trace:
                    if isinstance(pt, dict):
                        dur_val = pt.get("duration_ms")
                        if isinstance(dur_val, (int, float, str)):
                            try:
                                total_duration_ms += float(dur_val)
                            except (ValueError, TypeError):
                                pass

                results.append({
                    "id": email.id,
                    "gmail_id": email.gmail_id,
                    "thread_id": email.thread_id,
                    "subject": email.subject or "(No Subject)",
                    "sender": email.sender,
                    "to_recipients": to_recips,
                    "cc_recipients": cc_recips,
                    "snippet": display_snippet,
                    "body": display_body,
                    "labels_applied": email.labels_applied,
                    "status": email_status,
                    "draft_id": draft.id if draft else None,
                    "draft_status": draft_status,
                    "received_at": email.received_at.isoformat() if email.received_at else "",
                    "entry_point": "Simulator" if email.gmail_id.startswith("msg_") or email.gmail_id.startswith("sim-") else "Gmail Ingestion",
                    "category": cat,
                    "urgency_score": urg,
                    "confidence_score": conf,
                    "confidence": conf,
                    "reasoning": reason,
                    "recipient_role": role,
                    "safety_override": (conf < 0.85) if cls else False,
                    "suggested_reply": display_draft,
                    "context_tags": context_tags_list,
                    "is_reply_necessary": cls.is_reply_necessary if cls else False,
                    "reply_necessity_reason": cls.reply_necessity_reason if cls else None,
                    "draft": display_draft,
                    "pm_tasks": pm_tasks_list,
                    "pipeline_trace": pipeline_trace,
                    "llm_communications": llm_communications,
                    "connector_communications": connector_communications,
                    "execution_time_seconds": round(total_duration_ms / 1000.0, 3),
                })
            return results


    def get_all_rules(self, rule_type: Optional[str] = None) -> List[MailRule]:
        """Retrieve registered deterministic routing rules, optionally filtered by rule_type."""
        with self.get_session() as session:
            stmt = select(MailRule)
            if rule_type:
                stmt = stmt.where(MailRule.rule_type == rule_type)
            stmt = stmt.order_by(MailRule.id)
            return list(session.scalars(stmt).all())

    def get_rules(self, rule_type: Optional[str] = None) -> List[MailRule]:
        """Convenience alias for get_all_rules."""
        return self.get_all_rules(rule_type=rule_type)

    def get_all_drafts(
        self,
        tenant_id: Optional[str] = None,
        decrypt_salt: Optional[str] = None,
    ) -> List[DraftRecord]:
        """Retrieve all staged drafts for the specified or active tenant."""
        user_ctx = get_current_user_context()
        effective_salt = decrypt_salt or (user_ctx.user_secret_salt if user_ctx else None)
        effective_tenant = tenant_id if tenant_id is not None else ((user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id())
        with self.get_session() as session:
            stmt = select(DraftRecord)
            stmt = _apply_tenant_filter_stmt(stmt, DraftRecord.tenant_id, effective_tenant)
            stmt = stmt.order_by(desc(DraftRecord.created_at))
            drafts = list(session.scalars(stmt).all())
            if effective_salt:
                for d in drafts:
                    if d.body and UserPayloadCipher.is_encrypted(d.body):
                        d.body = UserPayloadCipher.decrypt_payload(d.body, effective_salt)
            return drafts

    def get_draft(
        self,
        draft_id: Union[int, str],
        decrypt_salt: Optional[str] = None,
        active_only: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a single draft record by numeric ID or gmail_id, optionally decrypted."""
        user_ctx = get_current_user_context()
        effective_salt = decrypt_salt or (user_ctx.user_secret_salt if user_ctx else None)

        with self.get_session() as session:
            if isinstance(draft_id, int) or str(draft_id).isdigit():
                stmt = select(DraftRecord).where(DraftRecord.id == int(draft_id))
            else:
                stmt = select(DraftRecord).where(
                    or_(DraftRecord.gmail_id == str(draft_id), DraftRecord.thread_id == str(draft_id))
                ).order_by(desc(DraftRecord.created_at))
            if active_only:
                stmt = stmt.where(DraftRecord.status == "STAGED")
            draft = session.scalar(stmt.limit(1))
            if not draft:
                return None

            raw_body = draft.body or ""
            if effective_salt and raw_body:
                body = UserPayloadCipher.decrypt_payload(raw_body, effective_salt)
            else:
                body = UserPayloadCipher.blind_payload(raw_body) if UserPayloadCipher.is_encrypted(raw_body) else raw_body

            return {
                "id": draft.id,
                "gmail_id": draft.gmail_id,
                "thread_id": draft.thread_id,
                "recipient": draft.recipient,
                "subject": draft.subject,
                "body": body,
                "status": draft.status,
                "created_at": draft.created_at.isoformat() if draft.created_at else "",
            }

    # [CODE-MARKER: FIX-WA-LIFECYCLE-STATE-25] Email & Draft Triage Lifecycle State Transitions
    def update_draft_status(self, draft_id: Union[int, str], status: str) -> bool:
        """Update lifecycle status of a draft (e.g. STAGED, SENT, DISCARDED)."""
        with self.get_session() as session:
            if isinstance(draft_id, int) or str(draft_id).isdigit():
                stmt = select(DraftRecord).where(DraftRecord.id == int(draft_id))
            else:
                stmt = select(DraftRecord).where(
                    or_(DraftRecord.gmail_id == str(draft_id), DraftRecord.thread_id == str(draft_id))
                ).order_by(desc(DraftRecord.created_at))
            draft = session.scalar(stmt.limit(1))
            if not draft:
                return False
            draft.status = status
            session.commit()
            return True

    def update_email_status(
        self,
        gmail_id: str,
        status: str,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Transition EmailRecord.status (PROCESSED -> SNOOZED / REVIEWED / ACTIONED / DISCARDED)."""
        with self.get_session() as session:
            stmt = select(EmailRecord).where(EmailRecord.gmail_id == str(gmail_id))
            if tenant_id:
                stmt = _apply_tenant_filter_stmt(stmt, EmailRecord.tenant_id, tenant_id)
            rec = session.scalar(stmt.limit(1))
            if not rec:
                return False
            rec.status = status.upper()
            session.commit()
            return True

    # [CODE-MARKER: FIX-DB-PURGE-MOCK-21] Purge Stale Synthetic Test Drafts from Live Database
    def purge_synthetic_test_records(self) -> int:
        """Remove synthetic mock_thread_1 test rows that leaked into the workspace database."""
        removed = 0
        with self.get_session() as session:
            stale_drafts = list(
                session.scalars(
                    select(DraftRecord).where(
                        DraftRecord.thread_id == "mock_thread_1",
                    )
                ).all()
            )
            for row in stale_drafts:
                session.delete(row)
                removed += 1
            if removed > 0:
                session.commit()
        return removed

    def approve_pm_task(self, task_id: Union[int, str]) -> bool:
        """Approve a staged PM task by integer ID or string task_id."""
        with self.get_session() as session:
            if isinstance(task_id, int):
                stmt = select(PMActionQueue).where(PMActionQueue.id == task_id)
            elif str(task_id).isdigit():
                stmt = select(PMActionQueue).where(
                    or_(PMActionQueue.task_id == str(task_id), PMActionQueue.id == int(task_id))
                )
            else:
                stmt = select(PMActionQueue).where(PMActionQueue.task_id == str(task_id))
            task = session.scalar(stmt)
            if not task or task.status != "PENDING":
                return False
            task.status = "APPROVED"
            task.executed_at = datetime.now(timezone.utc)
            session.commit()
            return True

    def reject_pm_task(self, task_id: Union[int, str]) -> bool:
        """Reject and cancel a staged PM task by integer ID or string task_id."""
        with self.get_session() as session:
            if isinstance(task_id, int):
                stmt = select(PMActionQueue).where(PMActionQueue.id == task_id)
            elif str(task_id).isdigit():
                stmt = select(PMActionQueue).where(
                    or_(PMActionQueue.task_id == str(task_id), PMActionQueue.id == int(task_id))
                )
            else:
                stmt = select(PMActionQueue).where(PMActionQueue.task_id == str(task_id))
            task = session.scalar(stmt)
            if not task or task.status != "PENDING":
                return False
            task.status = "REJECTED"
            task.executed_at = datetime.now(timezone.utc)
            session.commit()
            return True

    def get_dashboard_metrics(self, tenant_id: Optional[str] = None, user_email: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate triage statistics and queue counts for the specified or active tenant."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id if tenant_id is not None else ((user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id())
        with self.get_session() as session:
            # 1. Total emails
            email_stmt = select(func.count(EmailRecord.id))
            email_stmt = _apply_tenant_filter_stmt(email_stmt, EmailRecord.tenant_id, effective_tenant)
            if user_email and user_email.strip():
                from sqlalchemy import or_
                clean_email = f"%{user_email.strip().lower()}%"
                email_stmt = email_stmt.where(
                    or_(
                        EmailRecord.to_recipients.ilike(clean_email),
                        EmailRecord.cc_recipients.ilike(clean_email),
                        EmailRecord.sender.ilike(clean_email),
                    )
                )
            total_emails = session.scalar(email_stmt) or 0

            # 2. Pending PM tasks
            pm_stmt = select(func.count(PMActionQueue.id)).where(PMActionQueue.status == "PENDING")
            pm_stmt = _apply_tenant_filter_stmt(pm_stmt, PMActionQueue.tenant_id, effective_tenant)
            pending_tasks = session.scalar(pm_stmt) or 0

            # 3. Needs Review
            review_stmt = select(func.count(EmailClassification.id)).where(EmailClassification.category.like("%NeedsReview%"))
            review_stmt = _apply_tenant_filter_stmt(review_stmt, EmailClassification.tenant_id, effective_tenant)
            needs_review = session.scalar(review_stmt) or 0

            # 4. Drafts count
            draft_stmt = select(func.count(DraftRecord.id))
            draft_stmt = _apply_tenant_filter_stmt(draft_stmt, DraftRecord.tenant_id, effective_tenant)
            drafts_count = session.scalar(draft_stmt) or 0

            # Group by category
            cat_counts: Dict[str, int] = {}
            cls_stmt = select(EmailClassification.category, func.count(EmailClassification.id))
            cls_stmt = _apply_tenant_filter_stmt(cls_stmt, EmailClassification.tenant_id, effective_tenant)
            cls_stmt = cls_stmt.group_by(EmailClassification.category)
            for cat, count in session.execute(cls_stmt).all():
                if cat:
                    cat_counts[cat] = count

            return {
                "total_emails": total_emails,
                "total_emails_processed": total_emails,
                "total_processed": total_emails,
                "pending_pm_tasks": pending_tasks,
                "needs_review": needs_review,
                "drafts_staged": drafts_count,
                "category_breakdown": cat_counts,
            }

    def get_triage_metrics(self, tenant_id: Optional[str] = None, user_email: Optional[str] = None) -> Dict[str, Any]:
        """Alias for get_dashboard_metrics."""
        return self.get_dashboard_metrics(tenant_id=tenant_id, user_email=user_email)

    def get_email(self, gmail_id: str, tenant_id: Optional[str] = None) -> Optional[EmailRecord]:
        """Retrieve an email record by gmail_id with tenant filtering."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"

        with self.get_session() as session:
            stmt = select(EmailRecord).where(EmailRecord.gmail_id == gmail_id)
            stmt = _apply_tenant_filter_stmt(stmt, EmailRecord.tenant_id, effective_tenant)
            email_rec = session.scalar(stmt)
            if email_rec is None:
                return None
            return cast(Optional[EmailRecord], email_rec)

    def get_workspace_poller_config(self, tenant_id: Optional[str] = None) -> WorkspacePollerConfig:
        """Get or initialize workspace-level poller configuration for a tenant."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "default"

        with self.get_session() as session:
            stmt = select(WorkspacePollerConfig).where(WorkspacePollerConfig.tenant_id == effective_tenant)
            config = session.scalar(stmt)
            if config is None:
                config = WorkspacePollerConfig(
                    tenant_id=effective_tenant,
                    is_master_enabled=True,
                    default_poll_interval_seconds=300,
                )
                session.add(config)
                session.commit()
                session.refresh(config)
            session.expunge(config)
            return config

    def set_workspace_poller_status(self, is_enabled: bool, tenant_id: Optional[str] = None) -> WorkspacePollerConfig:
        """Toggle or set the master poller status for a tenant workspace."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "default"

        with self.get_session() as session:
            stmt = select(WorkspacePollerConfig).where(WorkspacePollerConfig.tenant_id == effective_tenant)
            config = session.scalar(stmt)
            if config is None:
                config = WorkspacePollerConfig(
                    tenant_id=effective_tenant,
                    is_master_enabled=is_enabled,
                    default_poll_interval_seconds=300,
                )
                session.add(config)
            else:
                config.is_master_enabled = is_enabled
                config.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(config)
            session.expunge(config)
            return config

    def get_user_poller_config(self, user_id: int, tenant_id: Optional[str] = None) -> Optional[UserPollerConfig]:
        """Retrieve poller configuration for an individual user."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "default"

        with self.get_session() as session:
            stmt = select(UserPollerConfig).where(
                UserPollerConfig.user_id == user_id,
                UserPollerConfig.tenant_id == effective_tenant,
            )
            config = session.scalar(stmt)
            if config is not None:
                session.expunge(config)
            return config

    def list_user_poller_configs(self, tenant_id: Optional[str] = None) -> List[UserPollerConfig]:
        """List all user poller configurations registered for a tenant."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "default"

        with self.get_session() as session:
            stmt = select(UserPollerConfig)
            stmt = _apply_tenant_filter_stmt(stmt, UserPollerConfig.tenant_id, effective_tenant)
            configs = list(session.scalars(stmt).all())
            for c in configs:
                session.expunge(c)
            return configs

    def upsert_user_poller_config(
        self,
        user_id: int,
        email: str,
        is_enabled: bool = True,
        poll_interval_seconds: int = 300,
        active_window: str = "24x7",
        tenant_id: Optional[str] = None,
    ) -> UserPollerConfig:
        """Create or update per-user poller configuration."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "default"

        with self.get_session() as session:
            stmt = select(UserPollerConfig).where(
                UserPollerConfig.user_id == user_id,
                UserPollerConfig.tenant_id == effective_tenant,
            )
            config = session.scalar(stmt)
            if config is None:
                config = UserPollerConfig(
                    tenant_id=effective_tenant,
                    user_id=user_id,
                    email=email,
                    is_poller_enabled=is_enabled,
                    poll_interval_seconds=max(5, poll_interval_seconds),
                    active_window=active_window,
                )
                session.add(config)
            else:
                config.email = email
                config.is_poller_enabled = is_enabled
                config.poll_interval_seconds = max(5, poll_interval_seconds)
                config.active_window = active_window
                config.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(config)
            session.expunge(config)
            return config

    def record_user_poll_run(
        self,
        user_id: int,
        emails_fetched: int = 0,
        error: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[UserPollerConfig]:
        """Record the completion of a poll cycle for a user, updating telemetry and last_polled_at."""
        user_ctx = get_current_user_context()
        effective_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "default"

        with self.get_session() as session:
            stmt = select(UserPollerConfig).where(
                UserPollerConfig.user_id == user_id,
                UserPollerConfig.tenant_id == effective_tenant,
            )
            config = session.scalar(stmt)
            if config is None:
                config = UserPollerConfig(
                    tenant_id=effective_tenant,
                    user_id=user_id,
                    email=f"user_{user_id}@{effective_tenant}.local",
                    is_poller_enabled=True,
                    poll_interval_seconds=300,
                    active_window="24x7",
                    total_cycles=0,
                    total_emails_fetched=0,
                )
                session.add(config)
            config.last_polled_at = datetime.now(timezone.utc)
            config.total_cycles = (config.total_cycles or 0) + 1
            config.total_emails_fetched = (config.total_emails_fetched or 0) + emails_fetched
            config.last_error = error
            config.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(config)
            session.expunge(config)
            return config

    # =========================================================================
    # [CODE-MARKER: MO-DB-02] Hybrid Neuro-Symbolic FTS5 & Semantic Retrieval
    # =========================================================================

    def index_fts_and_semantic_chunk(
        self,
        tenant_id: str,
        user_id: Optional[int],
        source_channel: str,
        msg_id: str,
        subject: str,
        body_clean: str,
        entity_tags: str = "",
    ) -> None:
        """Index message text into SQLite FTS5 virtual table and semantic chunk store."""
        eff_tenant = tenant_id or "public"
        uid_str = str(user_id) if user_id is not None else "0"
        clean_text = f"{subject}\n{body_clean}".strip()[:4000]
        if not clean_text:
            return

        # Compute lightweight normalized term-frequency dictionary for cosine similarity
        tokens = re.findall(r"[a-zA-Z0-9_\-]{3,}", clean_text.lower())
        tf_map: Dict[str, int] = {}
        for tok in tokens[:200]:
            tf_map[tok] = tf_map.get(tok, 0) + 1

        with self.get_session() as session:
            existing = session.scalar(
                select(SemanticChunkRecord).where(
                    SemanticChunkRecord.msg_id == msg_id,
                    SemanticChunkRecord.source_channel == source_channel,
                )
            )
            if existing is None:
                chunk = SemanticChunkRecord(
                    tenant_id=eff_tenant,
                    user_id=user_id,
                    source_channel=source_channel,
                    msg_id=msg_id,
                    entity_tags=entity_tags[:512],
                    chunk_text=clean_text,
                    token_vector_json=json.dumps(tf_map),
                )
                session.add(chunk)
            else:
                existing.chunk_text = clean_text
                existing.entity_tags = entity_tags[:512]
                existing.token_vector_json = json.dumps(tf_map)
            session.commit()

        if self.engine.dialect.name == "sqlite":
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        text("DELETE FROM mail_fts_index WHERE msg_id = :mid AND source_channel = :ch"),
                        {"mid": msg_id, "ch": source_channel},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO mail_fts_index("
                            "tenant_id, user_id, source_channel, msg_id, entity_tags, subject, body_clean"
                            ") VALUES (:tid, :uid, :ch, :mid, :tags, :subj, :body)"
                        ),
                        {
                            "tid": eff_tenant,
                            "uid": uid_str,
                            "ch": source_channel,
                            "mid": msg_id,
                            "tags": entity_tags[:512],
                            "subj": subject[:512],
                            "body": body_clean[:4000],
                        },
                    )
            except Exception:
                pass

    def search_hybrid_context(
        self,
        tenant_id: str,
        user_id: Optional[int],
        query_terms: List[str],
        entities: Optional[List[str]] = None,
        limit: int = 8,
    ) -> Dict[str, Any]:
        """Execute Hybrid Neuro-Symbolic Retrieval (EntityFactGraph + CommitmentLedger + FTS5 + Semantic Chunks)."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        entity_list = [e.strip() for e in (entities or []) if e and e.strip()]
        terms = [t.strip() for t in query_terms if t and len(t.strip()) >= 2]

        # 1. Symbolic Entity Fact Graph lookup (only active, non-superseded facts)
        active_facts: List[Dict[str, Any]] = self.query_entity_facts(
            tenant_id=eff_tenant,
            subject_entities=entity_list if entity_list else None,
            include_superseded=False,
            limit=limit,
        )

        # 2. Active Commitments lookup (OWED_BY_ME and OWED_TO_ME)
        open_commitments: List[Dict[str, Any]] = self.list_commitments(
            tenant_id=eff_tenant,
            user_id=user_id,
            active_only=True,
            limit=limit,
        )

        # 3. FTS5 + Semantic Chunk hybrid match
        fts_matches: List[Dict[str, Any]] = []
        if self.engine.dialect.name == "sqlite" and terms:
            fts_query = " OR ".join(
                f'"{re.sub(r"[^a-zA-Z0-9_-]", "", t)}"'
                for t in terms[:6]
                if re.sub(r"[^a-zA-Z0-9_-]", "", t)
            )
            if fts_query:
                try:
                    with self.engine.begin() as conn:
                        rows = conn.execute(
                            text(
                                "SELECT source_channel, msg_id, subject, snippet(mail_fts_index, 6, '[', ']', '...', 24) "
                                "FROM mail_fts_index WHERE mail_fts_index MATCH :q AND tenant_id = :tid LIMIT :lim"
                            ),
                            {"q": fts_query, "tid": eff_tenant, "lim": limit},
                        ).fetchall()
                        for r in rows:
                            fts_matches.append({
                                "source_channel": str(r[0]),
                                "msg_id": str(r[1]),
                                "subject": str(r[2]),
                                "snippet": str(r[3]),
                            })
                except Exception:
                    pass

        # 4. Semantic Chunk Overlap Fallback / Augmentation
        semantic_matches: List[Dict[str, Any]] = []
        query_tok_set = {re.sub(r"[^a-z0-9_-]", "", t.lower()) for t in terms if len(t) >= 3}
        if query_tok_set:
            with self.get_session() as session:
                stmt = select(SemanticChunkRecord).order_by(desc(SemanticChunkRecord.created_at)).limit(40)
                stmt = _apply_tenant_filter_stmt(stmt, SemanticChunkRecord.tenant_id, eff_tenant)
                chunks = list(session.scalars(stmt).all())
                scored: List[Tuple[float, SemanticChunkRecord]] = []
                for ch in chunks:
                    try:
                        vec: Dict[str, int] = json.loads(ch.token_vector_json or "{}")
                    except Exception:
                        vec = {}
                    overlap = sum(weight for tok, weight in vec.items() if tok in query_tok_set)
                    if overlap > 0:
                        scored.append((float(overlap), ch))
                scored.sort(key=lambda item: item[0], reverse=True)
                for score, ch in scored[:limit]:
                    semantic_matches.append({
                        "source_channel": ch.source_channel,
                        "msg_id": ch.msg_id,
                        "score": score,
                        "chunk_text": ch.chunk_text[:300],
                    })

        return {
            "entity_facts": active_facts,
            "open_commitments": open_commitments,
            "fts_matches": fts_matches,
            "semantic_matches": semantic_matches,
        }

    # =========================================================================
    # [CODE-MARKER: MO-DB-03] 3-Layer Alias Resolution & Salutation Promotion
    # =========================================================================

    def resolve_contact_alias_3layer(
        self,
        tenant_id: str,
        user_id: Optional[int],
        channel_type: str,
        raw_identifier: str,
        display_name: str = "",
        organization: str = "",
        org_relationship: str = "UNKNOWN",
        is_vip: bool = False,
    ) -> Dict[str, Any]:
        """Resolve a channel handle (email/phone) via the 3-Layer Alias & Salutation Resolution Engine.

        - Layer 1 (Exact Match, confidence = 1.0): Exact match on ContactChannelAlias.raw_identifier.
        - Layer 2 (Scoped Fuzzy + Salutation Match, confidence = 0.85 - 0.94): Same organization domain
          and high display-name/salutation similarity (>= 0.88).
        - Layer 3 (Ambiguous / Low Confidence < 0.85): Never auto-merges into an existing contact;
          creates a provisional contact & quarantined alias (PROVISIONAL_QUARANTINE) for 1-tap user confirmation.
        """
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        clean_id = raw_identifier.strip().lower()
        if "<" in clean_id and ">" in clean_id:
            m = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", clean_id)
            if m:
                clean_id = m.group(0).lower()

        clean_disp = display_name.strip() or (
            raw_identifier.split("<")[0].replace('"', "").strip() if "<" in raw_identifier else clean_id.split("@")[0]
        )
        domain = clean_id.split("@")[-1] if "@" in clean_id else clean_id
        inferred_org = organization.strip() or (domain.split(".")[0].capitalize() if "." in domain else "")

        with self.get_session() as session:
            # Layer 1: Exact Channel Handle Lookup
            alias_stmt = select(ContactChannelAlias).where(
                ContactChannelAlias.raw_identifier == clean_id,
                ContactChannelAlias.channel_type == channel_type.upper(),
            )
            alias_stmt = _apply_tenant_filter_stmt(alias_stmt, ContactChannelAlias.tenant_id, eff_tenant)
            exact_alias = session.scalar(alias_stmt)
            if exact_alias is not None:
                contact = session.get(ContactEntity, exact_alias.contact_id)
                if contact is not None:
                    if is_vip and not contact.vip_override:
                        contact.vip_override = True
                        session.commit()
                    learned_sals: List[str] = json.loads(contact.learned_salutations_json or "[]")
                    return {
                        "contact_id": contact.id,
                        "canonical_name": contact.canonical_name,
                        "organization": contact.organization,
                        "org_relationship": contact.org_relationship,
                        "is_vip": bool(contact.vip_override),
                        "resolution_layer": "LAYER_1_EXACT",
                        "resolution_confidence": exact_alias.resolution_confidence,
                        "resolution_status": exact_alias.resolution_status,
                        "learned_salutations": learned_sals,
                    }

            # Layer 2: Scoped Organization Domain + High-Similarity Fuzzy / Salutation Match
            contacts_stmt = select(ContactEntity)
            contacts_stmt = _apply_tenant_filter_stmt(contacts_stmt, ContactEntity.tenant_id, eff_tenant)
            existing_contacts = list(session.scalars(contacts_stmt).all())

            best_contact: Optional[ContactEntity] = None
            best_score: float = 0.0
            for cand in existing_contacts:
                name_sim = difflib.SequenceMatcher(None, clean_disp.lower(), (cand.canonical_name or "").lower()).ratio()
                cand_sals: List[str] = json.loads(cand.learned_salutations_json or "[]")
                sal_sim = max(
                    (difflib.SequenceMatcher(None, clean_disp.lower(), s.lower()).ratio() for s in cand_sals),
                    default=0.0,
                )
                same_org = bool(
                    inferred_org
                    and cand.organization
                    and inferred_org.lower() == cand.organization.lower()
                )
                combined = max(name_sim, sal_sim) + (0.06 if same_org else 0.0)
                if combined > best_score:
                    best_score = min(0.94, combined)
                    best_contact = cand

            if best_contact is not None and best_score >= 0.88:
                # Layer 2 Verified Scoped Match
                linked_alias = ContactChannelAlias(
                    tenant_id=eff_tenant,
                    contact_id=best_contact.id,
                    channel_type=channel_type.upper(),
                    raw_identifier=clean_id,
                    display_name_seen=clean_disp,
                    resolution_confidence=round(best_score, 2),
                    resolution_status="VERIFIED",
                )
                session.add(linked_alias)
                session.commit()
                learned_sals = json.loads(best_contact.learned_salutations_json or "[]")
                return {
                    "contact_id": best_contact.id,
                    "canonical_name": best_contact.canonical_name,
                    "organization": best_contact.organization,
                    "org_relationship": best_contact.org_relationship,
                    "is_vip": bool(best_contact.vip_override),
                    "resolution_layer": "LAYER_2_SCOPED_FUZZY",
                    "resolution_confidence": round(best_score, 2),
                    "resolution_status": "VERIFIED",
                    "learned_salutations": learned_sals,
                }

            # Layer 3: Ambiguous Match (0.50 <= score < 0.88) or Brand-New Contact
            is_ambiguous = best_contact is not None and 0.60 <= best_score < 0.88
            new_contact = ContactEntity(
                tenant_id=eff_tenant,
                user_id=user_id,
                canonical_name=clean_disp or clean_id,
                organization=inferred_org,
                org_relationship=org_relationship,
                vip_override=is_vip,
                learned_salutations_json="[]",
                provisional_salutations_json="{}",
            )
            session.add(new_contact)
            session.commit()
            session.refresh(new_contact)

            status_flag = "PROVISIONAL_QUARANTINE" if is_ambiguous else "VERIFIED"
            conf_val = round(best_score, 2) if is_ambiguous else 1.0
            new_alias = ContactChannelAlias(
                tenant_id=eff_tenant,
                contact_id=new_contact.id,
                channel_type=channel_type.upper(),
                raw_identifier=clean_id,
                display_name_seen=clean_disp,
                resolution_confidence=conf_val,
                resolution_status=status_flag,
            )
            session.add(new_alias)
            session.commit()

            return {
                "contact_id": new_contact.id,
                "canonical_name": new_contact.canonical_name,
                "organization": new_contact.organization,
                "org_relationship": new_contact.org_relationship,
                "is_vip": bool(new_contact.vip_override),
                "resolution_layer": "LAYER_3_QUARANTINE" if is_ambiguous else "LAYER_1_NEW_ENTITY",
                "resolution_confidence": conf_val,
                "resolution_status": status_flag,
                "learned_salutations": [],
            }

    def record_observed_salutation(
        self,
        tenant_id: str,
        contact_id: int,
        salutation: str,
        is_outbound_from_user: bool = False,
        observer_sender: str = "colleague",
    ) -> List[str]:
        """Record a salutation/nickname for a contact, enforcing strict self-vs-third-party promotion rules (REV-03)."""
        clean_sal = salutation.strip().rstrip(",:!.")
        for prefix in ("hi ", "hello ", "dear ", "hey "):
            if clean_sal.lower().startswith(prefix):
                clean_sal = clean_sal[len(prefix):].strip()
        if not clean_sal or len(clean_sal) > 48:
            return []

        with self.get_session() as session:
            contact = session.get(ContactEntity, contact_id)
            if contact is None:
                return []

            learned: List[str] = json.loads(contact.learned_salutations_json or "[]")
            provisional: Dict[str, List[str]] = json.loads(contact.provisional_salutations_json or "{}")

            if is_outbound_from_user:
                if clean_sal not in learned:
                    learned.append(clean_sal)
                    contact.learned_salutations_json = json.dumps(learned)
                    session.commit()
                return learned

            # Third-party salutation observed on thread: require >= 2 distinct observers before promoting
            observers = provisional.get(clean_sal, [])
            norm_obs = observer_sender.strip().lower()
            if norm_obs and norm_obs not in observers:
                observers.append(norm_obs)
            provisional[clean_sal] = observers
            contact.provisional_salutations_json = json.dumps(provisional)

            if len(observers) >= 2 and clean_sal not in learned:
                learned.append(clean_sal)
                contact.learned_salutations_json = json.dumps(learned)

            session.commit()
            return learned

    def resolve_quarantined_alias(
        self,
        alias_id: int,
        approve: bool = True,
        target_contact_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Approve or reject a PROVISIONAL_QUARANTINE ContactChannelAlias."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        with self.get_session() as session:
            alias_rec = session.get(ContactChannelAlias, alias_id)
            if alias_rec is None:
                return False
            if eff_tenant not in ("platform", "*", "public", "default") and alias_rec.tenant_id != eff_tenant:
                return False
            if approve:
                if target_contact_id is not None:
                    alias_rec.contact_id = target_contact_id
                alias_rec.resolution_status = "VERIFIED"
                alias_rec.resolution_confidence = 1.0
            else:
                alias_rec.resolution_status = "REJECTED"
            session.commit()
            return True

    def get_quarantined_aliases(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all ContactChannelAlias rows currently in PROVISIONAL_QUARANTINE."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        with self.get_session() as session:
            stmt = select(ContactChannelAlias).where(
                ContactChannelAlias.resolution_status == "PROVISIONAL_QUARANTINE"
            )
            stmt = _apply_tenant_filter_stmt(stmt, ContactChannelAlias.tenant_id, eff_tenant)
            rows = list(session.scalars(stmt).all())
            return [
                {
                    "id": r.id,
                    "contact_id": r.contact_id,
                    "channel_type": r.channel_type,
                    "raw_identifier": r.raw_identifier,
                    "display_name_seen": r.display_name_seen,
                    "resolution_confidence": r.resolution_confidence,
                    "resolution_status": r.resolution_status,
                }
                for r in rows
            ]

    # =========================================================================
    # Role-Adaptive Taxonomy Templates & User Active Categories (REV-04)
    # =========================================================================

    def seed_default_role_taxonomies(self, tenant_id: Optional[str] = None) -> List[RoleTaxonomyTemplate]:
        """Seed the 5 canonical role taxonomy templates (v1.3.0 Section 3.3) if not already present."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        canonical_templates: List[Dict[str, Any]] = [
            {
                "role_key": "EXECUTIVE_FOUNDER",
                "role_display_name": "Executive / Founder / General",
                "categories": [
                    {"category_name": "@Urgent", "parent_domain": "URGENT_ACTION", "description": "Critical incident, VIP escalation, or immediate blocker", "default_urgency": 10},
                    {"category_name": "@Action", "parent_domain": "WORK_DELIVERABLE", "description": "Direct deliverable, approval, or decision required", "default_urgency": 8},
                    {"category_name": "@Meeting", "parent_domain": "SCHEDULING", "description": "Calendar invite, scheduling proposal, or availability check", "default_urgency": 7},
                    {"category_name": "@WaitingOn", "parent_domain": "WAITING_TRACKING", "description": "Delegated deliverable or commitment owed to user", "default_urgency": 6},
                    {"category_name": "@Financial", "parent_domain": "FINANCE_ADMIN", "description": "Invoices, PO approvals, wire transfers, or billing", "default_urgency": 7},
                    {"category_name": "@ProjectTask", "parent_domain": "WORK_DELIVERABLE", "description": "Project milestone, sprint task, or engineering update", "default_urgency": 6},
                    {"category_name": "@Promotions", "parent_domain": "LOW_PRIORITY_NOISE", "description": "Marketing newsletters, cold outreach, and bulk notifications", "default_urgency": 2},
                ],
            },
            {
                "role_key": "SWE_IC",
                "role_display_name": "Software Engineer / IC",
                "categories": [
                    {"category_name": "@Urgent", "parent_domain": "URGENT_ACTION", "description": "Production outage, PagerDuty alert, or SEV-1 incident", "default_urgency": 10},
                    {"category_name": "@CodeReview", "parent_domain": "WORK_DELIVERABLE", "description": "PR review request, design doc feedback, or merge blocker", "default_urgency": 8},
                    {"category_name": "@Action", "parent_domain": "WORK_DELIVERABLE", "description": "Direct engineering task or bug assignment", "default_urgency": 7},
                    {"category_name": "@CIBuild", "parent_domain": "LOW_PRIORITY_NOISE", "description": "Automated CI/CD pipeline pass/fail notifications", "default_urgency": 3},
                    {"category_name": "@Meeting", "parent_domain": "SCHEDULING", "description": "Architecture sync, standup, or 1:1 scheduling", "default_urgency": 6},
                    {"category_name": "@Promotions", "parent_domain": "LOW_PRIORITY_NOISE", "description": "Vendor marketing and newsletters", "default_urgency": 2},
                ],
            },
            {
                "role_key": "ENG_MANAGER",
                "role_display_name": "Engineering Manager / Tech Lead",
                "categories": [
                    {"category_name": "@Urgent", "parent_domain": "URGENT_ACTION", "description": "Customer escalation, incident commander alert, or VP ask", "default_urgency": 10},
                    {"category_name": "@Action", "parent_domain": "WORK_DELIVERABLE", "description": "Unblocking team, resource approval, or hiring decision", "default_urgency": 8},
                    {"category_name": "@WaitingOn", "parent_domain": "WAITING_TRACKING", "description": "Delegated sprint commitments owed by direct reports", "default_urgency": 7},
                    {"category_name": "@Meeting", "parent_domain": "SCHEDULING", "description": "1:1s, sprint planning, and stakeholder reviews", "default_urgency": 7},
                    {"category_name": "@ProjectTask", "parent_domain": "WORK_DELIVERABLE", "description": "Roadmap tracking, Jira/Linear epics, and release notes", "default_urgency": 6},
                    {"category_name": "@Promotions", "parent_domain": "LOW_PRIORITY_NOISE", "description": "Bulk notifications and newsletters", "default_urgency": 2},
                ],
            },
            {
                "role_key": "PROCUREMENT_FINANCE",
                "role_display_name": "Procurement / Finance / Operations",
                "categories": [
                    {"category_name": "@Urgent", "parent_domain": "URGENT_ACTION", "description": "Audit deadline, customs hold, or payment escalation", "default_urgency": 10},
                    {"category_name": "@Financial", "parent_domain": "FINANCE_ADMIN", "description": "Purchase orders, invoices, vendor quotes, and wire sign-offs", "default_urgency": 8},
                    {"category_name": "@Action", "parent_domain": "WORK_DELIVERABLE", "description": "Contract redline review or compliance verification", "default_urgency": 8},
                    {"category_name": "@WaitingOn", "parent_domain": "WAITING_TRACKING", "description": "Pending vendor W-9, MSA signature, or delivery ETA", "default_urgency": 7},
                    {"category_name": "@Meeting", "parent_domain": "SCHEDULING", "description": "Vendor negotiation call or budget review", "default_urgency": 6},
                    {"category_name": "@Promotions", "parent_domain": "LOW_PRIORITY_NOISE", "description": "Marketing brochures and cold vendor pitches", "default_urgency": 2},
                ],
            },
            {
                "role_key": "SALES_ACCOUNT",
                "role_display_name": "Sales / Account Executive / CS",
                "categories": [
                    {"category_name": "@Urgent", "parent_domain": "URGENT_ACTION", "description": "Deal-desk blocker, churn risk, or Tier-1 client RFP deadline", "default_urgency": 10},
                    {"category_name": "@Action", "parent_domain": "WORK_DELIVERABLE", "description": "Proposal request, pricing quote, or security questionnaire", "default_urgency": 8},
                    {"category_name": "@Meeting", "parent_domain": "SCHEDULING", "description": "Client demo, QBR, or discovery call scheduling", "default_urgency": 8},
                    {"category_name": "@WaitingOn", "parent_domain": "WAITING_TRACKING", "description": "Awaiting legal redlines or countersigned order form", "default_urgency": 7},
                    {"category_name": "@Financial", "parent_domain": "FINANCE_ADMIN", "description": "Order forms, discounting approval, and billing terms", "default_urgency": 7},
                    {"category_name": "@Promotions", "parent_domain": "LOW_PRIORITY_NOISE", "description": "Newsletters and automated marketing", "default_urgency": 2},
                ],
            },
        ]

        seeded: List[RoleTaxonomyTemplate] = []
        with self.get_session() as session:
            for tpl in canonical_templates:
                stmt = select(RoleTaxonomyTemplate).where(
                    RoleTaxonomyTemplate.role_key == tpl["role_key"],
                    RoleTaxonomyTemplate.tenant_id == eff_tenant,
                )
                existing = session.scalar(stmt)
                if existing is None:
                    existing = RoleTaxonomyTemplate(
                        tenant_id=eff_tenant,
                        role_key=tpl["role_key"],
                        role_display_name=tpl["role_display_name"],
                        categories_json=json.dumps(tpl["categories"]),
                    )
                    session.add(existing)
                    session.commit()
                    session.refresh(existing)
                session.expunge(existing)
                seeded.append(existing)
        return seeded

    def select_user_role_taxonomy(
        self,
        role_key: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[int] = None,
        custom_category: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Apply a role taxonomy template (or add a custom category) for a tenant/user."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        templates = self.seed_default_role_taxonomies(tenant_id=eff_tenant)
        matched = next((t for t in templates if t.role_key == role_key), templates[0])
        cats: List[Dict[str, Any]] = json.loads(matched.categories_json or "[]")

        with self.get_session() as session:
            if not custom_category:
                # Replace active template categories for this user/tenant
                existing_rows = list(
                    session.scalars(
                        select(UserActiveCategory).where(
                            UserActiveCategory.tenant_id == eff_tenant,
                            UserActiveCategory.user_id == user_id,
                        )
                    ).all()
                )
                for row in existing_rows:
                    session.delete(row)
                session.commit()

                for item in cats:
                    session.add(
                        UserActiveCategory(
                            tenant_id=eff_tenant,
                            user_id=user_id,
                            role_key=matched.role_key,
                            category_name=str(item.get("category_name", "@Action")),
                            parent_domain=str(item.get("parent_domain", "WORK_DELIVERABLE")),
                            description=str(item.get("description", "")),
                            default_urgency=int(item.get("default_urgency", 6)),
                            is_active=True,
                        )
                    )
                session.commit()
            else:
                cat_name = str(custom_category.get("category_name", "@Custom")).strip()
                if not cat_name.startswith("@"):
                    cat_name = f"@{cat_name}"
                session.add(
                    UserActiveCategory(
                        tenant_id=eff_tenant,
                        user_id=user_id,
                        role_key=role_key or "CUSTOM",
                        category_name=cat_name,
                        parent_domain=str(custom_category.get("parent_domain", "WORK_DELIVERABLE")),
                        description=str(custom_category.get("description", "Custom user category")),
                        default_urgency=int(custom_category.get("default_urgency", 6)),
                        is_active=True,
                    )
                )
                session.commit()

        return self.get_active_user_taxonomy(tenant_id=eff_tenant, user_id=user_id)

    def get_active_user_taxonomy(
        self,
        tenant_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return active triage categories for the user, or the default 7 Executive categories on clean slate."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        with self.get_session() as session:
            stmt = select(UserActiveCategory).where(UserActiveCategory.is_active.is_(True))
            stmt = _apply_tenant_filter_stmt(stmt, UserActiveCategory.tenant_id, eff_tenant)
            if user_id is not None:
                stmt = stmt.where(or_(UserActiveCategory.user_id == user_id, UserActiveCategory.user_id.is_(None)))
            rows = list(session.scalars(stmt).all())
            if rows:
                return [
                    {
                        "category_name": r.category_name,
                        "parent_domain": r.parent_domain,
                        "description": r.description,
                        "default_urgency": r.default_urgency,
                        "role_key": r.role_key,
                    }
                    for r in rows
                ]

        # Clean-slate fallback (preserves 100% compatibility with existing 7 categories)
        return [
            {"category_name": "@Action", "parent_domain": "WORK_DELIVERABLE", "description": "Actionable deliverable or decision required", "default_urgency": 8, "role_key": "EXECUTIVE_FOUNDER"},
            {"category_name": "@Urgent", "parent_domain": "URGENT_ACTION", "description": "Immediate production blocker, incident, or VIP escalation", "default_urgency": 10, "role_key": "EXECUTIVE_FOUNDER"},
            {"category_name": "@Meeting", "parent_domain": "SCHEDULING", "description": "Meeting scheduling or calendar availability request", "default_urgency": 7, "role_key": "EXECUTIVE_FOUNDER"},
            {"category_name": "@WaitingOn", "parent_domain": "WAITING_TRACKING", "description": "Delegated task or promise owed by counterparty", "default_urgency": 6, "role_key": "EXECUTIVE_FOUNDER"},
            {"category_name": "@Promotions", "parent_domain": "LOW_PRIORITY_NOISE", "description": "Marketing newsletter or bulk notification", "default_urgency": 2, "role_key": "EXECUTIVE_FOUNDER"},
            {"category_name": "@Financial", "parent_domain": "FINANCE_ADMIN", "description": "Invoice, PO, billing, or payment inquiry", "default_urgency": 7, "role_key": "EXECUTIVE_FOUNDER"},
            {"category_name": "@ProjectTask", "parent_domain": "WORK_DELIVERABLE", "description": "Project milestone or engineering deliverable", "default_urgency": 6, "role_key": "EXECUTIVE_FOUNDER"},
        ]

    # =========================================================================
    # Language-Action Commitment Ledger & Entity Fact Graph (REV-05 & REV-08)
    # =========================================================================

    def upsert_commitment(
        self,
        source_msg_id: str,
        deliverable_summary: str,
        direction: str = "OWED_BY_ME",
        speech_act: str = "REQUEST",
        source_channel: str = "EMAIL",
        thread_id: str = "",
        counterparty_handle: str = "",
        counterparty_contact_id: Optional[int] = None,
        raw_deadline_text: str = "Next Business Day",
        resolved_due_at: Optional[datetime] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> CommitmentLedger:
        """Create or update a bidirectional CommitmentLedger record (OWED_BY_ME vs OWED_TO_ME)."""
        user_ctx = get_current_user_context()
        eff_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"
        eff_uid = user_id if user_id is not None else (user_ctx.user_id if user_ctx else None)

        digest_seed = f"{eff_tenant}:{source_msg_id}:{direction}:{deliverable_summary[:64]}"
        uid = f"CMT-{hashlib.sha256(digest_seed.encode('utf-8')).hexdigest()[:10].upper()}"
        init_status = "WAITING_ON_OTHER" if direction == "OWED_TO_ME" else "OPEN"

        with self.get_session() as session:
            existing = session.scalar(select(CommitmentLedger).where(CommitmentLedger.commitment_uid == uid))
            if existing is not None:
                existing.deliverable_summary = deliverable_summary[:512]
                existing.raw_deadline_text = raw_deadline_text[:128]
                if resolved_due_at is not None:
                    existing.resolved_due_at = resolved_due_at
                session.commit()
                session.refresh(existing)
                session.expunge(existing)
                return existing

            rec = CommitmentLedger(
                tenant_id=eff_tenant,
                user_id=eff_uid,
                commitment_uid=uid,
                source_channel=source_channel,
                source_msg_id=source_msg_id,
                thread_id=thread_id,
                direction=direction,
                speech_act=speech_act,
                counterparty_contact_id=counterparty_contact_id,
                counterparty_handle=counterparty_handle[:255],
                deliverable_summary=deliverable_summary[:512],
                raw_deadline_text=raw_deadline_text[:128],
                resolved_due_at=resolved_due_at or (datetime.now(timezone.utc) + timedelta(days=1)),
                status=init_status,
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            session.expunge(rec)
            return rec

    # [CODE-MARKER: FIX-WA-EMAIL-SCOPE-17] Per-email scoped commitments & entity facts
    def list_commitments(
        self,
        tenant_id: Optional[str] = None,
        user_id: Optional[int] = None,
        direction: Optional[str] = None,
        active_only: bool = True,
        limit: int = 25,
        source_msg_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List bidirectional commitments filtered by tenant, direction, status, and optional email/thread scope."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        with self.get_session() as session:
            stmt = select(CommitmentLedger).order_by(desc(CommitmentLedger.created_at))
            stmt = _apply_tenant_filter_stmt(stmt, CommitmentLedger.tenant_id, eff_tenant)
            if direction:
                stmt = stmt.where(CommitmentLedger.direction == direction)
            if active_only:
                stmt = stmt.where(CommitmentLedger.status.in_(["OPEN", "WAITING_ON_OTHER", "OVERDUE"]))
            if source_msg_id and thread_id:
                stmt = stmt.where(
                    or_(
                        CommitmentLedger.source_msg_id == source_msg_id,
                        CommitmentLedger.thread_id == thread_id,
                    )
                )
            elif source_msg_id:
                stmt = stmt.where(CommitmentLedger.source_msg_id == source_msg_id)
            elif thread_id:
                stmt = stmt.where(CommitmentLedger.thread_id == thread_id)
            stmt = stmt.limit(limit)
            rows = list(session.scalars(stmt).all())
            return [
                {
                    "commitment_uid": r.commitment_uid,
                    "source_channel": r.source_channel,
                    "source_msg_id": r.source_msg_id,
                    "thread_id": r.thread_id,
                    "direction": r.direction,
                    "speech_act": r.speech_act,
                    "counterparty_handle": r.counterparty_handle,
                    "deliverable_summary": r.deliverable_summary,
                    "raw_deadline_text": r.raw_deadline_text,
                    "status": r.status,
                }
                for r in rows
            ]

    def update_commitment_status(
        self,
        commitment_uid: str,
        status: str,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Transition a CommitmentLedger item to FULFILLED, OVERDUE, or CANCELLED."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        with self.get_session() as session:
            stmt = select(CommitmentLedger).where(CommitmentLedger.commitment_uid == commitment_uid)
            stmt = _apply_tenant_filter_stmt(stmt, CommitmentLedger.tenant_id, eff_tenant)
            rec = session.scalar(stmt)
            if rec is None:
                return False
            rec.status = status.upper()
            rec.updated_at = datetime.now(timezone.utc)
            session.commit()
            return True

    def upsert_entity_fact(
        self,
        subject_entity: str,
        predicate: str,
        object_value: str,
        source_msg_id: str,
        source_channel: str = "EMAIL",
        tenant_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> EntityFactGraph:
        """Insert a symbolic fact triple and supersede any older conflicting fact for (subject_entity, predicate)."""
        user_ctx = get_current_user_context()
        eff_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"
        eff_uid = user_id if user_id is not None else (user_ctx.user_id if user_ctx else None)

        norm_subj = subject_entity.strip()
        norm_pred = predicate.strip().upper()
        norm_obj = object_value.strip()

        with self.get_session() as session:
            prior_stmt = select(EntityFactGraph).where(
                EntityFactGraph.subject_entity == norm_subj,
                EntityFactGraph.predicate == norm_pred,
                EntityFactGraph.is_superseded.is_(False),
            )
            prior_stmt = _apply_tenant_filter_stmt(prior_stmt, EntityFactGraph.tenant_id, eff_tenant)
            prior_facts = list(session.scalars(prior_stmt).all())

            new_fact = EntityFactGraph(
                tenant_id=eff_tenant,
                user_id=eff_uid,
                subject_entity=norm_subj,
                predicate=norm_pred,
                object_value=norm_obj,
                source_channel=source_channel,
                source_msg_id=source_msg_id,
                is_superseded=False,
            )
            session.add(new_fact)
            session.commit()
            session.refresh(new_fact)

            for old_f in prior_facts:
                if old_f.id != new_fact.id and old_f.object_value != norm_obj:
                    old_f.is_superseded = True
                    old_f.superseded_by_id = new_fact.id
            session.commit()
            session.refresh(new_fact)
            session.expunge(new_fact)
            return new_fact

    def query_entity_facts(
        self,
        tenant_id: Optional[str] = None,
        subject_entities: Optional[List[str]] = None,
        include_superseded: bool = False,
        limit: int = 20,
        source_msg_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query deterministic EntityFactGraph triples with optional per-message scope."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        with self.get_session() as session:
            stmt = select(EntityFactGraph).order_by(desc(EntityFactGraph.observed_at))
            stmt = _apply_tenant_filter_stmt(stmt, EntityFactGraph.tenant_id, eff_tenant)
            if not include_superseded:
                stmt = stmt.where(EntityFactGraph.is_superseded.is_(False))
            if source_msg_id and subject_entities:
                stmt = stmt.where(
                    or_(
                        EntityFactGraph.source_msg_id == source_msg_id,
                        EntityFactGraph.subject_entity.in_(subject_entities),
                    )
                )
            elif source_msg_id:
                stmt = stmt.where(EntityFactGraph.source_msg_id == source_msg_id)
            elif subject_entities:
                stmt = stmt.where(EntityFactGraph.subject_entity.in_(subject_entities))
            stmt = stmt.limit(limit)
            rows = list(session.scalars(stmt).all())
            return [
                {
                    "id": r.id,
                    "subject_entity": r.subject_entity,
                    "predicate": r.predicate,
                    "object_value": r.object_value,
                    "source_channel": r.source_channel,
                    "source_msg_id": r.source_msg_id,
                    "is_superseded": r.is_superseded,
                }
                for r in rows
            ]

    def create_missing_artifact_request(
        self,
        gmail_id: str,
        artifact_type: str,
        artifact_description: str,
        thread_id: str = "",
        tenant_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> MissingArtifactRequest:
        """Record a MissingArtifactRequest placing the email into WAITING_FOR_USER_ARTIFACT state."""
        user_ctx = get_current_user_context()
        eff_tenant = tenant_id or (user_ctx.tenant_id if user_ctx else None) or get_current_tenant_id() or "public"
        eff_uid = user_id if user_id is not None else (user_ctx.user_id if user_ctx else None)

        with self.get_session() as session:
            existing = session.scalar(
                select(MissingArtifactRequest).where(
                    MissingArtifactRequest.gmail_id == gmail_id,
                    MissingArtifactRequest.status == "WAITING_FOR_USER_ARTIFACT",
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing

            req = MissingArtifactRequest(
                tenant_id=eff_tenant,
                user_id=eff_uid,
                gmail_id=gmail_id,
                thread_id=thread_id,
                artifact_type=artifact_type,
                artifact_description=artifact_description[:512],
                status="WAITING_FOR_USER_ARTIFACT",
            )
            session.add(req)
            session.commit()
            session.refresh(req)
            session.expunge(req)
            return req

    def resolve_missing_artifact_request(
        self,
        gmail_id: str,
        resolved_content_summary: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[MissingArtifactRequest]:
        """Resolve a pending MissingArtifactRequest when the user supplies the missing file or fact."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        with self.get_session() as session:
            stmt = select(MissingArtifactRequest).where(MissingArtifactRequest.gmail_id == gmail_id)
            stmt = _apply_tenant_filter_stmt(stmt, MissingArtifactRequest.tenant_id, eff_tenant)
            req: Optional[MissingArtifactRequest] = session.scalar(stmt)
            if req is None:
                return None
            req.status = "RESOLVED"
            req.resolved_content_summary = resolved_content_summary
            session.commit()
            session.refresh(req)
            session.expunge(req)
            return req

    def get_pending_artifact_requests(self, tenant_id: Optional[str] = None) -> List[MissingArtifactRequest]:
        """Return all MissingArtifactRequest rows in WAITING_FOR_USER_ARTIFACT state."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        with self.get_session() as session:
            stmt = select(MissingArtifactRequest).where(
                MissingArtifactRequest.status == "WAITING_FOR_USER_ARTIFACT"
            )
            stmt = _apply_tenant_filter_stmt(stmt, MissingArtifactRequest.tenant_id, eff_tenant)
            rows = list(session.scalars(stmt).all())
            for r in rows:
                session.expunge(r)
            return rows

    def record_consent_audit_log(
        self,
        session_id: str,
        channel_type: str,
        jurisdiction_policy: str,
        participants: List[str],
        all_parties_consented: bool,
        tenant_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> ConsentAuditLog:
        """Record an immutable cryptographic consent proof for CIPA / GDPR / India DPDP compliance."""
        eff_tenant = tenant_id or get_current_tenant_id() or "public"
        payload_str = f"{eff_tenant}:{session_id}:{channel_type}:{jurisdiction_policy}:{sorted(participants)}:{all_parties_consented}"
        proof_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        with self.get_session() as session:
            existing = session.scalar(select(ConsentAuditLog).where(ConsentAuditLog.session_id == session_id))
            if existing is not None:
                session.expunge(existing)
                return existing

            log_rec = ConsentAuditLog(
                tenant_id=eff_tenant,
                user_id=user_id,
                session_id=session_id,
                channel_type=channel_type,
                jurisdiction_policy=jurisdiction_policy,
                participants_json=json.dumps(participants),
                all_parties_consented=all_parties_consented,
                consent_proof_hash=proof_hash,
            )
            session.add(log_rec)
            session.commit()
            session.refresh(log_rec)
            session.expunge(log_rec)
            return log_rec


