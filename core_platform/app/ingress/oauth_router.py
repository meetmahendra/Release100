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
Google OAuth2 Magic Link Public Ingress Gateway.

Handles ephemeral, signed Magic Link browser authentication for WhatsApp users.
Allows mobile browser connection of Google Workspace credentials without requiring
passwords or desktop login.
"""

from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, Optional
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from core_platform.app.config import settings
from core_platform.app.identity.magic_link import verify_magic_link_token
from core_platform.app.identity.oauth_utils import (
    decrypt_user_tokens,
    encrypt_user_tokens,
    find_client_credentials,
)
from core_platform.app.identity.service import get_user_identity_service

logger = logging.getLogger("core_platform.ingress.oauth")

router = APIRouter(prefix="/auth/google", tags=["Google OAuth Ingress"])


def _render_html_page(title: str, heading: str, body_text: str, is_success: bool = True) -> HTMLResponse:
    """Render a clean, modern responsive status page for the mobile browser."""
    theme_color = "emerald" if is_success else "amber"
    icon = "✅" if is_success else "⚠️"
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} — Release100</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center p-4">
  <div class="max-w-md w-full bg-slate-800/90 border border-slate-700/60 rounded-2xl p-6 shadow-2xl text-center space-y-4">
    <div class="text-4xl">{icon}</div>
    <h1 class="text-xl font-bold text-{theme_color}-400">{heading}</h1>
    <p class="text-sm text-slate-300 leading-relaxed">{body_text}</p>
    <div class="pt-4 border-t border-slate-700/60">
      <p class="text-xs text-slate-500">You may close this browser tab and return to WhatsApp.</p>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html_content, status_code=200 if is_success else 400)


@router.get("/connect", response_class=HTMLResponse)
async def connect_google_oauth(
    request: Request,
    token: str = Query(..., description="Signed ephemeral Magic Link JWT token"),
) -> Any:
    """Validate Magic Link JWT and redirect user to Google OAuth consent screen."""
    payload = verify_magic_link_token(token)
    if not payload:
        return _render_html_page(
            title="Link Expired",
            heading="Authentication Link Expired or Invalid",
            body_text="This security link has expired or is invalid. Please send 'connect' to our WhatsApp bot to receive a fresh magic link.",
            is_success=False,
        )

    user_id = payload.get("user_id", "")
    user_service = get_user_identity_service()
    user = user_service.get_user_by_id(user_id)
    if not user:
        return _render_html_page(
            title="User Not Found",
            heading="User Record Not Found",
            body_text="We could not find a registered account matching this link. Please contact your system administrator.",
            is_success=False,
        )

    creds = find_client_credentials()
    if not creds:
        return _render_html_page(
            title="Configuration Error",
            heading="Google Credentials Missing",
            body_text="Google OAuth client credentials are not configured on this server node. Please contact your system administrator.",
            is_success=False,
        )

    client_id = creds.get("client_id")
    if not client_id:
        return _render_html_page(
            title="Configuration Error",
            heading="Invalid Client ID",
            body_text="Google client_id is missing from credentials configuration.",
            is_success=False,
        )

    base_url = (
        settings.ORCHESTRATOR_BASE_URL.rstrip("/")
        if settings.ORCHESTRATOR_BASE_URL
        else str(request.base_url).rstrip("/")
    )
    redirect_uri = f"{base_url}/auth/google/callback"

    scopes = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
    scope_str = " ".join(scopes)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope_str,
        "access_type": "offline",
        "prompt": "consent",
        "state": token,
    }

    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    logger.info("[OAuth Ingress] Redirecting user %s (phone: %s) to Google consent screen", user.id, user.phone_number)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback", response_class=HTMLResponse)
async def google_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
) -> HTMLResponse:
    """Exchange authorization code for OAuth tokens and bind encrypted vault to user."""
    if error:
        logger.warning("[OAuth Ingress] Google returned OAuth error: %s", error)
        return _render_html_page(
            title="Authentication Cancelled",
            heading="Google Authorization Cancelled",
            body_text=f"The connection request was not completed ({error}). You can request a new link in WhatsApp whenever you are ready.",
            is_success=False,
        )

    if not code or not state:
        return _render_html_page(
            title="Invalid Request",
            heading="Missing Code or State",
            body_text="Invalid callback parameters received from Google. Please initiate a new connection request.",
            is_success=False,
        )

    payload = verify_magic_link_token(state)
    if not payload:
        return _render_html_page(
            title="Link Expired",
            heading="Session Expired",
            body_text="Your connection session has expired. Please send 'connect' to WhatsApp to receive a new link.",
            is_success=False,
        )

    user_id = payload.get("user_id", "")
    user_service = get_user_identity_service()
    user = user_service.get_user_by_id(user_id)
    if not user:
        return _render_html_page(
            title="User Not Found",
            heading="User Account Not Found",
            body_text="No user account matches this session.",
            is_success=False,
        )

    creds = find_client_credentials()
    if not creds:
        return _render_html_page(
            title="Configuration Error",
            heading="Credentials Not Found",
            body_text="Google OAuth credentials are not found on this server node.",
            is_success=False,
        )

    client_id = creds.get("client_id")
    client_secret = creds.get("client_secret")
    base_url = (
        settings.ORCHESTRATOR_BASE_URL.rstrip("/")
        if settings.ORCHESTRATOR_BASE_URL
        else str(request.base_url).rstrip("/")
    )
    redirect_uri = f"{base_url}/auth/google/callback"

    try:
        # Exchange code for token payload
        token_req_data = urllib.parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_req_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            token_response = json.loads(resp.read().decode("utf-8"))

        # Add client credentials into token data for auto-refresh
        token_response["client_id"] = client_id
        token_response["client_secret"] = client_secret

        # Fetch user's Google Email address
        google_email = ""
        access_token = token_response.get("access_token")
        if access_token:
            try:
                ui_req = urllib.request.Request(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                with urllib.request.urlopen(ui_req, timeout=10.0) as ui_resp:
                    user_info = json.loads(ui_resp.read().decode("utf-8"))
                    google_email = str(user_info.get("email", ""))
            except Exception as ex:
                logger.warning("[OAuth Ingress] Could not fetch Google user info: %s", ex)

        if google_email:
            token_response["email"] = google_email
            token_response["account"] = google_email

        # Encrypt token payload with user's individual secret salt
        encrypted_payload = encrypt_user_tokens(token_response, user.user_secret_salt)

        # Store in user record
        user_service.update_user_tokens(
            user_id=user.id,
            encrypted_tokens=encrypted_payload,
            google_email=google_email or None,
        )

        logger.info(
            "[OAuth Ingress] Successfully bound Google OAuth credentials for user %s (email: %s)",
            user.id,
            google_email,
        )

        # Dispatch confirmation message over WhatsApp if configured
        if settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID:
            clean_to = user.phone_number.lstrip("+")
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    wa_url = f"https://graph.facebook.com/v21.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
                    headers = {
                        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                        "Content-Type": "application/json",
                    }
                    wa_body = {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": clean_to,
                        "type": "text",
                        "text": {
                            "body": f"✅ Google Workspace Connected!\n\nAccount: {google_email or 'Authorized'}\n\nYou can now manage your emails and calendar directly here in WhatsApp.",
                        },
                    }
                    await client.post(wa_url, headers=headers, json=wa_body)
            except Exception as wa_err:
                logger.warning("[OAuth Ingress] Could not send WhatsApp confirmation: %s", wa_err)

        return _render_html_page(
            title="Google Connected",
            heading="Account Connected Successfully!",
            body_text=f"Your Google account ({google_email or 'Authorized'}) has been securely linked to your WhatsApp number. You can now return to WhatsApp to interact with your mail and calendar.",
            is_success=True,
        )

    except Exception as exc:
        logger.error("[OAuth Ingress] Token exchange failed: %s", exc, exc_info=True)
        return _render_html_page(
            title="Connection Error",
            heading="Failed to Connect Account",
            body_text=f"An error occurred while linking your account ({exc}). Please try again or contact your administrator.",
            is_success=False,
        )
