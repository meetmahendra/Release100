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
Ephemeral Signed Magic Link Generator & Verifier.

Allows registered users to link their Google Workspace account
via mobile browser by clicking an ephemeral, HMAC-SHA256 signed link
sent over WhatsApp or generated in Admin Shell.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, Optional
import jwt

from core_platform.app.config import settings

logger = logging.getLogger("core_platform.identity.magic_link")

MAGIC_LINK_PURPOSE = "google_oauth_connect"


def generate_magic_link_token(
    user_id: Any,
    phone_number: str,
    tenant_id: str = "default_tenant",
    expiry_minutes: Optional[int] = None,
) -> str:
    """Generate a signed, short-lived JWT for WhatsApp Google OAuth connection.

    Args:
        user_id: PlatformUser ID (string or integer).
        phone_number: E.164 phone number.
        tenant_id: Tenant ID.
        expiry_minutes: Expiration window (defaults to settings.MAGIC_LINK_EXPIRY_MINUTES).

    Returns:
        Signed JWT string.
    """
    minutes = expiry_minutes or settings.MAGIC_LINK_EXPIRY_MINUTES
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=minutes)

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "phone": phone_number,
        "tenant_id": tenant_id,
        "purpose": MAGIC_LINK_PURPOSE,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }


    token: str = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    return token


def verify_magic_link_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a magic link token.

    Args:
        token: Signed JWT string.

    Returns:
        Decoded payload dict if valid, None if invalid or expired.
    """
    try:
        payload: Dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "purpose"]},
        )

        if payload.get("purpose") != MAGIC_LINK_PURPOSE:
            logger.warning("[MagicLink] Token purpose mismatch: %s", payload.get("purpose"))
            return None

        return {
            "user_id": str(payload.get("sub", "")),
            "phone_number": str(payload.get("phone", "")),
            "tenant_id": str(payload.get("tenant_id", "default_tenant")),
            "exp": payload.get("exp"),
        }
    except jwt.ExpiredSignatureError:
        logger.warning("[MagicLink] Token signature expired")
        return None
    except jwt.InvalidTokenError as err:
        logger.warning("[MagicLink] Invalid magic link token: %s", err)
        return None


def build_magic_link_url(
    user_id: str,
    phone_number: str,
    tenant_id: str = "default_tenant",
    base_url: Optional[str] = None,
    expiry_minutes: Optional[int] = None,
) -> str:
    """Construct full public Magic Link URL for WhatsApp OAuth linking.

    Args:
        user_id: PlatformUser ID.
        phone_number: E.164 phone number.
        tenant_id: Tenant ID.
        base_url: Base URL (defaults to settings.ORCHESTRATOR_BASE_URL or localhost).
        expiry_minutes: Token validity duration.

    Returns:
        Fully qualified URL string.
    """
    token = generate_magic_link_token(
        user_id=user_id,
        phone_number=phone_number,
        tenant_id=tenant_id,
        expiry_minutes=expiry_minutes,
    )

    effective_base = (
        (base_url or settings.ORCHESTRATOR_BASE_URL or f"http://localhost:{settings.ORCHESTRATOR_PORT}").rstrip("/")
    )
    return f"{effective_base}/auth/google/connect?token={token}"
