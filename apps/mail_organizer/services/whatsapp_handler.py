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
Domain-Specific WhatsApp Ingress Handler for Mail Organizer & Triage.

Adheres strictly to GEES v2.0 Microkernel Architecture (Rule 3).
Handles executive inbox digests, VIP email summaries, PM task approval,
and meeting scheduling interactions over WhatsApp.
"""

import logging
from typing import Any, Dict, List, Optional
import uuid

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.pm.task_manager import PMTaskManager
from core_platform.app.config import settings

logger = logging.getLogger("apps.mail_organizer.whatsapp_handler")


class MailOrganizerWhatsAppHandler:
    """Domain-specific WhatsApp conversational handler for Mail Organizer Cartridge."""

    def __init__(
        self,
        db_service: MailDatabaseService,
        pm_manager: PMTaskManager,
        workflow: Optional[Any] = None,
    ) -> None:
        """Initialize with mail database service, PM task manager, and workflow."""
        self.db_service = db_service
        self.pm_manager = pm_manager
        self.workflow = workflow

    async def dispatch(self, msg: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Process inbound WhatsApp message for mail & calendar triage domain.

        Args:
            msg: Inbound Meta WhatsApp message dictionary.
            context: Transport context (sender_phone, correlation_id, base_url, etc.).

        Returns:
            Formatted response string to be dispatched to sender.
        """
        sender_phone: str = str(context.get("sender_phone", "")).strip()
        correlation_id: str = str(context.get("correlation_id", f"wa-{uuid.uuid4().hex[:8]}"))
        base_url: str = str(context.get("base_url", f"http://localhost:{settings.ORCHESTRATOR_PORT}")).rstrip("/")

        text_content = ""
        if "text" in msg:
            text_content = str(msg["text"].get("body", "")).strip()
        elif "image" in msg:
            text_content = str(msg["image"].get("caption", "")).strip()

        cmd_lower = text_content.lower()

        # 1. Email Summary & Inbox Digest Commands
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["summary", "mail", "inbox", "emails", "digest"]):
            return self._handle_inbox_summary(base_url)

        # 2. PM Task Approval / Rejection Commands
        if cmd_lower.startswith("approve") or cmd_lower.startswith("export"):
            tokens = text_content.split()
            if len(tokens) >= 2:
                task_id = tokens[1]
                res = await self.pm_manager.approve_and_export(task_id)
                if res.get("success"):
                    return f"✅ PM Task {task_id} approved and exported to {res.get('destination', 'Linear/Jira')}."
                else:
                    return f"❌ Could not export task {task_id}: {res.get('error', 'Task not found or already exported.')}"
            return "Usage: approve <TASK-ID> (e.g. 'approve TASK-101')"

        if cmd_lower.startswith("reject"):
            tokens = text_content.split()
            if len(tokens) >= 2:
                task_id = tokens[1]
                res_rej = self.pm_manager.reject_task(task_id, reason="Rejected via WhatsApp")
                if res_rej:
                    return f"🗑️ PM Task {task_id} rejected and archived."
                return f"❌ Task {task_id} not found."
            return "Usage: reject <TASK-ID>"

        # 3. Pending PM Tasks Queue Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["tasks", "pm", "pending"]):
            return self._handle_pending_tasks(base_url)

        # 4. Triage Dashboard Link & Greeting
        return (
            f"📬 *AI Email & Calendar Triage Assistant*\n\n"
            f"Available Commands:\n"
            f"• *summary* — Get latest high-priority inbox briefing\n"
            f"• *tasks* — View extracted PM tasks awaiting approval\n"
            f"• *approve <ID>* — Export task to Jira / Linear / PM Queue\n"
            f"• *reject <ID>* — Reject and dismiss a task\n\n"
            f"🔗 Full Dashboard: {base_url}/mail/"
        )

    def _handle_inbox_summary(self, base_url: str) -> str:
        """Build executive email digest."""
        recent = self.db_service.get_recent_emails(limit=5)
        if not recent:
            return (
                "📬 *AI Mail & Calendar Summary*\n\n"
                "Status: All Clear\n"
                "No pending or unread emails requiring immediate triage.\n\n"
                f"Interactive Dashboard: {base_url}/mail/"
            )

        lines = ["📬 *AI Mail & Calendar Summary (Top Priority)*:\n"]
        for idx, email in enumerate(recent, 1):
            category = email.get("category", "General")
            urgency = email.get("urgency_score", 5)
            subject = email.get("subject", "(No Subject)")
            sender = email.get("sender", "Unknown")
            lines.append(f"{idx}. *[{category} - Urgency {urgency}/10]* {subject}\n   From: {sender}")

        lines.append(f"\nVisit {base_url}/mail/ for full interactive triage & reply drafting.")
        return "\n".join(lines)

    def _handle_pending_tasks(self, base_url: str) -> str:
        """List pending PM action items extracted from emails."""
        pending = self.db_service.get_pending_pm_tasks()[:5]
        if not pending:
            return "✅ No pending PM tasks awaiting approval."

        lines = ["📋 *Extracted PM Tasks Awaiting Approval*:\n"]
        for task in pending:
            t_id = task.task_id or f"TASK-{task.id}"
            title = task.summary or task.email_subject or "Action Item"
            dest = task.destination or "sqlite_queue"
            lines.append(f"• *{t_id}*: {title} (Target: {dest})\n  Reply: `approve {t_id}`")

        lines.append(f"\nReview all tasks at: {base_url}/mail/")
        return "\n".join(lines)
