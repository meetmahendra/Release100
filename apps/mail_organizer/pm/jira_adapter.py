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
Jira Cloud REST API Adapter.

Exports approved project management deliverables to Jira Cloud with
non-blocking asynchronous execution.
"""

import base64
import json
import logging
import os
from typing import Any, Dict, Optional
import urllib.error
import urllib.request
import uuid

logger = logging.getLogger("mail_organizer.jira_adapter")


class JiraAdapter:
    """Exports tasks to Jira Cloud REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ) -> None:
        """Initialize Jira adapter with live credential resolution."""
        self.base_url = (base_url or os.getenv("JIRA_BASE_URL") or "https://canectar.atlassian.net").rstrip("/")
        self.email = email or os.getenv("JIRA_AUTH_EMAIL")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN")

        has_creds = bool(self.email and self.api_token and not self.api_token.startswith("your_"))
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = not has_creds

    async def create_issue(
        self,
        summary: str,
        description: str = "",
        project_key: str = "CANE",
        issue_type: str = "Task",
        priority: str = "Medium",
    ) -> Dict[str, Any]:
        """Create an issue in Jira Cloud."""
        fallback_id = f"{project_key}-{uuid.uuid4().hex[:4].upper()}"

        if not self.mock_mode and self.email and self.api_token:
            try:
                auth_str = f"{self.email}:{self.api_token}".encode("utf-8")
                b64_auth = base64.b64encode(auth_str).decode("utf-8")

                adf_payload = {
                    "fields": {
                        "project": {"key": project_key},
                        "summary": summary,
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": description or summary}
                                    ],
                                }
                            ],
                        },
                        "issuetype": {"name": issue_type},
                        "priority": {"name": priority},
                    }
                }

                url = f"{self.base_url}/rest/api/3/issue"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(adf_payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Basic {b64_auth}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=12.0) as resp:
                    if resp.status in (200, 201):
                        resp_data = json.loads(resp.read().decode("utf-8"))
                        live_key = resp_data.get("key", fallback_id)
                        return {
                            "success": True,
                            "platform": "jira",
                            "issue_id": live_key,
                            "issue_url": f"{self.base_url}/browse/{live_key}",
                            "summary": summary,
                            "status": "Created",
                        }
            except Exception as err:
                logger.warning("[JiraAdapter] Live Jira issue creation failed (%s). Using fallback.", err)

        # Fallback / mock mode
        return {
            "success": True,
            "platform": "jira",
            "issue_id": fallback_id,
            "issue_url": f"{self.base_url}/browse/{fallback_id}",
            "summary": summary,
            "status": "Created (Mock)" if self.mock_mode else "Created (Offline Fallback)",
        }
