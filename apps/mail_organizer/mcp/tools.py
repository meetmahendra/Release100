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
Model Context Protocol (MCP) Tool Suite for Mail & Calendar Automation.

Adheres strictly to Plan 04 v1.0 Section 6.
Exposes tools for external AI agents (Claude Desktop, Cursor) and WhatsApp ingress.
"""

from typing import Any, Dict, List, Optional

from apps.mail_organizer.connectors.calendar_connector import GoogleCalendarConnector
from apps.mail_organizer.connectors.gmail_connector import GmailConnector
from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.pm.task_manager import PMTaskManager


class MailOrganizerMCPTools:
    """Tool provider class exporting domain tools to the core platform MCP server."""

    def __init__(
        self,
        db_service: Optional[MailDatabaseService] = None,
        gmail_connector: Optional[GmailConnector] = None,
        calendar_connector: Optional[GoogleCalendarConnector] = None,
        pm_manager: Optional[PMTaskManager] = None,
    ) -> None:
        """Initialize MCP tool handler with domain dependencies."""
        self.db_service = db_service or MailDatabaseService()
        self.gmail_connector = gmail_connector or GmailConnector()
        self.calendar_connector = calendar_connector or GoogleCalendarConnector()
        self.pm_manager = pm_manager or PMTaskManager(db_service=self.db_service)

    async def mail_search_threads(self, query: str = "", max_results: int = 10) -> List[Dict[str, Any]]:
        """Search email threads matching a query (e.g. from:rajesh, is:unread, label:@Urgent)."""
        threads = await self.gmail_connector.fetch_unread_threads(max_results=max_results)
        if not query:
            return threads
        q_lower = query.lower()
        return [
            t for t in threads
            if q_lower in t.get("subject", "").lower() or q_lower in t.get("sender", "").lower()
        ]

    async def mail_get_thread_context(self, thread_id: str) -> Dict[str, Any]:
        """Retrieve message history and classification context for an email thread."""
        recent = self.db_service.get_recent_emails(limit=50)
        email = next((e for e in recent if e.get("thread_id") == thread_id or e.get("gmail_id") == thread_id), None)
        if not email:
            return {"found": False, "thread_id": thread_id, "message": "Thread context not found"}
        return {"found": True, "thread_id": thread_id, "email": email}

    async def mail_stage_draft_reply(
        self,
        thread_id: str,
        recipient: str,
        reply_body: str,
        subject: str = "Re: Project Update",
    ) -> Dict[str, Any]:
        """Stage a contextual draft reply for an email thread."""
        draft = await self.gmail_connector.create_draft(
            thread_id=thread_id,
            recipient=recipient,
            subject=subject,
            body=reply_body,
        )
        self.db_service.store_draft(
            gmail_id=thread_id,
            thread_id=thread_id,
            recipient=recipient,
            subject=subject,
            body=reply_body,
        )
        return {"success": True, "draft": draft}

    async def mail_check_calendar_availability(
        self,
        preferred_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Check free/busy slots on Google Calendar for proposed meeting dates."""
        proposal = await self.calendar_connector.synthesize_availability_proposal(preferred_date=preferred_date)
        busy_slots = await self.calendar_connector.get_free_busy()
        return {
            "success": True,
            "availability_proposal": proposal,
            "busy_slots_count": len(busy_slots),
        }

    async def mail_get_pending_pm_tasks(self) -> List[Dict[str, Any]]:
        """Retrieve pending project management tasks awaiting user approval."""
        tasks = self.pm_manager.get_pending_tasks()
        return [
            {
                "task_id": t.task_id,
                "summary": t.summary,
                "description": t.description,
                "priority": t.priority,
                "due_date": t.due_date,
                "status": t.status,
                "destination": t.destination,
            }
            for t in tasks
        ]

    async def mail_approve_pm_task(
        self,
        task_id: str,
        destination: str = "jira",
    ) -> Dict[str, Any]:
        """Approve and export a pending PM task to Jira or Linear."""
        return await self.pm_manager.approve_and_export(task_id=task_id, destination=destination)


def get_mail_organizer_mcp_tools() -> List[Dict[str, Any]]:
    """Return tool manifests for registration in core platform MCP server."""
    tools_instance = MailOrganizerMCPTools()
    return [
        {
            "name": "mail_search_threads",
            "description": "Search email threads matching a query",
            "handler": tools_instance.mail_search_threads,
        },
        {
            "name": "mail_get_thread_context",
            "description": "Retrieve full message history and classification context for a thread",
            "handler": tools_instance.mail_get_thread_context,
        },
        {
            "name": "mail_stage_draft_reply",
            "description": "Stage a contextual draft reply for an email thread",
            "handler": tools_instance.mail_stage_draft_reply,
        },
        {
            "name": "mail_check_calendar_availability",
            "description": "Check free/busy slots on Google Calendar for proposed meeting dates",
            "handler": tools_instance.mail_check_calendar_availability,
        },
        {
            "name": "mail_get_pending_pm_tasks",
            "description": "Retrieve pending project management tasks awaiting user approval",
            "handler": tools_instance.mail_get_pending_pm_tasks,
        },
        {
            "name": "mail_approve_pm_task",
            "description": "Approve and export a pending PM task to Jira/Linear",
            "handler": tools_instance.mail_approve_pm_task,
        },
    ]
