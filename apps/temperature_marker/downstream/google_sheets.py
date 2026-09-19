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
Google Sheets Downstream Connector.

Adheres strictly to GEES v1.0 and Plan 03 v1.3 Section 8.
Appends attendance records to a Google Sheets spreadsheet via the REST API.
Implements BaseDownstreamConnector interface.

Mock mode: When GOOGLE_SHEETS_CREDENTIALS_PATH is not set, all operations
are logged and acknowledged without any network call (safe for development).
"""

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core_platform.app.config import settings

logger = logging.getLogger("temperature_marker.downstream.google_sheets")

try:
    from apps.temperature_marker.downstream.base_connector import BaseDownstreamConnector
    _HAS_BASE = True
except ImportError:
    _HAS_BASE = False
    class BaseDownstreamConnector:  # type: ignore[no-redef]
        """Fallback stub when base_connector is unavailable."""
        async def send_attendance_record(self, record: Dict[str, Any]) -> Tuple[bool, str]:  # type: ignore[empty-body]
            ...
        async def health_check(self) -> Dict[str, Any]:  # type: ignore[empty-body]
            ...

_MOCK_MODE_MSG = "[GoogleSheets] MOCK MODE — GOOGLE_SHEETS_CREDENTIALS_PATH not configured."


class GoogleSheetsConnector(BaseDownstreamConnector):
    """Appends attendance records to a Google Sheets spreadsheet.

    Uses the Google Sheets REST API with a service account JSON key.
    Falls back to mock mode when credentials are absent.
    """

    def __init__(
        self,
        spreadsheet_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        sheet_name: str = "AttendanceLog",
        timeout_seconds: float = 10.0,
    ) -> None:
        """Initialise the Google Sheets connector.

        Args:
            spreadsheet_id: Google Sheets spreadsheet ID.
            credentials_path: Path to service account JSON key file.
            sheet_name: Name of the target worksheet tab.
            timeout_seconds: HTTP request timeout.
        """
        super().__init__(connector_name="google_sheets")
        self._spreadsheet_id = spreadsheet_id or getattr(
            settings, "GOOGLE_SHEETS_SPREADSHEET_ID", ""
        )
        self._credentials_path = credentials_path or getattr(
            settings, "GOOGLE_SHEETS_CREDENTIALS_PATH", ""
        )
        self._sheet_name = sheet_name
        self._timeout = timeout_seconds
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0

    async def dispatch(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Dispatch attendance payload by delegating to send_attendance_record."""
        return await self.send_attendance_record(payload)

    @property
    def _is_mock(self) -> bool:
        """Return True when running in mock/dev mode (no credentials configured)."""
        return not (self._spreadsheet_id and self._credentials_path)

    async def send_attendance_record(self, record: Dict[str, Any]) -> Tuple[bool, str]:
        """Append an attendance record as a new row in the spreadsheet.

        Args:
            record: Dict with attendance fields (emp_code, name, temperature, timestamp, etc.).

        Returns:
            Tuple of (success: bool, message: str).
        """
        if self._is_mock:
            logger.info(
                "%s Pretending to append record for emp=%s",
                _MOCK_MODE_MSG,
                record.get("operator_emp_code", "unknown"),
            )
            return True, "mock_ok"

        try:
            token = await self._get_access_token()
            if not token:
                return False, "Failed to obtain Google OAuth2 token"

            row = self._record_to_row(record)
            url = (
                f"https://sheets.googleapis.com/v4/spreadsheets/{self._spreadsheet_id}"
                f"/values/{self._sheet_name}!A1:Z1:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS"
            )
            payload = {"values": [row]}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status in (200, 201):
                    return True, "row_appended"
                return False, f"HTTP {resp.status}"

        except urllib.error.HTTPError as exc:
            msg = f"HTTP {exc.code}: {exc.reason}"
            logger.error("[GoogleSheets] %s", msg)
            return False, msg
        except Exception as exc:
            logger.error("[GoogleSheets] Unexpected error: %s", exc)
            return False, str(exc)

    async def health_check(self) -> Dict[str, Any]:
        """Check connectivity to Google Sheets API.

        Returns:
            Dict with status, mock_mode, and spreadsheet_id fields.
        """
        status = "mock" if self._is_mock else "configured"
        if not self._is_mock:
            token = await self._get_access_token()
            status = "ok" if token else "auth_error"

        return {
            "connector": "google_sheets",
            "status": status,
            "mock_mode": self._is_mock,
            "spreadsheet_id": self._spreadsheet_id or "not_configured",
            "sheet_name": self._sheet_name,
        }

    async def _get_access_token(self) -> Optional[str]:
        """Obtain a Google OAuth2 access token using service account credentials.

        Caches the token until expiry.

        Returns:
            Access token string, or None on failure.
        """
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        if not self._credentials_path:
            return None

        cred_path = Path(self._credentials_path)
        if not cred_path.exists():
            logger.warning("[GoogleSheets] Credentials file not found: %s", self._credentials_path)
            return None

        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                creds = json.load(f)

            # Build a JWT assertion for service account OAuth2.
            import base64
            import hashlib
            import hmac

            now = int(time.time())
            header = base64.urlsafe_b64encode(
                json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
            ).rstrip(b"=").decode()
            payload_jwt = base64.urlsafe_b64encode(
                json.dumps({
                    "iss": creds.get("client_email", ""),
                    "scope": "https://www.googleapis.com/auth/spreadsheets",
                    "aud": "https://oauth2.googleapis.com/token",
                    "iat": now,
                    "exp": now + 3600,
                }).encode()
            ).rstrip(b"=").decode()

            # NOTE: For production, use google-auth library for proper RS256 signing.
            # This stub requests a token using the service account's private key via the
            # google-auth flow. Without google-auth installed, token request is skipped.
            try:
                import google.oauth2.service_account as _sa  # type: ignore[import-not-found]
                import google.auth.transport.requests as _tr  # type: ignore[import-not-found]
                sa_creds = _sa.Credentials.from_service_account_file(
                    str(cred_path),
                    scopes=["https://www.googleapis.com/auth/spreadsheets"],
                )
                sa_creds.refresh(_tr.Request())
                self._access_token = sa_creds.token
                self._token_expiry = time.time() + 3600
                return self._access_token
            except ImportError:
                logger.warning(
                    "[GoogleSheets] google-auth library not installed — cannot obtain token. "
                    "Install: pip install google-auth"
                )
                return None

        except Exception as exc:
            logger.error("[GoogleSheets] Token error: %s", exc)
            return None

    @staticmethod
    def _record_to_row(record: Dict[str, Any]) -> list[Any]:
        """Convert an attendance record dict to a flat spreadsheet row.

        Args:
            record: Attendance record dict.

        Returns:
            List of cell values in standard column order.
        """
        return [
            record.get("timestamp_utc", ""),
            record.get("kiosk_id", ""),
            record.get("operator_emp_code", ""),
            record.get("operator_name", ""),
            record.get("operator_status", ""),
            str(record.get("chiller_temp_c", "")),
            record.get("haccp_status", ""),
            str(record.get("face_confidence", "")),
            record.get("audit_record_hash", ""),
        ]
