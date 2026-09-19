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
import re
import time
from typing import Any, Dict, List, Optional
import urllib.request
from pydantic import BaseModel, Field

from apps.mail_organizer.graph.state import MailOrganizerState
from core_platform.app.config import settings


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

    # Step 1: Attempt Live Gemini LLM Task Extraction if API Key is configured
    if settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("your_"):
        try:
            model_name = getattr(settings, "GEMINI_ROUTING_MODEL", settings.GEMINI_MODEL)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
            prompt = (
                "You are an expert technical project manager. "
                "Analyze the email thread below and extract ALL actionable work items, deliverables, and assignments.\n\n"
                f"From: {sender}\n"
                f"Subject: {subject}\n"
                f"Category: {category}\n"
                f"Body:\n{body[:2500]}\n\n"
                "Return a JSON array of objects conforming strictly to this format:\n"
                "[\n"
                "  {\n"
                '    "summary": "Imperative task title (e.g. \'Update chiller sensor calibration\', max 80 chars)",\n'
                '    "description": "Specific details, context, and expectations",\n'
                '    "priority": "High" | "Medium" | "Low",\n'
                '    "due_date": "Specific deadline or \'Next Business Day\'",\n'
                '    "assignee": "Person or role responsible (default \'Fleet Ops Lead\')"\n'
                "  }\n"
                "]\n"
                "If there are no actionable work items, return []."
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    text_content = raw_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    parsed_list = json.loads(text_content)
                    if isinstance(parsed_list, list):
                        for item in parsed_list:
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
        except Exception:
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
