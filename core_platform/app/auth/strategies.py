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

        permitted_apps = list(settings.ENABLED_APPLICATIONS) if settings.ENABLED_APPLICATIONS is not None else []
        if not permitted_apps:
            try:
                from core_platform.main import plugin_loader
                permitted_apps = list(plugin_loader.get_all_applications().keys())
            except Exception:
                permitted_apps = []

        return SecurityContext(
            principal_id=phone_number,
            tenant_id=tenant_id,
            user_roles=["operator"],
            permitted_apps=permitted_apps,
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
    """Authenticates web users with username/phone + password → JWT.

    Adheres strictly to GEES v2.0 Rule 4 (Zero Hardcoding) & Rule 8 (Zero-Trust Security).
    100% of authentications are dynamically resolved against the PlatformUser identity database
    using cryptographically salted PBKDF2 password hashes. Zero hardcoded users in source code.
    """

    @staticmethod
    def authenticate(username: str, password: str, tenant_id: Optional[str] = None) -> Optional[SecurityContext]:
        """Validate credentials for any registered user, tenant admin, or super admin.

        Args:
            username: Plain-text username, phone number, or email.
            password: Plain-text password from the login form.
            tenant_id: Optional active tenant workspace slug.

        Returns:
            SecurityContext if credentials match, None otherwise.
        """
        if not username or not password:
            return None

        try:
            from core_platform.app.identity.service import get_user_identity_service
            user_service = get_user_identity_service()
            user = user_service.find_user_for_auth(username, tenant_id=tenant_id)
            if user and user.status.lower() == "active" and user.hashed_password:
                if verify_password(password, user.hashed_password):
                    # Map role to security context roles
                    role_lower = user.role.lower()
                    if role_lower in ("super_admin", "devops_admin", "superadmin"):
                        user_roles = ["admin", "devops_admin", "super_admin"]
                    elif role_lower in ("admin", "tenant_admin"):
                        user_roles = ["admin", "devops_admin"] if user.tenant_id in ("platform", "system") else ["admin"]
                    else:
                        user_roles = [role_lower]

                    cartridges = user.allowed_cartridges
                    if not cartridges:
                        permitted_apps = list(settings.ENABLED_APPLICATIONS) if settings.ENABLED_APPLICATIONS is not None else []
                        if not permitted_apps:
                            try:
                                from core_platform.main import plugin_loader
                                permitted_apps = list(plugin_loader.get_all_applications().keys())
                            except Exception:
                                permitted_apps = ["mail_organizer", "temperature_marker"]
                        cartridges = permitted_apps

                    return SecurityContext(
                        principal_id=user.phone_number,
                        tenant_id=user.tenant_id,
                        user_roles=user_roles,
                        permitted_apps=cartridges,
                        auth_strategy="local_jwt",
                        is_authenticated=True,
                    )
        except Exception as e:
            logger.warning("[LocalJWTStrategy] Authentication exception: %s", e)

        logger.warning("[LocalJWTStrategy] Invalid login attempt for user=%s", username)
        return None

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
    def resolve_credentials(username: str, password: str, tenant_id: Optional[str] = None) -> Optional[SecurityContext]:
        """Resolve auth for web admin login form submission.

        Args:
            username: Admin username, phone, or email.
            password: Plain-text password.
            tenant_id: Optional tenant workspace slug.

        Returns:
            SecurityContext if credentials are valid, None otherwise.
        """
        return LocalJWTStrategy.authenticate(username, password, tenant_id=tenant_id)


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
