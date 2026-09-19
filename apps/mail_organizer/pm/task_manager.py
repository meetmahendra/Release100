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
Project Management Task Manager & Human-in-the-Loop Approval Coordinator.

Coordinates staging, approval, and execution of deliverables to Jira or Linear.
"""

from typing import Any, Dict, List, Optional, Union

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.mail_organizer.database.models import PMActionQueue
from apps.mail_organizer.pm.jira_adapter import JiraAdapter
from apps.mail_organizer.pm.linear_adapter import LinearAdapter


class PMTaskManager:
    """Manages the lifecycle of extracted tasks and outbound platform export."""

    def __init__(
        self,
        db_service: MailDatabaseService,
        jira_adapter: Optional[JiraAdapter] = None,
        linear_adapter: Optional[LinearAdapter] = None,
    ) -> None:
        """Initialize task manager with adapters and database service."""
        self.db_service = db_service
        self.jira_adapter = jira_adapter or JiraAdapter()
        self.linear_adapter = linear_adapter or LinearAdapter()

    def stage_task(
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
    ) -> PMActionQueue:
        """Stage an extracted deliverable into the approval queue."""
        return self.db_service.queue_pm_task(
            summary=summary,
            gmail_id=gmail_id,
            email_subject=email_subject,
            email_sender=email_sender,
            description=description,
            priority=priority,
            project_key=project_key,
            assignee=assignee,
            due_date=due_date,
            destination=destination,
        )

    def get_pending_tasks(self) -> List[PMActionQueue]:
        """Return list of tasks waiting for user approval."""
        return self.db_service.get_pending_pm_tasks()

    async def approve_and_export(
        self,
        task_id: Union[int, str],
        destination: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approve and dispatch a staged task to its downstream target."""
        tasks = self.db_service.get_pending_pm_tasks()
        task = next((t for t in tasks if t.task_id == str(task_id) or str(t.id) == str(task_id)), None)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found or not in PENDING state"}

        target = destination or task.destination or "sqlite_queue"
        result: Dict[str, Any] = {}

        if target == "jira":
            result = await self.jira_adapter.create_issue(
                summary=task.summary,
                description=task.description or "",
                project_key=task.project_key or "CANE",
                priority=task.priority,
            )
            self.db_service.update_pm_task_status(task_id=task.task_id, status="EXECUTED", result_json=result)
        elif target == "linear":
            result = await self.linear_adapter.create_issue(
                title=task.summary,
                description=task.description or "",
            )
            self.db_service.update_pm_task_status(task_id=task.task_id, status="EXECUTED", result_json=result)
        else:
            # Default internal queue approval
            result = {"success": True, "destination": "sqlite_queue", "status": "APPROVED"}
            self.db_service.update_pm_task_status(task_id=task.task_id, status="APPROVED", result_json=result)

        return {"success": True, "task_id": task.task_id, "export_result": result}

    def approve_and_sync_task(self, task_id: Any, target: str = "jira") -> Dict[str, Any]:
        """Synchronous wrapper for approving and exporting a staged task."""
        import asyncio

        tasks = self.db_service.get_pending_pm_tasks()
        task = None
        for t in tasks:
            if t.id == task_id or t.task_id == str(task_id):
                task = t
                break

        if not task:
            return {"success": False, "error": f"Task {task_id} not found in pending queue"}

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                # In active event loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    res = pool.submit(asyncio.run, self.approve_and_export(task.task_id, destination=target)).result()
            else:
                res = asyncio.run(self.approve_and_export(task.task_id, destination=target))
            return res
        except Exception as e:
            return {"success": False, "error": str(e)}

    def reject_task(self, task_id: Union[int, str], reason: str = "User rejected") -> bool:
        """Mark a staged task as rejected."""
        tasks = self.db_service.get_pending_pm_tasks()
        task = next((t for t in tasks if t.task_id == str(task_id) or str(t.id) == str(task_id)), None)
        target_id = task.task_id if task else task_id
        res = self.db_service.update_pm_task_status(
            task_id=target_id,
            status="REJECTED",
            result_json={"rejection_reason": reason},
        )
        return res is not None
