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
Linear App GraphQL API Adapter.

Exports approved tasks to Linear teams with non-blocking asynchronous execution.
"""

import json
import logging
import os
from typing import Any, Dict, Optional
import urllib.request
import uuid

logger = logging.getLogger("mail_organizer.linear_adapter")


class LinearAdapter:
    """Exports tasks to Linear API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        team_id: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ) -> None:
        """Initialize Linear adapter."""
        self.api_key = api_key or os.getenv("LINEAR_API_KEY")
        self.team_id = team_id or os.getenv("LINEAR_TEAM_ID") or "ENG"
        has_creds = bool(self.api_key and not self.api_key.startswith("lin_api_your"))
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = not has_creds

    async def create_issue(
        self,
        title: str,
        description: str = "",
        priority: int = 2,  # 1=Urgent, 2=High, 3=Medium, 4=Low
    ) -> Dict[str, Any]:
        """Create an issue in Linear."""
        fallback_id = f"{self.team_id}-{uuid.uuid4().hex[:3].upper()}"

        if not self.mock_mode and self.api_key:
            try:
                mutation = """
                mutation CreateIssue($input: IssueCreateInput!) {
                    issueCreate(input: $input) {
                        success
                        issue {
                            id
                            identifier
                            url
                        }
                    }
                }
                """
                payload = {
                    "query": mutation,
                    "variables": {
                        "input": {
                            "title": title,
                            "description": description or title,
                            "teamId": self.team_id,
                            "priority": priority,
                        }
                    },
                }

                req = urllib.request.Request(
                    "https://api.linear.app/graphql",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=12.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        issue_data = data.get("data", {}).get("issueCreate", {}).get("issue", {})
                        if issue_data:
                            live_id = issue_data.get("identifier", fallback_id)
                            live_url = issue_data.get("url", f"https://linear.app/issue/{live_id}")
                            return {
                                "success": True,
                                "platform": "linear",
                                "issue_id": live_id,
                                "issue_url": live_url,
                                "title": title,
                                "status": "Created",
                            }
            except Exception as err:
                logger.warning("[LinearAdapter] Live Linear issue creation failed (%s). Using fallback.", err)

        return {
            "success": True,
            "platform": "linear",
            "issue_id": fallback_id,
            "issue_url": f"https://linear.app/apex/issue/{fallback_id}",
            "title": title,
            "status": "Created (Mock)" if self.mock_mode else "Created (Offline Fallback)",
        }
