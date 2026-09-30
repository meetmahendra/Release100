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
Adaptive Authentication Strategies.

Adheres strictly to Plan 02 v1.3 Section 3.
Dispatches auth by channel type → SecurityContext.

Strategy A: Phone + Biometric (WhatsApp / Kiosk)
Strategy C: Local Username+Password → JWT (Web Admin)
Strategy D: Scoped API Key  (MCP / REST)
"""

import hashlib
import logging
from typing import Optional

from core_platform.app.auth.api_keys import get_api_key_manager
from core_platform.app.auth.jwt_utils import verify_jwt_token
from core_platform.app.auth.models import SecurityContext
from core_platform.app.config import settings

logger = logging.getLogger("core_platform.auth.strategies")


# ── Strategy A: Phone + Biometric (WhatsApp / Kiosk) ─────────────────────────

class PhoneBiometricStrategy:
    """Authenticates WhatsApp/kiosk senders by phone number and two-phase biometric verification (SEC-6).

    Stage 1: Channel phone identification grants operator routing context.
    Stage 2: Biometric face verification inside the pipeline promotes `is_biometric_verified=True`.
    """

    @staticmethod
    def authenticate(
        phone_number: str,
        tenant_id: str = "default_tenant",
        biometric_verified: bool = False,
    ) -> SecurityContext:
        """Authenticate a WhatsApp sender by phone number.

        Args:
            phone_number: Normalised E.164 phone number (e.g. "+919876543210").
            tenant_id: Tenant identifier.
            biometric_verified: True if face/PIN biometric verification has passed.

        Returns:
            SecurityContext with operator role and biometric verification status.
        """
        if not phone_number:
            return SecurityContext.unauthenticated()

        return SecurityContext(
            principal_id=phone_number,
            tenant_id=tenant_id,
            user_roles=["operator"],
            permitted_apps=list(settings.ENABLED_APPLICATIONS),
            auth_strategy="phone_biometric",
            is_authenticated=True,
            is_biometric_verified=biometric_verified,
        )

    @classmethod
    def complete_biometric_verification(cls, ctx: SecurityContext) -> SecurityContext:
        """Promote security context to full biometric verification (Phase 2)."""
        return ctx.model_copy(update={"is_biometric_verified": True})


# ── Password Hashing & Verification (SEC-1) ──────────────────────────────────

_PBKDF2_ITERATIONS = 100_000


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash a password using salted PBKDF2-HMAC-SHA256.

    Args:
        password: Plain text password string.
        salt: Optional 16-byte hex salt; generated securely if omitted.

    Returns:
        Formatted hash string: 'pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>'
    """
    import secrets
    if not salt:
        salt_bytes = secrets.token_bytes(16)
        salt_hex = salt_bytes.hex()
    else:
        salt_hex = salt
        salt_bytes = bytes.fromhex(salt_hex)

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        _PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt_hex}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a hashed representation.

    Supports:
    1. Modern salted PBKDF2 ('pbkdf2_sha256$<iterations>$<salt>$<hash>')
    2. Legacy unsalted SHA-256 (64 hex characters) for seamless backward compatibility.

    Args:
        plain_password: Plain text password.
        hashed_password: Stored hash string.

    Returns:
        True if password matches, False otherwise.
    """
    if not plain_password or not hashed_password:
        return False

    # 1. PBKDF2-HMAC-SHA256 salted hash
    if hashed_password.startswith("pbkdf2_sha256$"):
        try:
            parts = hashed_password.split("$")
            if len(parts) == 4:
                _, iter_str, salt_hex, expected_hex = parts
                iterations = int(iter_str)
                salt_bytes = bytes.fromhex(salt_hex)
                derived = hashlib.pbkdf2_hmac(
                    "sha256",
                    plain_password.encode("utf-8"),
                    salt_bytes,
                    iterations,
                )
                return _constant_time_compare(derived.hex(), expected_hex)
        except Exception as exc:
            logger.warning("[LocalJWTStrategy] PBKDF2 verification error: %s", exc)
            return False

    # 2. Legacy raw SHA-256 comparison with constant-time check
    legacy_hash = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
    return _constant_time_compare(legacy_hash, hashed_password)


# ── Strategy C: Local Username + Password → JWT (Web Admin) ──────────────────

class LocalJWTStrategy:
    """Authenticates web admin users with username + password → JWT.

    Credentials configured in platform settings (ADMIN_USERNAME / ADMIN_PASSWORD_HASH).
    Password comparison uses salted PBKDF2 or timing-safe SHA-256; never plaintext.
    """

    @staticmethod
    def authenticate(username: str, password: str) -> Optional[SecurityContext]:
        """Validate credentials and return a SecurityContext.

        Args:
            username: Plain-text username from the login form.
            password: Plain-text password from the login form.

        Returns:
            SecurityContext if credentials match, None otherwise.
        """
        admin_username = getattr(settings, "ADMIN_USERNAME", "admin")
        admin_pwd_hash = getattr(
            settings,
            "ADMIN_PASSWORD_HASH",
            # Default: SHA-256 of "release100_admin" — MUST be changed in production.
            "09a90aa59b326bd017f7ab55d475269d0f3f38ae7426ace6a3fb007ee2c09790",
        )

        if username != admin_username:
            return None

        if not verify_password(password, admin_pwd_hash):
            logger.warning("[LocalJWTStrategy] Invalid password attempt for user=%s", username)
            return None

        return SecurityContext(
            principal_id=username,
            tenant_id=settings.TENANT_ID,
            user_roles=["admin"],
            permitted_apps=list(settings.ENABLED_APPLICATIONS),
            auth_strategy="local_jwt",
            is_authenticated=True,
        )

    @staticmethod
    def authenticate_token(token: str) -> Optional[SecurityContext]:
        """Validate a JWT token from the session cookie.

        Args:
            token: Raw JWT string.

        Returns:
            SecurityContext if valid, None if invalid/expired.
        """
        return verify_jwt_token(token)


# ── Strategy D: Scoped API Key (MCP / REST) ───────────────────────────────────

class ScopedAPIKeyStrategy:
    """Authenticates MCP/REST clients via bearer API key."""

    @staticmethod
    def authenticate(raw_key: str) -> Optional[SecurityContext]:
        """Validate a bearer API key.

        Args:
            raw_key: Raw API key extracted from Authorization header
                     ("Bearer ak_live_...").

        Returns:
            SecurityContext if valid, None otherwise.
        """
        manager = get_api_key_manager()
        return manager.validate_key(raw_key)


# ── AuthResolver ──────────────────────────────────────────────────────────────

class AuthResolver:
    """Dispatches to the correct auth strategy based on the channel type.

    Call AuthResolver.resolve_whatsapp(), .resolve_web(), or .resolve_api_key()
    from the appropriate ingress handler.
    """

    @staticmethod
    def resolve_whatsapp(phone_number: str, tenant_id: str = "default_tenant") -> SecurityContext:
        """Resolve auth for a WhatsApp inbound message.

        Args:
            phone_number: Sender phone number.
            tenant_id: Tenant identifier.

        Returns:
            SecurityContext.
        """
        return PhoneBiometricStrategy.authenticate(phone_number, tenant_id)

    @staticmethod
    def resolve_web(token: str) -> Optional[SecurityContext]:
        """Resolve auth for a web admin session (JWT cookie).

        Args:
            token: JWT from the session cookie.

        Returns:
            SecurityContext if valid, None otherwise.
        """
        return LocalJWTStrategy.authenticate_token(token)

    @staticmethod
    def resolve_api_key(raw_key: str) -> Optional[SecurityContext]:
        """Resolve auth for an MCP/REST API request.

        Args:
            raw_key: Raw API key from Authorization header.

        Returns:
            SecurityContext if valid, None otherwise.
        """
        return ScopedAPIKeyStrategy.authenticate(raw_key)

    @staticmethod
    def resolve_credentials(username: str, password: str) -> Optional[SecurityContext]:
        """Resolve auth for web admin login form submission.

        Args:
            username: Admin username.
            password: Plain-text password.

        Returns:
            SecurityContext if credentials are valid, None otherwise.
        """
        return LocalJWTStrategy.authenticate(username, password)


# ── Helper ────────────────────────────────────────────────────────────────────

def _constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison to prevent timing attacks.

    Args:
        a: First string.
        b: Second string.

    Returns:
        True if strings are equal.
    """
    import hmac as _hmac
    return _hmac.compare_digest(a.encode(), b.encode())
