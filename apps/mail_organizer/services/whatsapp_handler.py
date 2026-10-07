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

        # 0. Google OAuth Magic Link Connect Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["connect", "!connect", "login", "auth", "google", "reauth"]):
            user = context.get("user")
            user_id = context.get("user_id") or (user.id if user else None)
            tenant_id = context.get("tenant_id") or (user.tenant_id if user else "default_tenant")
            if user_id:
                from core_platform.app.identity.magic_link import build_magic_link_url
                magic_url = build_magic_link_url(
                    user_id=str(user_id),
                    phone_number=sender_phone,
                    tenant_id=tenant_id,
                    base_url=base_url,
                )
                return (
                    "🔗 *Connect Your Google Account*\n\n"
                    "Click the link below on your mobile browser to securely authorize Gmail & Calendar access:\n\n"
                    f"{magic_url}\n\n"
                    "⏱️ _This secure link is valid for 15 minutes._"
                )
            else:
                return "🔒 Your phone number is not registered on this platform. Please contact your system administrator to register."

        # 1. Email Summary & Inbox Digest Commands
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["summary", "mail", "inbox", "emails", "digest"]):
            return self._handle_inbox_summary(base_url)


        # 2. Draft 1-Click Send & Approval Commands
        if any(cmd_lower.startswith(c) for c in ["send draft", "send_draft", "approve draft", "approve_draft", "send ", "dispatch "]):
            tokens = text_content.split()
            if len(tokens) >= 2:
                draft_id = tokens[-1]
                user = context.get("user")
                return await self._handle_send_draft(draft_id, user)
            return "Usage: `send <DRAFT-ID>` (e.g. `send 1` or `send DRAFT-1`)"

        if any(cmd_lower.startswith(c) for c in ["discard draft", "discard_draft", "reject draft", "reject_draft", "discard "]):
            tokens = text_content.split()
            if len(tokens) >= 2:
                draft_id = tokens[-1]
                return self._handle_discard_draft(draft_id)
            return "Usage: `discard <DRAFT-ID>` (e.g. `discard 1`)"

        # 3. PM Task Approval / Rejection Commands
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

        # 4. Pending PM Tasks Queue Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["tasks", "pm", "pending", "action items"]):
            return self._handle_pending_tasks(base_url)

        # 5. Staged Drafts Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["drafts", "draft", "replies"]):
            return self._handle_staged_drafts(base_url)

        # 6. Active Rules Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["rules", "vip", "whitelist"]):
            return self._handle_rules_list()

        # 7. Conversational AI Q&A over Inbox & Calendar State
        if len(text_content.strip()) > 3 and not cmd_lower.startswith("help"):
            conversational_reply = await self._handle_conversational_query(text_content, base_url)
            if conversational_reply:
                return conversational_reply

        # 8. Triage Dashboard Link & Help Menu
        return (
            f"📬 *AI Email & Calendar Triage Assistant*\n\n"
            f"Available Commands:\n"
            f"• *summary* — Get latest high-priority inbox briefing\n"
            f"• *drafts* — View staged email draft replies\n"
            f"• *send <DRAFT-ID>* — Approve & send draft immediately over Gmail\n"
            f"• *discard <DRAFT-ID>* — Discard staged draft\n"
            f"• *tasks* — View extracted PM tasks awaiting approval\n"
            f"• *approve <TASK-ID>* — Export task to Jira / Linear / PM Queue\n"
            f"• *reject <TASK-ID>* — Reject and dismiss a task\n"
            f"• *rules* — Show active VIP senders and triage rules\n"
            f"• Or ask any natural question about your inbox & schedule!\n\n"
            f"🔗 Full Dashboard: {base_url}/admin/apps/mail-organizer/dashboard"
        )

    def _handle_inbox_summary(self, base_url: str) -> str:
        """Build executive email digest."""
        recent = self.db_service.get_recent_emails(limit=5)
        if not recent:
            return (
                "📬 *AI Mail & Calendar Summary*\n\n"
                "Status: All Clear\n"
                "No pending or unread emails requiring immediate triage.\n\n"
                f"Interactive Dashboard: {base_url}/admin/apps/mail-organizer/dashboard"
            )

        lines = ["📬 *AI Mail & Calendar Summary (Top Priority)*:\n"]
        for idx, email in enumerate(recent, 1):
            category = email.get("category", "General")
            urgency = email.get("urgency_score", 5)
            subject = email.get("subject", "(No Subject)")
            sender = email.get("sender", "Unknown")
            lines.append(f"{idx}. *[{category} - Urgency {urgency}/10]* {subject}\n   From: {sender}")

        lines.append(f"\nVisit {base_url}/admin/apps/mail-organizer/dashboard for interactive triage & reply drafting.")
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

        lines.append(f"\nReview all tasks at: {base_url}/admin/apps/mail-organizer/dashboard")
        return "\n".join(lines)

    def _handle_staged_drafts(self, base_url: str) -> str:
        """List staged non-destructive draft email replies with 1-click action commands."""
        all_drafts = self.db_service.get_all_drafts()
        drafts = [d for d in all_drafts if d.status == "STAGED"][:5]
        if not drafts:
            return "✍️ No staged email drafts awaiting review at this time."

        lines = ["✍️ *Staged Contextual Drafts Awaiting Review*:\n"]
        for idx, d in enumerate(drafts, 1):
            recipient = d.recipient or "Recipient"
            subj = d.subject or "Subject"
            snippet = (d.body[:120] + "...") if len(d.body or "") > 120 else (d.body or "")
            lines.append(
                f"• *[Draft #{d.id}]* To: {recipient}\n"
                f"  *Subject:* {subj}\n"
                f"  *Preview:* \"{snippet}\"\n"
                f"  ➡️ Reply: `send {d.id}` to dispatch or `discard {d.id}` to discard\n"
            )

        lines.append(f"Full details: {base_url}/admin/apps/mail-organizer/drafts")
        return "\n".join(lines)

    async def _handle_send_draft(self, draft_id: str, user: Optional[Any] = None) -> str:
        """Approve and dispatch a staged draft email live via Gmail."""
        salt = user.user_secret_salt if user else None
        draft = self.db_service.get_draft(draft_id, decrypt_salt=salt)
        if not draft:
            return f"❌ Draft '{draft_id}' not found."

        if draft.get("status") == "SENT":
            return f"⚠️ Draft '{draft_id}' has already been sent."

        from apps.mail_organizer.connectors.gmail_connector import GmailConnector
        from apps.mail_organizer.connectors.auth_manager import get_user_access_token

        user_token = get_user_access_token(user) if user else None
        connector = GmailConnector(access_token_override=user_token)

        try:
            res = await connector.send_message(
                recipient=draft.get("recipient", ""),
                subject=draft.get("subject", ""),
                body=draft.get("body", ""),
                thread_id=draft.get("thread_id"),
            )
            self.db_service.update_draft_status(draft_id, "SENT")
            return (
                f"✅ *Email Sent Successfully!*\n\n"
                f"• *To:* {draft.get('recipient')}\n"
                f"• *Subject:* {draft.get('subject')}\n"
                f"• *Message ID:* {res.get('id', 'N/A')}\n"
                f"• *Status:* Dispatched via Google Workspace"
            )
        except Exception as err:
            logger.error("[MailOrganizerWhatsAppHandler] Failed to send draft %s: %s", draft_id, err)
            return f"❌ Failed to send draft {draft_id}: {str(err)}"

    def _handle_discard_draft(self, draft_id: str) -> str:
        """Discard a staged draft email."""
        draft = self.db_service.get_draft(draft_id)
        if not draft:
            return f"❌ Draft '{draft_id}' not found."

        success = self.db_service.update_draft_status(draft_id, "DISCARDED")
        if success:
            return f"🗑️ Draft '{draft_id}' has been discarded."
        return f"❌ Could not discard draft '{draft_id}'."

    def _handle_rules_list(self) -> str:
        """List active deterministic VIP and routing rules."""
        rules = self.db_service.get_all_rules()
        if not rules:
            return "⚙️ No custom routing rules registered. Default executive heuristics active."

        lines = ["⚙️ *Active Triage & VIP Rules*:\n"]
        for r in rules[:8]:
            lines.append(f"• [{r.rule_type.upper()}] `{r.pattern}` ➔ `{r.action}`")
        return "\n".join(lines)

    async def _handle_conversational_query(self, query: str, base_url: str) -> Optional[str]:
        """Answer natural language inquiries using live inbox context and LLM."""
        try:
            from core_platform.app.llm.gateway import get_platform_llm_gateway
            gateway = get_platform_llm_gateway()

            recent = self.db_service.get_recent_emails(limit=5)
            pending_tasks = self.db_service.get_pending_pm_tasks()[:4]
            drafts = self.db_service.get_all_drafts()[:3]

            context_items = []
            if recent:
                context_items.append("Recent Emails:\n" + "\n".join(
                    f"- [{e.get('category')}] {e.get('subject')} from {e.get('sender')} (Urgency: {e.get('urgency_score')}/10)"
                    for e in recent
                ))
            if pending_tasks:
                context_items.append("Pending PM Tasks:\n" + "\n".join(
                    f"- {t.task_id}: {t.summary} (Priority: {t.priority})"
                    for t in pending_tasks
                ))
            if drafts:
                context_items.append("Staged Drafts:\n" + "\n".join(
                    f"- To {d.recipient}: {d.subject}"
                    for d in drafts
                ))

            ctx_text = "\n\n".join(context_items) if context_items else "No current emails or tasks in database."

            prompt = (
                f"You are the executive AI Email & Calendar Assistant on WhatsApp.\n"
                f"Answer the user's question concisely using the following inbox/calendar context.\n"
                f"Use bullet points and emojis where helpful. Keep response within 3-4 paragraphs.\n\n"
                f"Context:\n{ctx_text}\n\n"
                f"User Question: {query}\n\n"
                f"Dashboard URL: {base_url}/admin/apps/mail-organizer/dashboard"
            )

            res = await gateway.generate(
                task="conversational_chat",
                prompt=prompt,
                system_instruction="You are a professional executive email and scheduling coordinator.",
            )
            if res and isinstance(res, dict):
                # Check for answer text or raw text
                text_ans = res.get("text") or res.get("response") or res.get("result") or res.get("reply")
                if text_ans:
                    return str(text_ans).strip()
        except Exception as exc:
            logger.warning("[MailOrganizerWhatsAppHandler] Conversational query error: %s", exc)

        return None
