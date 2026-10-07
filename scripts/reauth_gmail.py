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
Interactive Google OAuth2 Re-Authentication Utility for Mail Organizer.

Renews expired Google OAuth2 credentials and saves AES-256-GCM encrypted tokens
to logs/secure_tokens/google_oauth.enc.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional
import urllib.parse
import urllib.request
import webbrowser

from apps.mail_organizer.connectors.auth_manager import GoogleAuthManager, find_client_credentials

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
]

AUTH_CODE: Optional[str] = None
AUTH_ERROR: Optional[str] = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Local HTTP handler to intercept OAuth authorization code."""

    def do_GET(self) -> None:
        global AUTH_CODE, AUTH_ERROR
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            AUTH_CODE = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family: sans-serif; text-align: center; padding: 50px; background: #0f172a; color: #f8fafc;'>"
                b"<h1 style='color: #22c55e;'>Authentication Successful!</h1>"
                b"<p>You can close this tab and return to the terminal / dashboard.</p>"
                b"</body></html>"
            )
        else:
            AUTH_ERROR = params.get("error", ["Unknown error"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"<html><body style='font-family: sans-serif; text-align: center; padding: 50px; background: #0f172a; color: #f8fafc;'>"
                f"<h1 style='color: #ef4444;'>Authentication Failed</h1>"
                f"<p>{AUTH_ERROR}</p>"
                f"</body></html>".encode("utf-8")
            )

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard HTTP server console logging
        return


def main() -> None:
    print("=" * 70)
    print("  GOOGLE GMAIL & CALENDAR OAUTH2 RE-AUTHENTICATION")
    print("=" * 70)

    creds = find_client_credentials()
    if not creds:
        print("[ERROR] Could not find 'credentials.json'.")
        print("Please place your Google OAuth client secrets in credentials.json.")
        sys.exit(1)

    client_id = creds.get("client_id")
    client_secret = creds.get("client_secret")

    if not client_id or not client_secret:
        print("[ERROR] client_id or client_secret missing in credentials.json.")
        sys.exit(1)

    port = 8088
    redirect_uri = f"http://localhost:{port}"

    # Build Google OAuth consent URL
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(auth_params)

    print(f"\n[INFO] Starting local loopback receiver on {redirect_uri}...")
    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.timeout = 120.0

    print("\n[STEP 1/2] Opening browser for Google OAuth Consent...")
    print(f"If the browser does not open automatically, visit this URL:\n\n{auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("[INFO] Waiting for browser consent response (timeout: 120s)...")
    while not AUTH_CODE and not AUTH_ERROR:
        server.handle_request()

    if AUTH_ERROR or not AUTH_CODE:
        print(f"\n[FAILED] Authorization failed or timed out. Error: {AUTH_ERROR}")
        sys.exit(1)

    print(f"\n[STEP 2/2] Exchanging authorization code for OAuth tokens...")
    token_params = {
        "code": AUTH_CODE,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(token_params).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            token_response: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[FAILED] Token exchange failed: {e}")
        read_fn = getattr(e, "read", None)
        if callable(read_fn):
            print(f"Server response: {read_fn().decode('utf-8')}")
        sys.exit(1)

    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    expires_in = token_response.get("expires_in", 3600)

    if not access_token:
        print("[FAILED] Google OAuth did not return an access token.")
        sys.exit(1)

    expiry = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    token_payload: Dict[str, Any] = {
        "token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": SCOPES,
        "expiry": expiry.isoformat(),
    }

    # Encrypt and save to local secure token storage
    auth_mgr = GoogleAuthManager()
    auth_mgr.encrypt_and_save_token(token_payload)

    print("\n" + "=" * 70)
    print("  [SUCCESS] Google OAuth2 credentials successfully refreshed & encrypted!")
    print(f"  Access Token : {access_token[:12]}... (Valid for {expires_in}s)")
    print(f"  Refresh Token: {'Present' if refresh_token else 'Retained'}")
    print(f"  Vault Path   : {auth_mgr.storage_path}")
    print("=" * 70)

    # Verification probe
    print("\n[VERIFICATION] Verifying live connection to Gmail API...")
    from apps.mail_organizer.connectors.gmail_connector import GmailConnector

    async def verify_live() -> None:
        conn = GmailConnector()
        threads = await conn.fetch_unread_threads(max_results=5)
        print(f"  [OK] Successfully connected! Found {len(threads)} unread threads in Inbox.")
        for i, t in enumerate(threads, 1):
            sender_val = str(t.get("sender", "Unknown"))
            subject_val = str(t.get("subject", "No Subject"))[:50]
            thread_id_val = str(t.get("thread_id", ""))
            print(f"       {i}. [{sender_val}] {subject_val} (ID: {thread_id_val})")

    try:
        asyncio.run(verify_live())
    except Exception as e:
        print(f"  [WARN] Verification probe encountered an error: {e}")

    print("\nThe background poller will automatically ingest unread emails on its next tick.\n")


if __name__ == "__main__":
    main()
