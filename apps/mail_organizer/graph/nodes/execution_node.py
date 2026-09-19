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
Execution Gate & Regulatory Telemetry Node (`execution_node`).

Adheres strictly to GEES v1.0 and Plan 04 v1.0.
Executes or stages actions according to operating mode:
  - `shadow`: Audit-only logging with SHA-256 hash chaining (Zero mutation).
  - `assistive`: Stages drafts and queues PM tasks in DB for human approval.
  - `autonomous`: Commits directly to Gmail & Calendar.
Contemporaneously streams audit trail to AuditEngine.
"""

import time
from typing import Any, Dict, List, Optional

from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.graph.state import MailOrganizerState
from core_platform.app.telemetry.audit_engine import AuditEngine


async def execution_node(
    state: MailOrganizerState,
    db_service: Optional[MailDatabaseService] = None,
    gmail_connector: Optional[GmailConnector] = None,
    audit_engine: Optional[AuditEngine] = None,
    execution_mode: str = "assistive",
) -> MailOrganizerState:
    """Execute or stage actions and stream compliance audit records."""
    t0 = time.perf_counter()

    mode: str = str(state.get("execution_mode") or execution_mode)
    actions_planned: List[Dict[str, Any]] = list(state.get("gmail_actions") or [])
    pm_tasks: List[Dict[str, Any]] = list(state.get("pending_pm_tasks") or [])
    gmail_id: str = str(state.get("gmail_id") or "GMAIL-UNKNOWN")
    thread_id: str = str(state.get("thread_id") or "THREAD-UNKNOWN")
    subject: str = str(state.get("subject") or "")
    sender: str = str(state.get("sender") or "")
    category: str = str(state.get("category") or "@Action")
    urgency_score: int = int(state.get("urgency_score") or 5)
    confidence_score: float = float(state.get("confidence_score") or 1.0)
    suggested_reply: Optional[str] = state.get("suggested_reply")
    snippet: str = str(state.get("snippet") or "")
    body: str = str(state.get("body") or "")
    context_tags: List[str] = list(state.get("context_tags") or [])
    is_reply_necessary: bool = bool(state.get("is_reply_necessary", False))
    responsibility_role: str = str(state.get("responsibility_role") or "PRIMARY_ACTIONEE")
    safety_override: bool = bool(state.get("safety_override", False))

    actions_executed: List[Dict[str, Any]] = []

    # 1. Database persistence
    if db_service:
        db_service.store_email(
            gmail_id=gmail_id,
            thread_id=thread_id,
            subject=subject,
            sender=sender,
            snippet=snippet,
            body=body,
            labels_applied=",".join([str(a.get("label", "")) for a in actions_planned if a.get("action") == "apply_label"]),
        )
        db_service.store_classification(
            gmail_id=gmail_id,
            category=category,
            urgency_score=urgency_score,
            confidence_score=confidence_score,
            reasoning=str(state.get("reasoning") or ""),
            context_tags=",".join(context_tags),
            is_reply_necessary=is_reply_necessary,
            responsibility_role=responsibility_role,
            suggested_reply=suggested_reply,
        )

    # 2. Execution branching
    if mode == "shadow":
        # Zero mutation: log only
        actions_executed.append({
            "action": "shadow_audit_logged",
            "mode": "shadow",
            "actions_planned": actions_planned,
        })
    else:
        # Assistive or Autonomous mode
        # Apply labels via Gmail connector
        if gmail_connector:
            add_labels = [str(a["label"]) for a in actions_planned if a.get("action") == "apply_label" and "label" in a]
            rem_labels = [str(a["label"]) for a in actions_planned if a.get("action") == "remove_label" and "label" in a]
            try:
                await gmail_connector.apply_labels(gmail_id, add_labels=add_labels, remove_labels=rem_labels)
                actions_executed.append({
                    "action": "labels_applied",
                    "added": add_labels,
                    "removed": rem_labels,
                })
            except Exception as _gmail_exc:
                import logging as _logging
                _logging.getLogger("mail_organizer.execution_node").error(
                    "[E-DOWN-001] Gmail label apply failed for gmail_id=%s — queuing to outbox. Error: %s",
                    gmail_id, _gmail_exc,
                )
                # Enqueue failed Gmail action to platform outbox for retry.
                try:
                    from core_platform.app.outbox.queue import PlatformOutboxQueue
                    _outbox = PlatformOutboxQueue()
                    _outbox.enqueue(
                        app_id="mail_organizer",
                        target="gmail_api",
                        payload={
                            "action": "apply_labels",
                            "gmail_id": gmail_id,
                            "add_labels": add_labels,
                            "remove_labels": rem_labels,
                        },
                    )
                except Exception:
                    pass
                actions_executed.append({
                    "action": "labels_queued_outbox",
                    "error": str(_gmail_exc),
                })

            # Stage draft in Gmail
            if suggested_reply:
                draft_res = await gmail_connector.create_draft(
                    thread_id=thread_id,
                    recipient=sender,
                    subject=f"Re: {subject}",
                    body=suggested_reply,
                )
                actions_executed.append({
                    "action": "draft_created",
                    "draft_id": draft_res.get("draft_id"),
                })
                if db_service:
                    db_service.store_draft(
                        gmail_id=gmail_id,
                        thread_id=thread_id,
                        recipient=sender,
                        subject=f"Re: {subject}",
                        body=suggested_reply,
                    )

        # Stage PM tasks into approval queue
        if pm_tasks and db_service:
            for task in pm_tasks:
                queued = db_service.queue_pm_task(
                    summary=str(task.get("summary") or "New Task"),
                    gmail_id=gmail_id,
                    email_subject=subject,
                    email_sender=sender,
                    description=str(task.get("description") or ""),
                    priority=str(task.get("priority") or "Medium"),
                    due_date=str(task.get("due_date") or ""),
                    destination=str(task.get("destination") or "sqlite_queue"),
                )
                actions_executed.append({
                    "action": "pm_task_queued",
                    "task_id": queued.task_id,
                    "summary": queued.summary,
                })

    state["actions_taken"] = actions_executed

    # 3. Contemporaneous Regulatory Telemetry (SHA-256 Hash Chaining)
    engine = audit_engine or AuditEngine.get_instance()
    audit_rec = engine.record_event(
        action_type="EMAIL_TRIAGE_COMPLETED",
        operator_id=sender[:32] if sender else "SYS_MAIL_TRIAGE",
        layer_0_status="PASSED" if not safety_override else "DIVERTED",
        layer_1_model="langgraph_gemini_triage",
        layer_1_confidence=confidence_score,
        layer_2_gate_status="APPROVED" if not safety_override else "NEEDS_REVIEW",
        correlation_id=gmail_id,
        payload_summary={
            "category": category,
            "urgency_score": urgency_score,
            "confidence_score": confidence_score,
            "responsibility_role": responsibility_role,
            "safety_override": safety_override,
            "execution_mode": mode,
            "actions_taken": actions_executed,
        },
    )
    state["audit_record_hash"] = audit_rec.record_hash

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "execution_gate",
        "duration_ms": duration_ms,
        "mode": mode,
        "actions_executed_count": len(actions_executed),
    })
    state["pipeline_trace"] = trace

    return state
