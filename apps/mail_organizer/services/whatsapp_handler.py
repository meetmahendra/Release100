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


def _extract_user_id_int(user: Optional[Any], context: Dict[str, Any]) -> Optional[int]:
    """Safely extract integer user_id from context or user entity."""
    raw = context.get("user_id")
    if raw is None and user is not None:
        raw = getattr(user, "id", None)
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        if raw.isdigit():
            return int(raw)
        return (abs(hash(raw)) % 900000) + 100000
    return None


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

        cmd_lower = text_content.lower().strip()

        user = context.get("user")
        user_id_int: Optional[int] = _extract_user_id_int(user, context)
        user_id_str: Optional[str] = str(user_id_int) if user_id_int is not None else None
        tenant_id: str = str(context.get("tenant_id") or (getattr(user, "tenant_id", None) if user else "default_tenant"))

        # 0. Google OAuth Magic Link Connect Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["connect", "!connect", "login", "auth", "google", "reauth"]):
            if user_id_str:
                from core_platform.app.identity.magic_link import build_magic_link_url
                magic_url = build_magic_link_url(
                    user_id=user_id_str,
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

        # 1. Immediate On-Demand Poller Sync
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["poll now", "sync now", "poll_now", "sync_now", "check inbox", "check mail", "refresh mail", "fetch mail"]):
            return await self._handle_poll_now(tenant_id=tenant_id, user_id=user_id_int)

        # 2. Poller Status & Cadence Inquiries
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["poller status", "sync status", "poller cadence", "sync cadence"]):
            return self._handle_poller_status(tenant_id=tenant_id, user_id=user_id_int)

        # 3. Poller Pause / Resume Controls
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["pause poller", "stop poller", "pause sync", "stop sync"]):
            return self._handle_toggle_user_poller(tenant_id=tenant_id, user=user, user_id=user_id_int, enable=False)

        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["resume poller", "start poller", "start sync", "resume sync", "enable poller"]):
            return self._handle_toggle_user_poller(tenant_id=tenant_id, user=user, user_id=user_id_int, enable=True)

        # 4. Urgent / High-Priority Emails Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["urgent", "urgent emails", "urgent mail", "critical", "critical emails"]):
            return self._handle_urgent_emails(tenant_id=tenant_id)

        # 5. Email Summary & Inbox Digest Commands
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["summary", "mail", "inbox", "emails", "digest"]):
            return self._handle_inbox_summary(base_url, tenant_id=tenant_id)

        # 6. Draft 1-Click Send & Approval Commands
        if any(cmd_lower.startswith(c) for c in ["send draft", "send_draft", "approve draft", "approve_draft", "send ", "dispatch "]):
            tokens = text_content.split()
            if len(tokens) >= 2:
                draft_id = tokens[-1]
                return await self._handle_send_draft(draft_id, user)
            return "Usage: `send <DRAFT-ID>` (e.g. `send 1` or `send DRAFT-1`)"

        if any(cmd_lower.startswith(c) for c in ["discard draft", "discard_draft", "reject draft", "reject_draft", "discard "]):
            tokens = text_content.split()
            if len(tokens) >= 2:
                draft_id = tokens[-1]
                return self._handle_discard_draft(draft_id)
            return "Usage: `discard <DRAFT-ID>` (e.g. `discard 1`)"

        # 7. PM Task Approval / Rejection Commands
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

        # 8. Pending PM Tasks Queue Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["tasks", "pm", "pending", "action items"]):
            return self._handle_pending_tasks(base_url)

        # 9. Staged Drafts Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["drafts", "draft", "replies"]):
            return self._handle_staged_drafts(base_url)

        # 10. Active Rules Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["rules", "vip", "whitelist"]):
            return self._handle_rules_list()

        # 11. Explicit Help Menu
        if cmd_lower in ["help", "?", "menu", "commands"]:
            return self._format_help_menu(base_url)

        # 12. Conversational Agentic AI Q&A over Inbox, Calendar & Poller State
        if text_content.strip():
            return await self._handle_conversational_query(text_content, base_url, context)

        return self._format_help_menu(base_url)

    def _handle_inbox_summary(self, base_url: str, tenant_id: Optional[str] = None) -> str:
        """Build executive email digest."""
        recent = self.db_service.get_recent_emails(limit=5, tenant_id=tenant_id)
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

    def _format_help_menu(self, base_url: str) -> str:
        """Render actionable help guide and command list."""
        return (
            "📬 *AI Email & Calendar Triage Assistant*\n\n"
            "Available Commands:\n"
            "• *summary* — Get latest high-priority inbox briefing\n"
            "• *poll now* — Trigger immediate on-demand Gmail sync\n"
            "• *poller status* — View active sync cadence & last check time\n"
            "• *pause poller* / *resume poller* — Control background polling\n"
            "• *urgent* — View urgent & critical emails\n"
            "• *drafts* — View staged email draft replies\n"
            "• *send <DRAFT-ID>* — Approve & send draft immediately over Gmail\n"
            "• *discard <DRAFT-ID>* — Discard staged draft\n"
            "• *tasks* — View extracted PM tasks awaiting approval\n"
            "• *approve <TASK-ID>* — Export task to Jira / Linear / PM Queue\n"
            "• *reject <TASK-ID>* — Reject and dismiss a task\n"
            "• *rules* — Show active VIP senders and triage rules\n"
            "• Or ask any natural question about your inbox, drafts, or schedule!\n\n"
            f"🔗 Full Dashboard: {base_url}/admin/apps/mail-organizer/dashboard"
        )

    def _handle_poller_status(self, tenant_id: str, user_id: Optional[int]) -> str:
        """Build detailed poller and cadence status card."""
        ws_config = self.db_service.get_workspace_poller_config(tenant_id)
        user_config = self.db_service.get_user_poller_config(user_id, tenant_id) if user_id is not None else None

        ws_status = "🟢 Active" if ws_config.is_master_enabled else "⏸️ Paused"
        if user_config:
            user_status = "🟢 Active" if user_config.is_poller_enabled else "⏸️ Paused"
            interval_m = user_config.poll_interval_seconds // 60
            window = user_config.active_window or "24x7"
            last_poll = (
                user_config.last_polled_at.strftime("%Y-%m-%d %H:%M UTC")
                if user_config.last_polled_at
                else "Never"
            )
            cycles = user_config.total_cycles
            emails = user_config.total_emails_fetched
            err_note = f"\n⚠️ *Last Error:* {user_config.last_error}" if user_config.last_error else ""
        else:
            user_status = "🟢 Active (Default)"
            interval_m = ws_config.default_poll_interval_seconds // 60
            window = "24x7"
            last_poll = "Never"
            cycles = 0
            emails = 0
            err_note = ""

        return (
            "🔄 *Email Poller & Sync Status*\n\n"
            f"• *Workspace Master Switch:* {ws_status}\n"
            f"• *Your Personal Poller:* {user_status}\n"
            f"• *Sync Cadence:* Every {interval_m} minutes\n"
            f"• *Active Window:* {window}\n"
            f"• *Last Checked:* {last_poll}\n"
            f"• *Total Sync Cycles:* {cycles}\n"
            f"• *Total Emails Processed:* {emails}"
            f"{err_note}\n\n"
            "💡 _Commands:_\n"
            "• `poll now` — Trigger immediate inbox sync\n"
            "• `pause poller` — Pause automatic background checks\n"
            "• `resume poller` — Resume background checks"
        )

    async def _handle_poll_now(self, tenant_id: str, user_id: Optional[int]) -> str:
        """Trigger on-demand manual sync for the user's Gmail inbox."""
        if user_id is None:
            return "🔒 User identity not identified. Please re-authenticate via `connect`."

        from apps.mail_organizer.services.poller_manager import MailPollerManager
        mgr = MailPollerManager.get_instance()
        poll_res = await mgr.poll_user_now(user_id=user_id, tenant_id=tenant_id)
        if isinstance(poll_res, dict):
            count = int(poll_res.get("emails_processed", 0))
        elif isinstance(poll_res, int):
            count = poll_res
        else:
            count = 0
        return (
            "⚡ *On-Demand Inbox Sync Complete!*\n\n"
            f"• *Target User:* `{user_id}`\n"
            f"• *New Emails Processed:* {count}\n"
            "• *Status:* 🟢 Inbox up to date\n\n"
            "Reply `summary` to view the latest emails or `drafts` for staged replies."
        )

    def _handle_toggle_user_poller(
        self,
        tenant_id: str,
        user: Optional[Any],
        user_id: Optional[int],
        enable: bool,
    ) -> str:
        """Pause or resume automatic polling for the requesting user."""
        if user_id is None:
            return "🔒 User identity not identified. Please re-authenticate via `connect`."

        existing = self.db_service.get_user_poller_config(user_id=user_id, tenant_id=tenant_id)
        email = (
            (existing.email if existing else None)
            or getattr(user, "email", None)
            or getattr(user, "google_email", None)
            or f"user_{user_id}@{tenant_id}.local"
        )
        interval = existing.poll_interval_seconds if existing else 300
        window = existing.active_window if existing else "24x7"

        self.db_service.upsert_user_poller_config(
            user_id=user_id,
            email=str(email),
            is_enabled=enable,
            poll_interval_seconds=interval,
            active_window=window,
            tenant_id=tenant_id,
        )
        state_str = "resumed and active 🟢" if enable else "paused ⏸️"
        return (
            "🔄 *Poller Status Updated*\n\n"
            f"Your personal email poller has been {state_str}.\n\n"
            "Cadence and active schedule will be honored accordingly."
        )

    def _handle_urgent_emails(self, tenant_id: Optional[str] = None) -> str:
        """List high-urgency and critical emails needing immediate attention."""
        recent = self.db_service.get_recent_emails(limit=20, tenant_id=tenant_id)
        urgent = [
            e for e in recent
            if (e.get("urgency_score", 0) or 0) >= 7
            or str(e.get("category", "")).lower() in ("urgent", "critical", "vip")
        ]
        if not urgent:
            return (
                "✅ *No Urgent Emails*\n\n"
                "Your inbox is clear of high-urgency or critical items right now.\n\n"
                "Reply `summary` to view all recent emails."
            )

        lines = [f"🚨 *Urgent & Critical Emails ({len(urgent)} items)*:\n"]
        for idx, email in enumerate(urgent[:5], 1):
            urgency = email.get("urgency_score", 7)
            cat = email.get("category", "Urgent")
            subj = email.get("subject", "(No Subject)")
            sndr = email.get("sender", "Unknown")
            lines.append(f"{idx}. *[{cat} - Urgency {urgency}/10]* {subj}\n   From: {sndr}")

        lines.append("\nReply `summary` for full details or `drafts` to check pending replies.")
        return "\n".join(lines)

    def _handle_search_emails(self, search_term: str, tenant_id: Optional[str] = None) -> str:
        """Search recent emails by keyword or sender."""
        recent = self.db_service.get_recent_emails(limit=50, tenant_id=tenant_id)
        term = search_term.lower().strip()
        matched = [
            e for e in recent
            if term in str(e.get("sender", "")).lower()
            or term in str(e.get("subject", "")).lower()
            or term in str(e.get("snippet", "")).lower()
        ]
        if not matched:
            return f"🔍 *Email Search*\n\nNo recent emails found matching *\"{search_term}\"*."

        lines = [f"🔍 *Emails matching \"{search_term}\" ({len(matched)} found)*:\n"]
        for idx, email in enumerate(matched[:5], 1):
            subj = email.get("subject", "(No Subject)")
            sndr = email.get("sender", "Unknown")
            cat = email.get("category", "General")
            lines.append(f"{idx}. *[{cat}]* {subj}\n   From: {sndr}")
        return "\n".join(lines)

    async def _handle_conversational_query(
        self,
        query: str,
        base_url: str,
        context: Dict[str, Any],
    ) -> str:
        """Answer natural language inquiries using live inbox context and LLM."""
        user = context.get("user")
        user_id_int: Optional[int] = _extract_user_id_int(user, context)
        tenant_id = str(context.get("tenant_id") or (getattr(user, "tenant_id", None) if user else "default_tenant"))
        user_name = str(getattr(user, "full_name", None) or "User")
        q_lower = query.lower().strip()

        # 1. Deterministic Intent Checks (Fast Pre-Execution)
        if any(w in q_lower for w in ["poll", "sync", "fetching", "background check"]):
            if any(w in q_lower for w in ["now", "immediate", "check inbox", "refresh", "fetch"]):
                return await self._handle_poll_now(tenant_id=tenant_id, user_id=user_id_int)
            if any(w in q_lower for w in ["pause", "stop", "halt", "disable"]):
                return self._handle_toggle_user_poller(tenant_id=tenant_id, user=user, user_id=user_id_int, enable=False)
            if any(w in q_lower for w in ["resume", "start", "enable", "unpause"]):
                return self._handle_toggle_user_poller(tenant_id=tenant_id, user=user, user_id=user_id_int, enable=True)
            return self._handle_poller_status(tenant_id=tenant_id, user_id=user_id_int)

        if any(w in q_lower for w in ["urgent", "critical", "high priority", "emergency"]):
            return self._handle_urgent_emails(tenant_id=tenant_id)

        if any(w in q_lower for w in ["draft", "reply", "replies", "outbox"]):
            return self._handle_staged_drafts(base_url)

        if any(w in q_lower for w in ["task", "jira", "linear", "action item", "todo", "pm"]):
            return self._handle_pending_tasks(base_url)

        if q_lower.startswith("search ") or q_lower.startswith("find "):
            term = query.split(maxsplit=1)[-1].strip()
            if term:
                return self._handle_search_emails(term, tenant_id=tenant_id)

        # 2. Gather Live State for Context Synthesis
        recent = self.db_service.get_recent_emails(limit=8, tenant_id=tenant_id)
        drafts = [d for d in self.db_service.get_all_drafts() if d.status == "STAGED"][:4]
        pending_tasks = self.db_service.get_pending_pm_tasks()[:4]
        urgent_count = sum(1 for e in recent if (e.get("urgency_score", 0) or 0) >= 7)
        ws_config = self.db_service.get_workspace_poller_config(tenant_id)
        user_config = self.db_service.get_user_poller_config(user_id_int, tenant_id) if user_id_int is not None else None

        # 3. LLM Synthesis via Platform Gateway
        try:
            from core_platform.app.llm.gateway import get_platform_llm_gateway
            gateway = get_platform_llm_gateway()

            context_sections: List[str] = [
                f"User Name: {user_name}",
                f"Workspace Poller Status: {'ACTIVE' if ws_config.is_master_enabled else 'PAUSED'}",
                f"Personal Poller Status: {'ACTIVE' if (user_config.is_poller_enabled if user_config else True) else 'PAUSED'}",
            ]

            if recent:
                context_sections.append(
                    "Recent Emails in Inbox:\n" + "\n".join(
                        f"- [{e.get('category', 'General')} | Urgency {e.get('urgency_score', 5)}/10] "
                        f"Subject: \"{e.get('subject', 'No Subject')}\" from {e.get('sender', 'Unknown')}. "
                        f"Snippet: {str(e.get('snippet', ''))[:150]}"
                        for e in recent
                    )
                )
            else:
                context_sections.append("Recent Emails in Inbox: Zero emails in database.")

            if drafts:
                context_sections.append(
                    "Staged Draft Replies (Waiting for User Approval):\n" + "\n".join(
                        f"- Draft #{d.id} to {d.recipient}: \"{d.subject}\" (Preview: {str(d.body)[:100]})"
                        for d in drafts
                    )
                )

            if pending_tasks:
                context_sections.append(
                    "Pending PM Tasks:\n" + "\n".join(
                        f"- Task {t.task_id or t.id}: \"{t.summary}\" (Target: {t.destination})"
                        for t in pending_tasks
                    )
                )

            ctx_text = "\n\n".join(context_sections)

            prompt = (
                "You are the executive AI Email & Calendar Assistant on WhatsApp for the Mail Organizer application.\n"
                "Answer the user's natural language question concisely, accurately, and politely.\n"
                "Ground your answer STRICTLY in the provided live context.\n"
                "Formatting rules:\n"
                "- Use WhatsApp markdown formatting (*bold*, _italic_, bullet points).\n"
                "- Include relevant emojis.\n"
                "- If relevant action commands exist (e.g. `send <id>`, `approve <id>`, `poll now`), mention them.\n"
                "- Return your response as a JSON object with a single string field: 'reply'.\n\n"
                f"Live System Context:\n{ctx_text}\n\n"
                f"User Message: {query}\n\n"
                f"Dashboard URL: {base_url}/admin/apps/mail-organizer/dashboard"
            )

            res = await gateway.generate(
                task="text_generation",
                prompt=prompt,
                response_mime_type="application/json",
                system_instruction="You are an intelligent executive AI email and calendar coordinator on WhatsApp.",
                operation_id="whatsapp_inbox_agentic_chat",
                tenant_id=tenant_id,
                cartridge_id="mail_organizer",
            )
            if res and isinstance(res, dict):
                text_ans = (
                    res.get("reply")
                    or res.get("response")
                    or res.get("text")
                    or res.get("result")
                    or res.get("raw_text")
                )
                if text_ans and str(text_ans).strip():
                    return str(text_ans).strip()
        except Exception as exc:
            logger.warning("[MailOrganizerWhatsAppHandler] Agentic query error: %s", exc)

        # 4. Deterministic Intelligent Fallback (GEES Layer 0 / Layer 2)
        if any(w in q_lower for w in ["hi", "hello", "hey", "greetings", "good morning", "good evening"]):
            return (
                f"👋 *Hello {user_name}!*\n\n"
                "I'm your AI Email & Calendar Assistant.\n\n"
                "📊 *Inbox Overview:*\n"
                f"• *Recent Emails:* {len(recent)}\n"
                f"• *Urgent Attention:* {urgent_count} items\n"
                f"• *Staged Drafts:* {len(drafts)} awaiting review\n"
                f"• *Pending PM Tasks:* {len(pending_tasks)} pending\n\n"
                "How can I help you? You can ask me to summarize emails, check urgent items, review drafts, or sync your inbox (`poll now`)."
            )

        lines = [f"📬 *Inbox Status Update for {user_name}*:\n"]
        if recent:
            lines.append("*Recent Emails:*")
            for idx, e in enumerate(recent[:4], 1):
                lines.append(f"{idx}. *[{e.get('category', 'General')}]* {e.get('subject')} (from {e.get('sender')})")
        else:
            lines.append("• No emails currently in inbox.")

        if drafts:
            lines.append(f"\n✍️ *{len(drafts)} Draft(s) Awaiting Review:* (reply `drafts` to view)")
        if pending_tasks:
            lines.append(f"📋 *{len(pending_tasks)} PM Task(s) Pending:* (reply `tasks` to view)")

        lines.append("\n💡 _Reply `poll now` to check Gmail now, or `help` for command options._")
        lines.append(f"🔗 Dashboard: {base_url}/admin/apps/mail-organizer/dashboard")
        return "\n".join(lines)
