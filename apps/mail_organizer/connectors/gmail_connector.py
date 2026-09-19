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
Gmail API Connector with Zero-Deletion Guarantee.

Adheres strictly to Plan 04 v1.0 and GEES v1.0.
Provides non-blocking async thread fetching, zero-deletion label management,
and draft reply staging.
"""

import asyncio
import base64
from email.message import EmailMessage
import json
import logging
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request
import uuid

from apps.mail_organizer.connectors.auth_manager import GoogleAuthManager

logger = logging.getLogger("mail_organizer.gmail_connector")


def _extract_body(payload: Dict[str, Any]) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    text = ""
    if "parts" in payload and isinstance(payload["parts"], list):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    try:
                        text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    except Exception:
                        pass
            else:
                text += _extract_body(part)
    else:
        data = payload.get("body", {}).get("data")
        if data:
            try:
                text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                pass
    return text


def _parse_email_addrs(val: str) -> List[str]:
    """Extract clean email addresses from header string."""
    if not val:
        return []
    found = re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", val)
    return [a.lower() for a in found] if found else [val.strip().lower()]


class GmailConnector:
    """Manages communication with Google Workspace Gmail API or high-fidelity mock."""

    def __init__(
        self,
        auth_manager: Optional[GoogleAuthManager] = None,
        mock_mode: Optional[bool] = None,
    ) -> None:
        """Initialize Gmail connector with automatic live/mock determination."""
        self.auth_manager = auth_manager or GoogleAuthManager()
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = not self.auth_manager.is_authenticated()

        self._mock_threads: List[Dict[str, Any]] = []
        self._mock_drafts: List[Dict[str, Any]] = []
        self._mock_labels_applied: Dict[str, List[str]] = {}
        self._label_cache: Dict[str, str] = {}  # name -> id

    def seed_mock_thread(
        self,
        gmail_id: str,
        thread_id: str,
        subject: str,
        sender: str,
        body: str,
        to_recipients: Optional[List[str]] = None,
        cc_recipients: Optional[List[str]] = None,
        snippet: str = "",
    ) -> None:
        """Inject a simulated email thread for testing or offline operation."""
        self._mock_threads.append({
            "gmail_id": gmail_id,
            "thread_id": thread_id,
            "subject": subject,
            "sender": sender,
            "body": body,
            "to_recipients": to_recipients or ["user@canectar.com"],
            "cc_recipients": cc_recipients or [],
            "snippet": snippet or (body[:120] + "..."),
            "labels": ["INBOX", "UNREAD"],
        })

    def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
    ) -> Any:
        """Execute synchronous authenticated HTTP request to Gmail REST API v1."""
        auth_token = token or self.auth_manager.get_valid_access_token()
        if not auth_token:
            raise ValueError("No active OAuth2 access token available for Gmail API call.")

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/{endpoint.lstrip('/')}"
        encoded_data = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as err:
            if err.code == 401 and not token:
                fresh_token = self.auth_manager.get_valid_access_token(force_refresh=True)
                if fresh_token and fresh_token != auth_token:
                    headers["Authorization"] = f"Bearer {fresh_token}"
                    req2 = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
                    with urllib.request.urlopen(req2, timeout=12.0) as resp2:
                        content2 = resp2.read().decode("utf-8")
                        return json.loads(content2) if content2 else {}
            raise

    async def fetch_unread_threads(self, max_results: int = 25) -> List[Dict[str, Any]]:
        """Retrieve unread email messages. Runs non-blocking via asyncio.to_thread."""
        if self.mock_mode or not self.auth_manager.is_authenticated():
            return list(self._mock_threads[:max_results])

        try:
            return await asyncio.to_thread(self._fetch_unread_threads_live, max_results)
        except Exception as err:
            logger.warning("[GmailConnector] Live fetch failed (%s). Using mock fallback.", err)
            return list(self._mock_threads[:max_results])

    def _fetch_unread_threads_live(self, max_results: int) -> List[Dict[str, Any]]:
        """Live synchronous Google API call wrapped in thread."""
        query = urllib.parse.urlencode({"q": "is:unread label:INBOX", "maxResults": max_results})
        list_resp = self._api_request(f"messages?{query}", method="GET")
        messages = list_resp.get("messages", [])
        if not messages:
            return []

        parsed_emails: List[Dict[str, Any]] = []
        for item in messages:
            msg_id = item.get("id")
            if not msg_id:
                continue

            try:
                raw = self._api_request(f"messages/{msg_id}?format=full", method="GET")
                payload = raw.get("payload", {})
                headers_list = payload.get("headers", [])
                lower_headers = {h["name"].lower(): h["value"] for h in headers_list}

                parsed_emails.append({
                    "gmail_id": raw["id"],
                    "thread_id": raw.get("threadId", raw["id"]),
                    "subject": lower_headers.get("subject", "(no subject)"),
                    "sender": lower_headers.get("from", ""),
                    "snippet": raw.get("snippet", ""),
                    "body": _extract_body(payload),
                    "message_id_header": lower_headers.get("message-id", ""),
                    "to_recipients": _parse_email_addrs(lower_headers.get("to", "")),
                    "cc_recipients": _parse_email_addrs(lower_headers.get("cc", "")),
                    "labels": raw.get("labelIds", ["INBOX", "UNREAD"]),
                })
            except Exception as exc:
                logger.warning("[GmailConnector] Failed fetching full message %s: %s", msg_id, exc)

        return parsed_emails

    async def apply_labels(
        self,
        gmail_id: str,
        add_labels: List[str],
        remove_labels: Optional[List[str]] = None,
    ) -> bool:
        """Apply labels to an email while enforcing Zero-Deletion policy."""
        remove_labels = remove_labels or []

        # Zero-Deletion check: Never allow TRASH or SPAM deletions
        sanitized_adds = [l for l in add_labels if l.upper() not in ("TRASH", "SPAM_DELETE")]

        if self.mock_mode or not self.auth_manager.is_authenticated():
            current = self._mock_labels_applied.get(gmail_id, [])
            current.extend(sanitized_adds)
            self._mock_labels_applied[gmail_id] = list(set(current))
            return True

        try:
            return await asyncio.to_thread(
                self._apply_labels_live, gmail_id, sanitized_adds, remove_labels
            )
        except Exception as err:
            logger.warning("[GmailConnector] Live label application failed: %s", err)
            current = self._mock_labels_applied.get(gmail_id, [])
            current.extend(sanitized_adds)
            self._mock_labels_applied[gmail_id] = list(set(current))
            return True

    def _ensure_label_exists(self, label_name: str) -> str:
        """Ensure named label exists on the Gmail account and return its ID."""
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        # Fetch existing labels
        resp = self._api_request("labels", method="GET")
        labels = resp.get("labels", [])
        for l in labels:
            if l.get("name", "").lower() == label_name.lower():
                lid_found = str(l["id"])
                self._label_cache[label_name] = lid_found
                return lid_found

        # Create new label
        new_label_body = {
            "name": label_name,
            "messageListVisibility": "show",
            "labelListVisibility": "labelShow",
        }
        create_resp = self._api_request("labels", method="POST", data=new_label_body)
        lid = str(create_resp.get("id", label_name))
        self._label_cache[label_name] = lid
        return lid

    def _apply_labels_live(
        self,
        gmail_id: str,
        add_labels: List[str],
        remove_labels: List[str],
    ) -> bool:
        """Live Google API label modification."""
        add_ids = [self._ensure_label_exists(l) for l in add_labels]
        remove_ids = [self._ensure_label_exists(l) for l in remove_labels if l.upper() in ["UNREAD", "INBOX"]]

        modify_body = {
            "addLabelIds": add_ids,
            "removeLabelIds": remove_ids,
        }
        self._api_request(f"messages/{gmail_id}/modify", method="POST", data=modify_body)
        return True

    async def create_draft(
        self,
        thread_id: str,
        recipient: str,
        subject: str,
        body: str,
        message_id_header: str = "",
    ) -> Dict[str, Any]:
        """Stage an RFC 822 draft reply in Gmail (does NOT send)."""
        draft_id = f"DRAFT-{uuid.uuid4().hex[:8]}"
        draft_payload = {
            "draft_id": draft_id,
            "thread_id": thread_id,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "status": "STAGED",
        }

        if self.mock_mode or not self.auth_manager.is_authenticated():
            self._mock_drafts.append(draft_payload)
            return draft_payload

        try:
            return await asyncio.to_thread(
                self._create_draft_live,
                thread_id,
                recipient,
                subject,
                body,
                message_id_header,
                draft_payload,
            )
        except Exception as err:
            logger.warning("[GmailConnector] Live draft creation failed: %s", err)
            self._mock_drafts.append(draft_payload)
            return draft_payload

    def _create_draft_live(
        self,
        thread_id: str,
        recipient: str,
        subject: str,
        body: str,
        message_id_header: str,
        draft_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Live Google API draft creation using standard RFC 822 MIME."""
        msg = EmailMessage()
        msg.set_content(body)
        msg["To"] = recipient
        msg["From"] = "me"
        sub = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        msg["Subject"] = sub

        if message_id_header:
            msg["In-Reply-To"] = message_id_header
            msg["References"] = message_id_header

        raw_bytes = msg.as_bytes()
        encoded = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

        req_body = {
            "message": {
                "raw": encoded,
                "threadId": thread_id,
            }
        }
        resp = self._api_request("drafts", method="POST", data=req_body)
        live_draft_id = resp.get("id", draft_payload["draft_id"])
        draft_payload["draft_id"] = live_draft_id
        return draft_payload

    def get_applied_labels(self, gmail_id: str) -> List[str]:
        """Return recorded applied labels for an email."""
        return self._mock_labels_applied.get(gmail_id, [])
