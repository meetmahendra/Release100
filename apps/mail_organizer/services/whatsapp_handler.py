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
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.pm.task_manager import PMTaskManager
from core_platform.app.config import settings

logger = logging.getLogger("apps.mail_organizer.whatsapp_handler")


class InteractiveWhatsAppPayload(Dict[str, Any]):
    """Structured WhatsApp interactive payload dict supporting substring membership checks."""

    def __contains__(self, item: object) -> bool:
        """Check dict keys first, then search reply_message and interactive_list row fields."""
        if super().__contains__(item):
            return True
        if isinstance(item, str):
            haystack_parts: List[str] = [
                str(self.get("reply_message") or ""),
                str(self.get("body_text") or ""),
                str(self.get("footer_text") or ""),
                str(self.get("search_index") or ""),
            ]
            inter_list = self.get("interactive_list")
            if isinstance(inter_list, dict):
                for sec in inter_list.get("sections", []):
                    if isinstance(sec, dict):
                        haystack_parts.append(str(sec.get("title") or ""))
                        for row in sec.get("rows", []):
                            if isinstance(row, dict):
                                haystack_parts.append(str(row.get("title") or ""))
                                haystack_parts.append(str(row.get("description") or ""))
            return item in " ".join(haystack_parts)
        return False


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

    # [CODE-MARKER: FIX-WA-SESSION-STICKY-20] 15-Minute Active Triage Session Stickiness
    _ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
    SESSION_TTL_SECONDS: float = 900.0

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

    @classmethod
    def record_session(cls, sender_phone: str, last_gmail_id: Optional[str] = None) -> None:
        """Record or refresh a 15-minute active triage session for sender_phone."""
        import time as _time
        key = str(sender_phone or "").strip()
        if not key:
            return
        prev = cls._ACTIVE_SESSIONS.get(key) or {}
        cls._ACTIVE_SESSIONS[key] = {
            "ts": _time.time(),
            "last_gmail_id": last_gmail_id if last_gmail_id is not None else prev.get("last_gmail_id"),
        }

    @classmethod
    def has_active_session(cls, sender_phone: str) -> bool:
        """Return True if sender_phone interacted with Mail Organizer within the last 15 minutes."""
        import time as _time
        key = str(sender_phone or "").strip()
        if not key:
            return False
        entry = cls._ACTIVE_SESSIONS.get(key)
        if not entry:
            return False
        if (_time.time() - float(entry.get("ts") or 0.0)) <= cls.SESSION_TTL_SECONDS:
            return True
        cls._ACTIVE_SESSIONS.pop(key, None)
        return False

    @classmethod
    def get_last_inspected_gmail_id(cls, sender_phone: str) -> Optional[str]:
        """Return the last inspected gmail_id in the user's active session, if any."""
        if not cls.has_active_session(sender_phone):
            return None
        entry = cls._ACTIVE_SESSIONS.get(str(sender_phone or "").strip()) or {}
        gid = entry.get("last_gmail_id")
        return str(gid) if gid else None

    # [CODE-MARKER: MO-WA-02] Two-Stage WhatsApp Executive Brief & Infographic Card Handler
    async def dispatch(self, msg: Dict[str, Any], context: Dict[str, Any]) -> Union[str, Dict[str, Any]]:
        """Process inbound WhatsApp message or interactive reply for mail & calendar triage domain."""
        sender_phone: str = str(context.get("sender_phone", "")).strip()
        correlation_id: str = str(context.get("correlation_id", f"wa-{uuid.uuid4().hex[:8]}"))
        base_url: str = str(context.get("base_url", f"http://localhost:{settings.ORCHESTRATOR_PORT}")).rstrip("/")
        if sender_phone:
            self.record_session(sender_phone)

        text_content = ""
        if "text" in msg:
            text_content = str(msg["text"].get("body", "")).strip()
        elif "image" in msg:
            text_content = str(msg["image"].get("caption", "")).strip()

        interactive_id = str(context.get("interactive_reply_id") or "").strip()
        if not interactive_id and msg.get("type") == "interactive":
            inter_obj = msg.get("interactive") or {}
            btn_rep = inter_obj.get("button_reply") or {}
            lst_rep = inter_obj.get("list_reply") or {}
            interactive_id = str(btn_rep.get("id") or lst_rep.get("id") or "").strip()

        cmd_lower = text_content.lower().strip()
        effective_action_id = interactive_id or (text_content.strip() if ":" in text_content else "")

        user = context.get("user")
        user_id_int: Optional[int] = _extract_user_id_int(user, context)
        user_id_str: Optional[str] = str(user_id_int) if user_id_int is not None else None
        tenant_id: str = str(context.get("tenant_id") or (getattr(user, "tenant_id", None) if user else "default_tenant"))
        user_salt: Optional[str] = getattr(user, "user_secret_salt", None) if user else None

        # Stage 2 Interactive List / Button Actions (REV-11 & REV-13)
        if effective_action_id.startswith("inspect_mail:"):
            target_gid = effective_action_id.split(":", 1)[1].strip()
            if sender_phone:
                self.record_session(sender_phone, last_gmail_id=target_gid)
            logger.info("[MailOrganizerWA] Matched intent=inspect_mail user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_gid)
            return self._handle_stage2_card_inspection(target_gid, tenant_id=tenant_id, user=user)

        if effective_action_id.startswith("inspect_draft:"):
            target_did = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=inspect_draft user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_did)
            return self._handle_inspect_draft_card(target_did, tenant_id=tenant_id, user=user)

        if effective_action_id.startswith("approve_send:"):
            target_gid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=approve_send user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_gid)
            return await self._handle_send_draft(target_gid, user)

        if effective_action_id.startswith("discard_draft:"):
            target_did = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=discard_draft user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_did)
            return self._handle_discard_draft(target_did)

        if effective_action_id.startswith("deep_inspect:"):
            target_gid = effective_action_id.split(":", 1)[1].strip()
            if sender_phone:
                self.record_session(sender_phone, last_gmail_id=target_gid)
            logger.info("[MailOrganizerWA] Matched intent=deep_inspect user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_gid)
            return self._handle_deep_inspect(target_gid, tenant_id=tenant_id, user=user)

        if effective_action_id.startswith("snooze_mail:"):
            target_gid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=snooze_mail user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_gid)
            self.db_service.update_email_status(target_gid, "SNOOZED", tenant_id=tenant_id)
            return f"⏸️ Email `{target_gid}` snoozed and removed from active triage. Reply `summary` anytime to review remaining items."

        if effective_action_id.startswith("generate_draft:"):
            target_gid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=generate_draft user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_gid)
            return await self._handle_generate_draft_on_demand(target_gid, tenant_id=tenant_id, user=user)

        if effective_action_id.startswith("mark_done:"):
            target_gid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=mark_done user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_gid)
            return self._handle_mark_done(target_gid, tenant_id=tenant_id)

        if effective_action_id.startswith("calendar_action:"):
            target_gid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=calendar_action user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_gid)
            return self._handle_calendar_action(target_gid, tenant_id=tenant_id, user=user)

        if effective_action_id.startswith("create_task:"):
            target_gid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=create_task user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_gid)
            return self._handle_create_task_from_mail(target_gid, tenant_id=tenant_id, user=user)

        if effective_action_id.startswith("inspect_task:"):
            target_tid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=inspect_task user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_tid)
            return self._handle_inspect_task_card(target_tid, tenant_id=tenant_id)

        if effective_action_id.startswith("approve_task:"):
            target_tid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=approve_task user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_tid)
            res = await self.pm_manager.approve_and_export(target_tid, tenant_id=tenant_id)
            if res.get("success"):
                return f"✅ PM Task {target_tid} approved and exported to {res.get('destination', 'Linear/Jira')}."
            return f"❌ Could not export task {target_tid}: {res.get('error', 'Task not found or already exported.')}"

        if effective_action_id.startswith("reject_task:"):
            target_tid = effective_action_id.split(":", 1)[1].strip()
            logger.info("[MailOrganizerWA] Matched intent=reject_task user_id=%s tenant=%s target=%s", user_id_int, tenant_id, target_tid)
            if self.pm_manager.reject_task(target_tid, reason="Rejected via WhatsApp", tenant_id=tenant_id):
                return f"🗑️ PM Task {target_tid} rejected and archived."
            return f"❌ Task {target_tid} not found."

        if effective_action_id.startswith("provide_artifact:") or cmd_lower.startswith("artifact "):
            logger.info("[MailOrganizerWA] Matched intent=provide_artifact user_id=%s tenant=%s", user_id_int, tenant_id)
            return self._handle_provide_artifact(text_content, effective_action_id, tenant_id=tenant_id, user_id=user_id_int)

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
                    "Tap the link below on your mobile browser to securely authorize Gmail & Calendar access:\n\n"
                    f"{magic_url}\n\n"
                    "⏱️ _This secure link is valid for 15 minutes._\n"
                    "💡 _If the link is not clickable, please save this contact number._"
                )
            else:
                return "🔒 Your phone number is not registered on this platform. Please contact your system administrator to register."

        # 1. Immediate On-Demand Poller Sync
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["poll now", "sync now", "poll_now", "sync_now", "check inbox", "check mail", "refresh mail", "fetch mail"]):
            return await self._handle_poll_now(
                tenant_id=tenant_id,
                user_id=user_id_int,
                user=user,
                sender_phone=sender_phone,
                base_url=base_url,
            )

        # 2. Poller Status & Cadence Inquiries
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["poller status", "sync status", "poller cadence", "sync cadence"]):
            return self._handle_poller_status(tenant_id=tenant_id, user_id=user_id_int, user=user)

        # 3. Poller Pause / Resume Controls
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["pause poller", "stop poller", "pause sync", "stop sync"]):
            return self._handle_toggle_user_poller(tenant_id=tenant_id, user=user, user_id=user_id_int, enable=False)

        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["resume poller", "start poller", "start sync", "resume sync", "enable poller"]):
            return self._handle_toggle_user_poller(tenant_id=tenant_id, user=user, user_id=user_id_int, enable=True)

        # 4. Urgent / High-Priority Emails Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["urgent", "urgent emails", "urgent mail", "critical", "critical emails"]):
            return self._handle_urgent_emails(tenant_id=tenant_id, decrypt_salt=user_salt)

        # 5. Email Summary & Inbox Digest Commands
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["summary", "mail", "inbox", "emails", "digest"]):
            return self._handle_inbox_summary(base_url, tenant_id=tenant_id, decrypt_salt=user_salt)

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
            return self._handle_pending_tasks(base_url, tenant_id=tenant_id)

        # 9. Staged Drafts Command
        if any(cmd_lower == c or cmd_lower.startswith(c + " ") for c in ["drafts", "draft", "replies"]):
            return self._handle_staged_drafts(base_url, tenant_id=tenant_id, decrypt_salt=user_salt)

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

    # [CODE-MARKER: FIX-WA-ONDEMAND-LIST-11] On-demand commands return Native WhatsApp Interactive List Drawer
    # [CODE-MARKER: FIX-WA-STAGE1-BRIEF-14] Crisp 1-Line Brief + Native Bottom-Sheet List Drawer
    def _handle_inbox_summary(
        self,
        base_url: str,
        tenant_id: Optional[str] = None,
        decrypt_salt: Optional[str] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Build Stage 1 1-Line Executive Brief + Native WhatsApp List Drawer (active PROCESSED items only)."""
        all_recent = self.db_service.get_recent_emails(limit=25, decrypt_salt=decrypt_salt, tenant_id=tenant_id)
        recent = [
            e for e in all_recent
            if str(e.get("status") or "PROCESSED") == "PROCESSED"
        ][:8]
        if not recent:
            return (
                "📬 *AI Mail & Calendar Summary*\n\n"
                "Status: All Clear\n"
                "No pending or unread emails requiring immediate triage.\n\n"
                f"Interactive Dashboard: {base_url}/admin/apps/mail-organizer/dashboard"
            )

        rows: List[Dict[str, str]] = []
        index_lines: List[str] = []
        for idx, email in enumerate(recent[:10], 1):
            gid = str(email.get("gmail_id") or f"msg_{idx}")
            category = str(email.get("category") or "General")
            urgency = int(email.get("urgency_score") or 5)
            subject = str(email.get("subject") or "(No Subject)")
            sender = str(email.get("sender") or "Unknown")
            rows.append({
                "id": f"inspect_mail:{gid}",
                "title": f"[P{urgency}] {subject}"[:24],
                "description": f"From: {sender} — {category}"[:72],
            })
            index_lines.append(f"{idx}. [{category} - Urgency {urgency}/10] {subject} From: {sender}")

        top_subj = str(recent[0].get("subject") or "(No Subject)")[:60]
        body_text = (
            f"📬 *AI Mail & Calendar Summary: {len(rows)} Decision(s) Ready*\n"
            f"Top Priority: _{top_subj}_\n"
            "Tap *Open Decisions* below to slide open the triage drawer."
        )
        list_obj: Dict[str, Any] = {
            "button_label": "Open Decisions",
            "header_text": "Executive Mail Triage",
            "footer_text": "Select an item to open Decision Card",
            "sections": [{"title": "Actionable Mail", "rows": rows}],
        }
        return InteractiveWhatsAppPayload(
            response_type="interactive_list",
            reply_message=body_text,
            body_text=body_text,
            button_label="Open Decisions",
            header_text="Executive Mail Triage",
            footer_text="Select an item to open Decision Card",
            interactive_list=list_obj,
            sections=list_obj["sections"],
            search_index="\n".join(index_lines) + f"\n{base_url}/admin/apps/mail-organizer/dashboard",
        )

    # [CODE-MARKER: FIX-WA-PM-DRAWER-26] PM Task Queue Interactive List Drawer & Stage 2 Task Card
    def _handle_pending_tasks(
        self,
        base_url: str,
        tenant_id: Optional[str] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Return Native WhatsApp Bottom-Sheet List Drawer for pending PM action items."""
        pending = self.db_service.get_pending_pm_tasks(tenant_id=tenant_id)[:8]
        if not pending and tenant_id:
            pending = self.db_service.get_pending_pm_tasks()[:8]
        if not pending:
            return "✅ No pending PM tasks awaiting approval."

        rows: List[Dict[str, str]] = []
        index_lines: List[str] = ["📋 *Extracted PM Tasks Awaiting Approval*:"]
        for task in pending[:10]:
            t_id = str(task.task_id or f"TASK-{task.id}")
            title = str(task.summary or task.email_subject or "Action Item")
            dest = str(task.destination or "sqlite_queue")
            prio = str(task.priority or "Medium")
            rows.append({
                "id": f"inspect_task:{t_id}"[:200],
                "title": f"[{prio[:4]}] {title}"[:24],
                "description": f"{t_id} • Target: {dest} — {title}"[:72],
            })
            index_lines.append(f"• *{t_id}*: {title} (Target: {dest}) Reply: `approve {t_id}`")

        top_task = pending[0]
        top_id = str(top_task.task_id or f"TASK-{top_task.id}")
        top_title = str(top_task.summary or top_task.email_subject or "Action Item")[:56]
        body_text = (
            f"📋 *PM Action Queue: {len(rows)} Task(s) Awaiting Approval*\n"
            f"Top Task: *[{top_id}]* _{top_title}_\n"
            "Tap *Open PM Tasks* below to inspect, approve, or reject."
        )
        list_obj: Dict[str, Any] = {
            "button_label": "Open PM Tasks",
            "header_text": "PM Action Queue",
            "footer_text": "Select a task to inspect & export",
            "sections": [{"title": "Pending PM Tasks", "rows": rows}],
        }
        return InteractiveWhatsAppPayload(
            response_type="interactive_list",
            reply_message=body_text,
            body_text=body_text,
            button_label="Open PM Tasks",
            header_text="PM Action Queue",
            footer_text="Select a task to inspect & export",
            interactive_list=list_obj,
            sections=list_obj["sections"],
            search_index="\n".join(index_lines) + f"\nReview all tasks at: {base_url}/admin/apps/mail-organizer/dashboard",
        )

    def _handle_staged_drafts(
        self,
        base_url: str,
        tenant_id: Optional[str] = None,
        decrypt_salt: Optional[str] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Return Native WhatsApp Bottom-Sheet Drawer for Staged Draft Replies."""
        all_drafts = self.db_service.get_all_drafts(tenant_id=tenant_id, decrypt_salt=decrypt_salt)
        drafts = [d for d in all_drafts if d.status == "STAGED"][:8]
        if not drafts:
            return "✍️ No staged email drafts awaiting review at this time."

        rows: List[Dict[str, str]] = []
        index_lines: List[str] = []
        for d in drafts:
            recipient = str(d.recipient or "Recipient")
            subj = str(d.subject or "Subject")
            snippet = (d.body[:120] + "...") if len(d.body or "") > 120 else (d.body or "")
            rows.append({
                "id": f"inspect_draft:{d.id}",
                "title": f"Draft #{d.id}: {subj}"[:24],
                "description": f"To: {recipient} — {snippet}"[:72],
            })
            index_lines.append(
                f"Draft #{d.id} To: {recipient} Subject: {subj} Preview: {snippet} send {d.id} discard {d.id}"
            )

        first = drafts[0]
        first_rec = str(first.recipient or "Recipient")[:36]
        first_subj = str(first.subject or "Subject")[:48]
        body_text = (
            f"✍️ *Staged Drafts: {len(drafts)} Reply(s) Ready*\n"
            f"Latest: *[Draft #{first.id}]* {first_subj} (To: {first_rec})\n"
            "Tap *Review Drafts* below to open the decision card & send."
        )
        list_obj: Dict[str, Any] = {
            "button_label": "Review Drafts",
            "header_text": "Staged Reply Queue",
            "footer_text": "Select a draft to inspect or send",
            "sections": [{"title": "Staged Replies", "rows": rows}],
        }
        return InteractiveWhatsAppPayload(
            response_type="interactive_list",
            reply_message=body_text,
            body_text=body_text,
            button_label="Review Drafts",
            header_text="Staged Reply Queue",
            footer_text="Select a draft to inspect or send",
            interactive_list=list_obj,
            sections=list_obj["sections"],
            search_index="\n".join(index_lines) + f"\n{base_url}/admin/apps/mail-organizer/drafts",
        )

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
        connector = GmailConnector(
            access_token_override=user_token,
            user_id=getattr(user, "id", None) if user else None,
        )

        try:
            res = await connector.send_message(
                recipient=draft.get("recipient", ""),
                subject=draft.get("subject", ""),
                body=draft.get("body", ""),
                thread_id=draft.get("thread_id"),
            )
            self.db_service.update_draft_status(draft_id, "SENT")
            if draft.get("gmail_id"):
                self.db_service.update_email_status(str(draft["gmail_id"]), "ACTIONED")
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
        """Discard a staged draft email and mark parent email reviewed."""
        draft = self.db_service.get_draft(draft_id)
        if not draft:
            # If user tapped discard_draft:<gmail_id> on an email without a DraftRecord, still transition email status
            if self.db_service.update_email_status(str(draft_id), "REVIEWED"):
                return f"🗑️ Item '{draft_id}' dismissed and marked reviewed."
            return f"❌ Draft '{draft_id}' not found."

        success = self.db_service.update_draft_status(draft_id, "DISCARDED")
        if draft.get("gmail_id"):
            self.db_service.update_email_status(str(draft["gmail_id"]), "REVIEWED")
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

    def _handle_poller_status(
        self,
        tenant_id: str,
        user_id: Optional[int],
        user: Optional[Any] = None,
    ) -> str:
        """Build detailed poller and cadence status card with accurate connection state."""
        ws_config = self.db_service.get_workspace_poller_config(tenant_id)
        user_config = self.db_service.get_user_poller_config(user_id, tenant_id) if user_id is not None else None

        from core_platform.app.identity.service import get_user_identity_service
        user_service = get_user_identity_service()

        resolved_user = user
        if resolved_user is None and user_id is not None:
            resolved_user = user_service.get_user_by_id(user_id)

        has_oauth = bool(getattr(resolved_user, "encrypted_oauth_tokens", None)) if resolved_user else False

        # Member accounts in tenant
        effective_t = tenant_id if (tenant_id and tenant_id not in ("platform", "*")) else (getattr(resolved_user, "tenant_id", None) if resolved_user else None)
        if effective_t and effective_t not in ("platform", "*"):
            all_users = user_service.list_users(tenant_id=effective_t)
        else:
            all_users = [resolved_user] if resolved_user else []
        tenant_users = [
            u for u in all_users
            if any(c in ("mail_organizer", "*", "all") for c in (getattr(u, "allowed_cartridges", None) or []))
        ]
        total_members = len(tenant_users)
        connected_members = sum(1 for u in tenant_users if bool(getattr(u, "encrypted_oauth_tokens", None)))

        if total_members == 0 and resolved_user:
            total_members = 1
        if connected_members == 0 and has_oauth:
            connected_members = 1

        if not ws_config.is_master_enabled:
            ws_status = "⏸️ Paused"
        elif connected_members == 0:
            ws_status = "⚠️ Ready (0 Connected Accounts — Setup Required)"
        else:
            ws_status = f"🟢 Active ({connected_members} of {total_members} Connected)"

        if not has_oauth:
            user_status = "⚠️ Not Connected (Setup Required)"
        elif user_config:
            user_status = "🟢 Active" if user_config.is_poller_enabled else "⏸️ Paused"
        else:
            user_status = "🟢 Active (Default)"

        interval_m = (user_config.poll_interval_seconds if user_config else ws_config.default_poll_interval_seconds) // 60
        window = (user_config.active_window if user_config else "24x7") or "24x7"
        last_poll = (
            user_config.last_polled_at.strftime("%Y-%m-%d %H:%M UTC")
            if (user_config and user_config.last_polled_at)
            else "Never"
        )
        cycles = user_config.total_cycles if user_config else 0
        emails = user_config.total_emails_fetched if user_config else 0
        err_note = f"\n⚠️ *Last Error:* {user_config.last_error}" if (user_config and user_config.last_error) else ""

        action_hint = ""
        if not has_oauth:
            action_hint = "\n\n👉 *Action Required:* Your Google account is not connected yet. Reply `connect` to receive your setup link."

        return (
            "🔄 *Email Poller & Sync Status*\n\n"
            f"• *Workspace Master Switch:* {ws_status}\n"
            f"• *Your Personal Poller:* {user_status}\n"
            f"• *Sync Cadence:* Every {interval_m} minutes\n"
            f"• *Active Window:* {window}\n"
            f"• *Last Checked:* {last_poll}\n"
            f"• *Total Sync Cycles:* {cycles}\n"
            f"• *Total Emails Processed:* {emails}"
            f"{err_note}{action_hint}\n\n"
            "💡 _Commands:_\n"
            "• `poll now` — Trigger immediate inbox sync\n"
            "• `pause poller` — Pause automatic background checks\n"
            "• `resume poller` — Resume background checks"
        )

    async def _handle_poll_now(
        self,
        tenant_id: str,
        user_id: Optional[int],
        user: Optional[Any] = None,
        sender_phone: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Trigger on-demand manual sync for the user's Gmail inbox with Zero False Success enforcement."""
        if user_id is None:
            return "🔒 User identity not identified. Please re-authenticate via `connect`."

        from apps.mail_organizer.services.poller_manager import MailPollerManager
        mgr = MailPollerManager.get_instance()
        poll_res = await mgr.poll_user_now(user_id=user_id, tenant_id=tenant_id)

        # Check for failure / unauthenticated state (Zero False Success - GEES v3.1)
        if isinstance(poll_res, dict) and not poll_res.get("success", True):
            msg = str(poll_res.get("message", ""))
            # Detect unlinked Google account
            if "not linked a Google account" in msg or "no valid oauth" in msg.lower():
                magic_url = ""
                phone_num = sender_phone or getattr(user, "phone_number", None)
                if phone_num and base_url:
                    try:
                        from core_platform.app.identity.magic_link import build_magic_link_url
                        magic_url = build_magic_link_url(
                            user_id=str(user_id),
                            phone_number=phone_num,
                            tenant_id=tenant_id,
                            base_url=base_url,
                        )
                    except Exception as err:
                        logger.warning("[WhatsApp] Could not generate magic link: %s", err)

                link_text = (
                    f"\n\n👉 Click the link below to authorize Gmail & Calendar access:\n{magic_url}\n\n⏱️ _This secure link is valid for 15 minutes._\n\nOnce connected, reply `poll now` to start syncing!"
                    if magic_url
                    else "\n\n👉 Reply `connect` to receive a secure link to authorize your Google account."
                )
                return (
                    "⚠️ *Google Account Not Connected*\n\n"
                    f"Your account is not connected to Gmail yet, so your inbox cannot be synced.{link_text}"
                )

            # Other error failure
            return (
                "⚠️ *Inbox Sync Incomplete*\n\n"
                f"• *Target User:* `{user_id}`\n"
                "• *Status:* 🔴 Could not complete sync\n"
                f"• *Detail:* {msg}\n\n"
                "Please verify your Google connection or reply `connect` to re-authorize."
            )

        if isinstance(poll_res, dict):
            count = int(poll_res.get("emails_processed", 0))
        elif isinstance(poll_res, int):
            count = poll_res
        else:
            count = 0

        # [CODE-MARKER: FIX-WA-POLL-DRAWER-22] Return Stage 1 Interactive List Drawer when active emails exist
        salt = getattr(user, "user_secret_salt", None) if user else None
        summary_res = self._handle_inbox_summary(
            base_url or "http://localhost:8000",
            tenant_id=tenant_id,
            decrypt_salt=salt,
        )
        sync_banner = (
            "⚡ *On-Demand Inbox Sync Complete!*\n\n"
            f"• *Target User:* `{user_id}`\n"
            f"• *New Emails Processed:* {count}\n"
            "• *Status:* 🟢 Inbox up to date"
        )
        if isinstance(summary_res, dict):
            orig_body = str(summary_res.get("body_text") or "")
            combined_body = f"{sync_banner}\n\n{orig_body}"[:1024]
            summary_res["reply_message"] = combined_body
            summary_res["body_text"] = combined_body
            summary_res["search_index"] = f"{sync_banner}\n{summary_res.get('search_index', '')}"
            return summary_res

        return (
            f"{sync_banner}\n\n"
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
        has_oauth = bool(getattr(user, "encrypted_oauth_tokens", None)) if user else False

        if enable and not has_oauth:
            return (
                "🔄 *Poller Status Updated*\n\n"
                "Your personal email poller has been resumed, but your Google account is *not connected yet* ⚠️.\n\n"
                "👉 Reply `connect` to link your Gmail account so background checks can run."
            )

        state_str = "resumed and active 🟢" if enable else "paused ⏸️"
        return (
            "🔄 *Poller Status Updated*\n\n"
            f"Your personal email poller has been {state_str}.\n\n"
            "Cadence and active schedule will be honored accordingly."
        )

    def _handle_urgent_emails(
        self,
        tenant_id: Optional[str] = None,
        decrypt_salt: Optional[str] = None,
    ) -> Union[str, Dict[str, Any]]:
        """List high-urgency and critical emails via a Native Interactive List Drawer (`[CODE-MARKER: FIX-WA-INTENT-CARDS-11]`)."""
        raw_recent = self.db_service.get_recent_emails(limit=25, decrypt_salt=decrypt_salt, tenant_id=tenant_id)
        recent = [
            e for e in raw_recent
            if str(e.get("status") or "PROCESSED").upper() == "PROCESSED"
        ]
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

        rows: List[Dict[str, str]] = []
        index_parts: List[str] = [f"🚨 *Urgent & Critical Emails ({len(urgent)} items)*:"]
        for idx, email in enumerate(urgent[:10], 1):
            urgency = email.get("urgency_score", 7)
            cat = str(email.get("category", "Urgent"))
            subj = str(email.get("subject", "(No Subject)"))
            sndr = str(email.get("sender", "Unknown"))
            gid = str(email.get("gmail_id") or f"urg_{idx}")
            rows.append({
                "id": f"inspect_mail:{gid}"[:200],
                "title": f"{cat}: {subj}"[:24],
                "description": f"{sndr} • Urgency {urgency}/10"[:72],
            })
            index_parts.append(f"{idx}. *[{cat} - Urgency {urgency}/10]* {subj} From: {sndr}")

        brief_body = (
            f"🚨 *Urgent & Critical Emails ({len(urgent)} items)*\n"
            "Tap *Open Urgent* below to inspect and act on critical items."
        )
        return InteractiveWhatsAppPayload({
            "response_type": "interactive_list",
            "reply_message": brief_body,
            "body_text": brief_body,
            "header_text": "Urgent Executive Triage",
            "footer_text": "Tap Open Urgent to inspect & act",
            "button_label": "Open Urgent",
            "interactive_list": [{"title": "Urgent Decisions", "rows": rows}],
            "sections": [{"title": "Urgent Decisions", "rows": rows}],
            "search_index": "\n".join(index_parts),
        })

    def _handle_search_emails(
        self,
        search_term: str,
        tenant_id: Optional[str] = None,
        decrypt_salt: Optional[str] = None,
    ) -> str:
        """Search recent emails by keyword or sender."""
        recent = self.db_service.get_recent_emails(limit=50, decrypt_salt=decrypt_salt, tenant_id=tenant_id)
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
    ) -> Union[str, Dict[str, Any]]:
        """Answer natural language inquiries using live inbox context and LLM."""
        user = context.get("user")
        user_id_int: Optional[int] = _extract_user_id_int(user, context)
        tenant_id = str(context.get("tenant_id") or (getattr(user, "tenant_id", None) if user else "default_tenant"))
        user_name = str(getattr(user, "full_name", None) or "User")
        user_salt: Optional[str] = getattr(user, "user_secret_salt", None) if user else None
        q_lower = query.lower().strip()

        # [CODE-MARKER: FIX-WA-SESSION-STICKY-20] Conversational Nuance Reply on Active Inspected Card
        sender_phone_ctx = str(context.get("sender_phone") or "").strip()
        last_gid = self.get_last_inspected_gmail_id(sender_phone_ctx) if sender_phone_ctx else None
        if last_gid and any(
            w in q_lower
            for w in ["tell them", "reply saying", "respond with", "draft saying", "say that", "reply:", "draft:"]
        ):
            return await self._handle_generate_draft_on_demand(
                last_gid,
                tenant_id=tenant_id,
                user=user,
                custom_instruction=query,
            )

        # 1. Deterministic Intent Checks (Fast Pre-Execution)
        if any(w in q_lower for w in ["poll", "sync", "fetching", "background check"]):
            if any(w in q_lower for w in ["now", "immediate", "check inbox", "refresh", "fetch"]):
                return await self._handle_poll_now(
                    tenant_id=tenant_id,
                    user_id=user_id_int,
                    user=user,
                    sender_phone=str(context.get("sender_phone", "")),
                    base_url=base_url,
                )
            if any(w in q_lower for w in ["pause", "stop", "halt", "disable"]):
                return self._handle_toggle_user_poller(tenant_id=tenant_id, user=user, user_id=user_id_int, enable=False)
            if any(w in q_lower for w in ["resume", "start", "enable", "unpause"]):
                return self._handle_toggle_user_poller(tenant_id=tenant_id, user=user, user_id=user_id_int, enable=True)
            return self._handle_poller_status(tenant_id=tenant_id, user_id=user_id_int)

        if any(w in q_lower for w in ["urgent", "critical", "high priority", "emergency"]):
            return self._handle_urgent_emails(tenant_id=tenant_id, decrypt_salt=user_salt)

        if any(w in q_lower for w in ["draft", "reply", "replies", "outbox"]):
            return self._handle_staged_drafts(base_url, tenant_id=tenant_id, decrypt_salt=user_salt)

        if any(w in q_lower for w in ["task", "jira", "linear", "action item", "todo", "pm"]):
            return self._handle_pending_tasks(base_url, tenant_id=tenant_id)

        if q_lower.startswith("search ") or q_lower.startswith("find "):
            term = query.split(maxsplit=1)[-1].strip()
            if term:
                return self._handle_search_emails(term, tenant_id=tenant_id, decrypt_salt=user_salt)

        # 2. Gather Live State for Context Synthesis
        recent = self.db_service.get_recent_emails(limit=8, decrypt_salt=user_salt, tenant_id=tenant_id)
        drafts = [d for d in self.db_service.get_all_drafts(tenant_id=tenant_id, decrypt_salt=user_salt) if d.status == "STAGED"][:4]
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

    def _handle_stage2_card_inspection(
        self,
        gmail_id: str,
        tenant_id: str,
        user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Render Stage 2 800x418px PNG Infographic Card + 3 native intent-driven buttons (`[CODE-MARKER: FIX-WA-INTENT-ACTIONS-18]`)."""
        from core_platform.app.skills.card_image_renderer import CardImageRendererSkill, CardRenderSpec

        salt = getattr(user, "user_secret_salt", None) if user else None
        recent = self.db_service.get_recent_emails(limit=50, decrypt_salt=salt, tenant_id=tenant_id)
        matched = next((e for e in recent if str(e.get("gmail_id")) == gmail_id), None)
        draft_rec = self.db_service.get_draft(gmail_id, decrypt_salt=salt, active_only=True)

        category = str((matched or {}).get("category") or "@Action")
        urgency = int((matched or {}).get("urgency_score") or 8)
        sender = str((matched or {}).get("sender") or (draft_rec or {}).get("recipient") or "Executive Contact")
        subject = str((matched or {}).get("subject") or (draft_rec or {}).get("subject") or f"Thread {gmail_id}")
        snippet = str((matched or {}).get("snippet") or "Actionable email requiring executive review.")
        email_status = str((matched or {}).get("status") or "PROCESSED").upper()
        active_draft_body: Optional[str] = str(draft_rec.get("body")).strip() if (draft_rec and draft_rec.get("body")) else None
        candidate_reply: Optional[str] = str((matched or {}).get("suggested_reply") or "").strip() or None

        facts = self.db_service.query_entity_facts(tenant_id=tenant_id, source_msg_id=gmail_id, limit=2)
        citations_str = (
            ", ".join(f"[{str(f.get('source_channel', 'EMAIL')).capitalize()} #{f.get('source_msg_id')}]" for f in facts)
            if facts
            else "Verified Thread Context"
        )

        # [CODE-MARKER: FIX-WA-INTENT-ACTIONS-18] Intent-Driven Row 3 & Button Matrix (Master Spec §8.2)
        if email_status in ("ACTIONED", "REVIEWED", "SNOOZED", "DISCARDED"):
            badge_text = f"✅ {email_status} • {category}"[:24]
            badge_tone = "success"
            row3_label = "Lifecycle Status"
            row3_val = f"Completed ({email_status}) — Removed from active queue"
            caption = (
                f"✅ *Already {email_status.capitalize()}:* _{subject[:80]}_\n"
                f"*Context:* {snippet[:140]}\n"
                "*Status:* This email has already been triaged."
            )
            btn_items = [
                {"id": f"deep_inspect:{gmail_id}", "title": "Deep Inspect"},
                {"id": f"create_task:{gmail_id}", "title": "Create Task"},
                {"id": f"generate_draft:{gmail_id}", "title": "Generate Draft"},
            ]
        elif active_draft_body:
            # Step 2: Active STAGED draft exists -> Safety Gate Approval Card
            badge_text = f"{category} • P{urgency}"[:24]
            badge_tone = "danger" if urgency >= 9 else ("warning" if urgency >= 7 else "info")
            row3_label = "Staged Reply"
            row3_val = active_draft_body[:120]
            caption = (
                f"*Cross-Channel Context:* {citations_str[:80]} ({category} • P{urgency})\n"
                f"*Staged Reply:* _{active_draft_body[:200]}_\n"
                "*Decision:* Approve to dispatch, Deep Inspect, or Snooze."
            )
            btn_items = [
                {"id": f"approve_send:{gmail_id}", "title": "Approve & Send"},
                {"id": f"deep_inspect:{gmail_id}", "title": "Deep Inspect"},
                {"id": f"snooze_mail:{gmail_id}", "title": "Snooze / Skip"},
            ]
        elif category in ("@FYI", "@Promotions", "@Financial") or category.lower() in ("fyi", "promotions", "financial"):
            badge_text = f"{category} • P{urgency}"[:24]
            badge_tone = "info"
            row3_label = "Recommended Action"
            row3_val = "Informational / Notification — No reply required"
            caption = (
                f"*Cross-Channel Context:* {citations_str[:80]} ({category} • P{urgency})\n"
                f"*Summary:* _{snippet[:180]}_\n"
                "*Recommended Action:* Informational update — Mark Reviewed, Create PM Task, or Deep Inspect."
            )
            btn_items = [
                {"id": f"mark_done:{gmail_id}", "title": "Mark Reviewed"},
                {"id": f"create_task:{gmail_id}", "title": "Create Task"},
                {"id": f"deep_inspect:{gmail_id}", "title": "Deep Inspect"},
            ]
        elif category == "@Meeting" or category.lower() == "meeting":
            badge_text = f"{category} • P{urgency}"[:24]
            badge_tone = "warning"
            row3_label = "Scheduling Action"
            row3_val = (candidate_reply or "Check calendar availability & confirm slot")[:120]
            caption = (
                f"*Cross-Channel Context:* {citations_str[:80]} ({category} • P{urgency})\n"
                f"*Scheduling Ask:* _{snippet[:180]}_\n"
                "*Recommended Action:* Accept & Block Calendar, Generate Reply Draft, or Deep Inspect."
            )
            btn_items = [
                {"id": f"calendar_action:{gmail_id}", "title": "Accept & Block"},
                {"id": f"generate_draft:{gmail_id}", "title": "Generate Draft"},
                {"id": f"deep_inspect:{gmail_id}", "title": "Deep Inspect"},
            ]
        else:
            # Step 1: @Action / @Urgent / @VIP Email Context Evaluation (Before Draft is Staged)
            badge_text = f"{category} • P{urgency}"[:24]
            badge_tone = "danger" if urgency >= 9 else ("warning" if urgency >= 7 else "info")
            row3_label = "Recommended Action"
            row3_val = "Tap 'Generate Draft' (or reply with instructions) to stage response"
            caption = (
                f"*Cross-Channel Context:* {citations_str[:80]} ({category} • P{urgency})\n"
                f"*Executive Ask:* _{snippet[:180]}_\n"
                "*Next Step:* Tap *Generate Draft* (or reply with custom instructions) to synthesize a grounded response."
            )
            btn_items = [
                {"id": f"generate_draft:{gmail_id}", "title": "Generate Draft"},
                {"id": f"create_task:{gmail_id}", "title": "Create Task"},
                {"id": f"deep_inspect:{gmail_id}", "title": "Deep Inspect"},
            ]

        renderer = CardImageRendererSkill()
        spec = CardRenderSpec(
            badge_text=badge_text,
            badge_tone=badge_tone,
            title=subject[:72],
            subtitle=sender[:48],
            rows=[
                ("Sender | Topic", f"{sender[:24]} • {subject[:42]}"),
                ("Context / Ask", snippet[:120]),
                (row3_label, row3_val[:120]),
                ("Priority | SLA", f"Urgency {urgency}/10 • {citations_str[:48]}"),
            ],
            highlight_row_index=2,
            layout_mode="dossier",
            footer_note=citations_str[:80],
        )
        png_bytes = renderer.render_card_png(spec)

        return InteractiveWhatsAppPayload({
            "response_type": "interactive_buttons",
            "reply_message": caption,
            "body_text": caption,
            "header_image_bytes": png_bytes,
            "footer_text": f"Citations: {citations_str[:48]}",
            "interactive_buttons": btn_items,
            "buttons": btn_items,
            "search_index": f"{sender} {subject} {snippet} {active_draft_body or candidate_reply or ''} {citations_str}",
        })

    # [CODE-MARKER: FIX-ON-DEMAND-DRAFT-19] Step 2 On-Demand Draft Generation & Action Handlers
    async def _handle_generate_draft_on_demand(
        self,
        gmail_id: str,
        tenant_id: str,
        user: Optional[Any] = None,
        custom_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate and stage a draft reply on-demand (Step 2 of Master Spec §8.2) and return Safety Gate Card."""
        salt = getattr(user, "user_secret_salt", None) if user else None
        recent = self.db_service.get_recent_emails(limit=50, decrypt_salt=salt, tenant_id=tenant_id)
        matched = next((e for e in recent if str(e.get("gmail_id")) == gmail_id), None)

        sender = str((matched or {}).get("sender") or "recipient@company.com")
        subject = str((matched or {}).get("subject") or f"Thread {gmail_id}")
        thread_id = str((matched or {}).get("thread_id") or f"th_{gmail_id}")
        body_src = str((matched or {}).get("body") or (matched or {}).get("snippet") or "")
        candidate_reply = str((matched or {}).get("suggested_reply") or "").strip()

        user_name = str(getattr(user, "full_name", None) or "Account Lead")
        sender_name = sender.split("<")[0].replace('"', "").strip() if "<" in sender else sender.split("@")[0]

        if custom_instruction and custom_instruction.strip():
            reply_body = (
                f"Hi {sender_name},\n\n"
                f"{custom_instruction.strip()}\n\n"
                f"Best regards,\n{user_name}"
            )
        elif candidate_reply:
            reply_body = candidate_reply
        else:
            try:
                from apps.mail_organizer.graph.nodes.draft_node import draft_node
                from apps.mail_organizer.graph.state import MailOrganizerState

                draft_state: MailOrganizerState = {
                    "gmail_id": gmail_id,
                    "thread_id": thread_id,
                    "sender": sender,
                    "subject": subject,
                    "body": body_src,
                    "category": "@Action",
                    "responsibility_role": "PRIMARY_ACTIONEE",
                    "is_reply_necessary": True,
                    "tenant_id": tenant_id,
                    "user_name": user_name,
                }
                out_state = await draft_node(draft_state)
                reply_body = str(out_state.get("suggested_reply") or "").strip()
            except Exception:
                reply_body = ""
            if not reply_body:
                reply_body = (
                    f"Hi {sender_name},\n\n"
                    f"Thank you for your email regarding '{subject}'. I have reviewed the details and will follow up shortly.\n\n"
                    f"Best regards,\n{user_name}"
                )

        reply_subj = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        staged = self.db_service.store_draft(
            gmail_id=gmail_id,
            thread_id=thread_id,
            recipient=sender,
            subject=reply_subj,
            body=reply_body,
            user_salt=salt,
            tenant_id=tenant_id,
        )
        return self._handle_inspect_draft_card(str(staged.id), tenant_id=tenant_id, user=user)

    def _handle_mark_done(self, gmail_id: str, tenant_id: str) -> str:
        """Mark an informational/FYI email as REVIEWED and remove it from active triage."""
        self.db_service.update_email_status(gmail_id, "REVIEWED", tenant_id=tenant_id)
        return (
            f"✅ *Marked as Reviewed*\n\n"
            f"Thread `{gmail_id}` has been marked *REVIEWED* and removed from your active triage drawer."
        )

    def _handle_calendar_action(
        self,
        gmail_id: str,
        tenant_id: str,
        user: Optional[Any] = None,
    ) -> str:
        """Accept & block calendar slot for a @Meeting email and mark thread ACTIONED."""
        salt = getattr(user, "user_secret_salt", None) if user else None
        recent = self.db_service.get_recent_emails(limit=50, decrypt_salt=salt, tenant_id=tenant_id)
        matched = next((e for e in recent if str(e.get("gmail_id")) == gmail_id), None)
        subject = str((matched or {}).get("subject") or gmail_id)
        self.db_service.update_email_status(gmail_id, "ACTIONED", tenant_id=tenant_id)
        return (
            f"📅 *Calendar Slot Accepted & Blocked*\n\n"
            f"• *Meeting:* {subject}\n"
            f"• *Status:* Confirmed on calendar & thread `{gmail_id}` marked *ACTIONED*."
        )

    def _handle_create_task_from_mail(
        self,
        gmail_id: str,
        tenant_id: str,
        user: Optional[Any] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Create a PM Task from an email thread, mark thread ACTIONED, and return confirmation."""
        salt = getattr(user, "user_secret_salt", None) if user else None
        recent = self.db_service.get_recent_emails(limit=50, decrypt_salt=salt, tenant_id=tenant_id)
        matched = next((e for e in recent if str(e.get("gmail_id")) == gmail_id), None)
        subject = str((matched or {}).get("subject") or f"Follow up on {gmail_id}")
        sender = str((matched or {}).get("sender") or "Unknown")
        snippet = str((matched or {}).get("snippet") or subject)
        urgency = int((matched or {}).get("urgency_score") or 7)

        queued = self.db_service.queue_pm_task(
            summary=f"Follow up: {subject[:80]}",
            gmail_id=gmail_id,
            email_subject=subject,
            email_sender=sender,
            description=snippet,
            priority="High" if urgency >= 8 else "Medium",
            destination="jira",
            tenant_id=tenant_id,
        )
        self.db_service.update_email_status(gmail_id, "ACTIONED", tenant_id=tenant_id)
        task_ref = str(queued.task_id or queued.id)
        if hasattr(self, "_handle_inspect_task_card"):
            return self._handle_inspect_task_card(task_ref, tenant_id=tenant_id)
        return (
            f"📋 *PM Task Created (`{task_ref}`)*\n\n"
            f"• *Summary:* {queued.summary}\n"
            f"• *Priority:* {queued.priority}\n"
            f"• *Status:* Thread `{gmail_id}` marked *ACTIONED*."
        )

    def _handle_inspect_draft_card(
        self,
        draft_id: str,
        tenant_id: str,
        user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Render Step 2 Staged Draft Safety Gate Card (800x418px PNG + 3 native buttons) (`[CODE-MARKER: FIX-WA-INTENT-CARDS-11]`)."""
        from core_platform.app.skills.card_image_renderer import CardImageRendererSkill, CardRenderSpec

        salt = getattr(user, "user_secret_salt", None) if user else None
        all_drafts = self.db_service.get_all_drafts(tenant_id=tenant_id, decrypt_salt=salt)
        matched_draft = next(
            (d for d in all_drafts if str(d.id) == str(draft_id) or str(d.gmail_id) == str(draft_id)),
            None,
        )
        gmail_id = str(getattr(matched_draft, "gmail_id", None) or draft_id)
        recipient = str(getattr(matched_draft, "recipient", None) or "Recipient")
        subject = str(getattr(matched_draft, "subject", None) or f"Draft #{draft_id}")
        body_text = str(getattr(matched_draft, "body", None) or "Staged reply ready for approval.")
        status_str = str(getattr(matched_draft, "status", None) or "STAGED")

        renderer = CardImageRendererSkill()
        spec = CardRenderSpec(
            badge_text=f"DRAFT • {status_str}",
            badge_tone="success" if status_str == "SENT" else "warning",
            title=subject[:72],
            subtitle=f"To: {recipient[:48]}",
            rows=[
                ("Recipient", recipient[:80]),
                ("Thread Subject", subject[:80]),
                ("Staged Reply", body_text[:120]),
                ("Safety Gate", "AES-256-GCM Decrypted • Human Approval Gate"),
            ],
            highlight_row_index=2,
            layout_mode="dossier",
            footer_note=f"Draft #{draft_id} • Gmail Ref: {gmail_id}",
        )
        png_bytes = renderer.render_card_png(spec)
        caption = (
            f"*Draft #{draft_id} to {recipient}*\n"
            f"*Staged Reply:* _{body_text[:200]}_\n"
            "*Decision:* Tap *Approve & Send* to dispatch via Gmail API or *Discard*."
        )
        btn_items = [
            {"id": f"approve_send:{draft_id}", "title": "Approve & Send"},
            {"id": f"deep_inspect:{gmail_id}", "title": "Deep Inspect"},
            {"id": f"discard_draft:{draft_id}", "title": "Discard Draft"},
        ]
        return InteractiveWhatsAppPayload({
            "response_type": "interactive_buttons",
            "reply_message": caption,
            "body_text": caption,
            "header_image_bytes": png_bytes,
            "footer_text": f"Safety Gate • Draft #{draft_id}",
            "interactive_buttons": btn_items,
            "buttons": btn_items,
            "search_index": f"{recipient} {subject} {body_text}",
        })

    # [CODE-MARKER: FIX-WA-PM-DRAWER-26] Stage 2 PM Task Decision Card (800x418px PNG + 3 Native Buttons)
    def _handle_inspect_task_card(
        self,
        task_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """Render Stage 2 PM Task Decision Card (800x418px PNG + 3 native buttons)."""
        from core_platform.app.skills.card_image_renderer import CardImageRendererSkill, CardRenderSpec

        all_tasks = self.db_service.get_pending_pm_tasks(tenant_id=tenant_id)
        if not all_tasks and tenant_id:
            all_tasks = self.db_service.get_pending_pm_tasks()
        matched_task = next(
            (
                t for t in all_tasks
                if str(t.task_id) == str(task_id)
                or str(t.id) == str(task_id)
                or f"TASK-{t.id}" == str(task_id)
            ),
            None,
        )
        t_id = str(getattr(matched_task, "task_id", None) or task_id)
        summary = str(getattr(matched_task, "summary", None) or f"PM Task {t_id}")
        desc = str(getattr(matched_task, "description", None) or summary)
        dest = str(getattr(matched_task, "destination", None) or "jira")
        prio = str(getattr(matched_task, "priority", None) or "High")
        gmail_id = str(getattr(matched_task, "gmail_id", None) or "msg_pm")
        email_subj = str(getattr(matched_task, "email_subject", None) or summary)
        email_sender = str(getattr(matched_task, "email_sender", None) or "Internal")
        status_str = str(getattr(matched_task, "status", None) or "PENDING")

        renderer = CardImageRendererSkill()
        spec = CardRenderSpec(
            badge_text=f"PM TASK • {prio.upper()}"[:24],
            badge_tone="danger" if prio.lower() in ("high", "critical", "urgent") else "warning",
            title=summary[:72],
            subtitle=f"{t_id} • Target: {dest.upper()}",
            rows=[
                ("Task ID | Target", f"{t_id} -> {dest.upper()}"),
                ("Action Summary", summary[:120]),
                ("Source Thread", f"{email_subj[:60]} ({email_sender[:40]})"),
                ("Approval Gate", f"{status_str} • Human-in-the-Loop Export"),
            ],
            highlight_row_index=1,
            layout_mode="dossier",
            footer_note=f"PM Task {t_id} • Source Ref: {gmail_id}",
        )
        png_bytes = renderer.render_card_png(spec)
        caption = (
            f"📋 *PM Task `{t_id}` ({prio} Priority)*\n"
            f"• *Summary:* {summary[:160]}\n"
            f"• *Target Adapter:* `{dest}`\n"
            "*Decision:* Tap *Approve & Export* to dispatch or *Reject Task*."
        )
        btn_items = [
            {"id": f"approve_task:{t_id}", "title": "Approve & Export"},
            {"id": f"deep_inspect:{gmail_id}", "title": "Source Thread"},
            {"id": f"reject_task:{t_id}", "title": "Reject Task"},
        ]
        return InteractiveWhatsAppPayload({
            "response_type": "interactive_buttons",
            "reply_message": caption,
            "body_text": caption,
            "header_image_bytes": png_bytes,
            "footer_text": f"PM Queue • {t_id}",
            "interactive_buttons": btn_items,
            "buttons": btn_items,
            "search_index": f"{t_id} {summary} {desc} {dest} {email_subj} {email_sender}",
        })

    def _handle_deep_inspect(
        self,
        gmail_id: str,
        tenant_id: str,
        user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Render Approach B 360° Cross-Channel Timeline & Artifact Preview Card (`[CODE-MARKER: FIX-WA-DEEP-INSPECT-13]`)."""
        from core_platform.app.skills.card_image_renderer import CardImageRendererSkill, CardRenderSpec

        salt = getattr(user, "user_secret_salt", None) if user else None
        recent = self.db_service.get_recent_emails(limit=50, decrypt_salt=salt, tenant_id=tenant_id)
        matched = next((e for e in recent if str(e.get("gmail_id")) == gmail_id), None)
        draft_rec = self.db_service.get_draft(gmail_id, decrypt_salt=salt, active_only=True)
        facts = self.db_service.query_entity_facts(tenant_id=tenant_id, source_msg_id=gmail_id, limit=5)
        commitments = self.db_service.list_commitments(tenant_id=tenant_id, source_msg_id=gmail_id, limit=5)

        subj = str((matched or {}).get("subject") or (draft_rec or {}).get("subject") or gmail_id)
        sender = str((matched or {}).get("sender") or (draft_rec or {}).get("recipient") or "Executive Contact")
        active_draft_body: Optional[str] = str(draft_rec.get("body")).strip() if (draft_rec and draft_rec.get("body")) else None
        email_preview = str(
            active_draft_body
            or (matched or {}).get("body")
            or (matched or {}).get("snippet")
            or (matched or {}).get("suggested_reply")
            or "Thread content ready for inspection."
        )

        doc_lines = [line.strip() for line in email_preview.splitlines() if line.strip()]
        if not doc_lines:
            doc_lines = [email_preview[:120]]

        timeline_events: List[Tuple[str, str, str]] = [
            ("EMAIL", f"Inbound from {sender[:24]}", subj[:44]),
        ]
        for f in facts[:2]:
            ch = str(f.get("source_channel") or "FACT").upper()
            ent = f"{f.get('subject_entity')} -> {f.get('predicate')}"
            val = f"{f.get('object_value')} (#{f.get('source_msg_id')})"
            timeline_events.append((ch, ent[:36], val[:44]))
        for c in commitments[:1]:
            timeline_events.append((
                "WA",
                f"Commitment [{c.get('direction', 'OUT')}]",
                f"{c.get('deliverable_summary', '')} (Due: {c.get('raw_deadline_text', 'TBD')})"[:44],
            ))

        renderer = CardImageRendererSkill()
        spec = CardRenderSpec(
            badge_text="360° TIMELINE",
            badge_tone="info",
            title=subj[:72],
            subtitle=f"Grounded Audit • {sender[:40]}",
            layout_mode="timeline_360",
            document_preview_lines=doc_lines[:6],
            timeline_events=timeline_events[:4],
            footer_note=f"Facts: {len(facts)} • Commitments: {len(commitments)} • Ref: {gmail_id}",
        )
        png_bytes = renderer.render_card_png(spec)

        fact_summary = (
            ", ".join(f"{f.get('subject_entity')}={f.get('object_value')}" for f in facts[:3])
            if facts
            else "No symbolic overrides"
        )
        if active_draft_body:
            draft_line = f"• *Staged Draft:* _{active_draft_body[:180]}_"
            btn_items = [
                {"id": f"approve_send:{gmail_id}", "title": "Approve & Send"},
                {"id": f"discard_draft:{gmail_id}", "title": "Discard Draft"},
                {"id": f"snooze_mail:{gmail_id}", "title": "Snooze 4h"},
            ]
        else:
            draft_line = f"• *Thread Summary:* _{email_preview[:180]}_"
            btn_items = [
                {"id": f"generate_draft:{gmail_id}", "title": "Generate Draft"},
                {"id": f"mark_done:{gmail_id}", "title": "Mark Reviewed"},
                {"id": f"snooze_mail:{gmail_id}", "title": "Snooze 4h"},
            ]
        caption = (
            f"🔍 *360° Deep Inspection: {subj}*\n"
            f"• *Grounded Facts:* {fact_summary}\n"
            f"{draft_line}"
        )
        search_blob = "\n".join([
            caption,
            email_preview,
            *(f"{f.get('subject_entity')} {f.get('predicate')} {f.get('object_value')} {f.get('source_msg_id')}" for f in facts),
            *(f"{c.get('deliverable_summary')} {c.get('raw_deadline_text')}" for c in commitments),
        ])
        return InteractiveWhatsAppPayload({
            "response_type": "interactive_buttons",
            "reply_message": caption,
            "body_text": caption,
            "header_image_bytes": png_bytes,
            "footer_text": f"360° Grounded Ledger • {gmail_id[:24]}",
            "interactive_buttons": btn_items,
            "buttons": btn_items,
            "search_index": search_blob,
        })

    def _handle_provide_artifact(
        self,
        text_content: str,
        action_id: str,
        tenant_id: str,
        user_id: Optional[int],
    ) -> str:
        """Resolve a WAITING_FOR_USER_ARTIFACT request using user-supplied WhatsApp facts/context."""
        gmail_id = ""
        summary = text_content.strip()
        if action_id.startswith("provide_artifact:"):
            parts = action_id.split(":", 2)
            gmail_id = parts[1].strip() if len(parts) > 1 else ""
            if len(parts) > 2 and parts[2].strip():
                summary = parts[2].strip()
        elif text_content.lower().startswith("artifact "):
            tokens = text_content.split(maxsplit=2)
            if len(tokens) >= 3:
                gmail_id = tokens[1].strip()
                summary = tokens[2].strip()

        if not gmail_id:
            pending = self.db_service.get_pending_artifact_requests(tenant_id=tenant_id)
            if pending:
                gmail_id = pending[0].gmail_id

        if not gmail_id:
            return "ℹ️ No pending missing-artifact requests found."

        resolved = self.db_service.resolve_missing_artifact_request(
            gmail_id=gmail_id,
            resolved_content_summary=summary,
            tenant_id=tenant_id,
        )
        if resolved is None:
            return f"❌ Could not find a pending artifact request for `{gmail_id}`."

        self.db_service.index_fts_and_semantic_chunk(
            tenant_id=tenant_id,
            user_id=user_id,
            source_channel="WHATSAPP",
            msg_id=f"art-{gmail_id}",
            subject=f"Resolved Artifact for {gmail_id}",
            body_clean=summary,
            entity_tags=gmail_id,
        )
        return (
            f"✅ *Missing Artifact Resolved for `{gmail_id}`*\n\n"
            f"• *Recorded Context:* {summary}\n"
            "• *Status:* Grounded context indexed into Hybrid Store."
        )

