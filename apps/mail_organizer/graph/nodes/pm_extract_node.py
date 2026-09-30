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
Project Management Deliverable Extractor Node (`pm_extract_node`).

Adheres strictly to Plan 04 v1.0 Section 5.3.
Detects actionable work items in emails, extracts task details (title, priority,
due date, assignee), and stages them for human approval.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from apps.mail_organizer.graph.state import MailOrganizerState
from core_platform.app.config import settings

logger = logging.getLogger("mail_organizer.graph.pm_extract_node")


class ExtractedTaskItem(BaseModel):
    """Structured Pydantic schema for extracted project tasks."""

    summary: str = Field(description="Actionable task title under 80 characters")
    description: str = Field(description="Context and requirements for this deliverable")
    priority: str = Field(default="Medium", description="'High' | 'Medium' | 'Low'")
    due_date: str = Field(default="Next Business Day", description="Extracted deadline")
    assignee: str = Field(default="Fleet Ops Lead", description="Assigned owner or role")


async def pm_extract_node(state: MailOrganizerState) -> MailOrganizerState:
    """Scan email content and extract structured PM tasks via Gemini LLM or offline fallback."""
    t0 = time.perf_counter()

    category = state.get("category") or ""
    subject = state.get("subject") or ""
    body = state.get("body") or ""
    sender = state.get("sender") or ""
    gmail_id = state.get("gmail_id") or ""
    content = f"{subject}\n{body}"

    extracted_tasks: List[Dict[str, Any]] = []

    # Step 1: Attempt Live Platform LLM Task Extraction via Gateway
    try:
        from core_platform.app.llm.gateway import get_platform_llm_gateway

        gateway = get_platform_llm_gateway()
        prompt = (
            "You are an expert technical project manager. "
            "Analyze the email thread below and extract ALL actionable work items, deliverables, and assignments.\n\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Category: {category}\n"
            f"Body:\n{body[:2500]}\n\n"
            "Return a JSON object conforming strictly to this format:\n"
            "{\n"
            '  "tasks": [\n'
            "    {\n"
            '      "summary": "Imperative task title (e.g. \'Update chiller sensor calibration\', max 80 chars)",\n'
            '      "description": "Specific details, context, and expectations",\n'
            '      "priority": "High" | "Medium" | "Low",\n'
            '      "due_date": "Specific deadline or \'Next Business Day\'",\n'
            '      "assignee": "Person or role responsible (default \'Fleet Ops Lead\')"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            'If there are no actionable work items, return {"tasks": []}.'
        )
        res = await gateway.generate(
            task="text_generation",
            prompt=prompt,
            temperature=0.1,
            response_mime_type="application/json",
            operation_id=f"pm_extract_{gmail_id}",
        )
        if res and isinstance(res, dict):
            task_list = res.get("tasks")
            if task_list is None and "raw_text" in res:
                try:
                    loaded = json.loads(res["raw_text"])
                    if isinstance(loaded, list):
                        task_list = loaded
                    elif isinstance(loaded, dict):
                        task_list = loaded.get("tasks", [])
                except Exception:
                    pass
            if isinstance(task_list, list):
                for item in task_list:
                    if isinstance(item, dict) and item.get("summary"):
                        task = ExtractedTaskItem(**item)
                        extracted_tasks.append({
                            "gmail_id": gmail_id,
                            "summary": task.summary[:80].strip(),
                            "description": task.description,
                            "priority": task.priority,
                            "due_date": task.due_date,
                            "assignee": task.assignee,
                            "destination": "sqlite_queue",
                        })
    except Exception as exc:
        logger.debug("[PMExtractNode] LLM gateway failed: %s", exc)
        extracted_tasks.clear()

    # Step 2: Offline Deterministic Regex Fallback Engine
    if not extracted_tasks and category != "@Promotions":
        patterns = [
            r"(?:please|kindly)\s+([^\.\n\?]+(?:update|review|prepare|submit|check|verify|fix|deploy|inspect)[^\.\n\?]+)",
            r"(?:action\s+required[:\-]?\s*)([^\.\n\?]+)",
            r"(?:todo[:\-]?\s*)([^\.\n\?]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                task_raw = match.group(1).strip()
                summary = task_raw[:80].strip().capitalize()
                priority = "High" if category == "@Urgent" else "Medium"
                due_match = re.search(
                    r"(?:by|before|due)\s+([a-zA-Z0-9\s]+(?:friday|monday|eod|tomorrow|\d{1,2}(?:st|nd|rd|th)?))",
                    content,
                    re.IGNORECASE,
                )
                due_date = due_match.group(1).strip() if due_match else "Next Business Day"

                extracted_tasks.append({
                    "gmail_id": gmail_id,
                    "summary": summary,
                    "description": f"Extracted from email subject: '{subject}'\nFrom: {sender}\nContext snippet: {body[:250]}",
                    "priority": priority,
                    "due_date": due_date,
                    "assignee": "Fleet Ops Lead",
                    "destination": "sqlite_queue",
                })
                break

    state["pending_pm_tasks"] = extracted_tasks

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "pm_extract",
        "duration_ms": duration_ms,
        "tasks_extracted_count": len(extracted_tasks),
    })
    state["pipeline_trace"] = trace

    return state
