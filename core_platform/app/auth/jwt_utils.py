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
JWT Utilities — HS256 token creation and verification.

Adheres strictly to GEES v1.0 (Zero-Trust, Credential Isolation).
Uses stdlib hmac + hashlib — no PyJWT dependency required.
Token expiry: 8 hours. Algorithm: HS256 with Base64URL encoding.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

from core_platform.app.auth.models import SecurityContext

logger = logging.getLogger("core_platform.auth.jwt")

_TOKEN_EXPIRY_SECONDS = 8 * 3600  # 8 hours


def _b64url_encode(data: bytes) -> str:
    """Base64URL-encode bytes without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64URL-decode a string, adding padding as needed."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


import threading
import uuid

# ── JWT Revocation Registry (SEC-2) ──────────────────────────────────────────

class TokenBlacklistRegistry:
    """Thread-safe in-memory blacklist registry for revoked JWT tokens and JTIs."""

    _instance: Optional["TokenBlacklistRegistry"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TokenBlacklistRegistry":
        """Get singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._revoked_jtis: dict[str, float] = {}  # jti -> expires_at
        self._lock = threading.Lock()

    def revoke_token(self, token: str) -> bool:
        """Revoke a JWT token by extracting its JTI and expiry.

        Args:
            token: Raw compact JWT string.

        Returns:
            True if token was parsed and blacklisted, False otherwise.
        """
        if not token:
            return False
        try:
            parts = token.strip().split(".")
            if len(parts) != 3:
                return False
            payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
            jti = payload.get("jti")
            exp = float(payload.get("exp", time.time() + _TOKEN_EXPIRY_SECONDS))
            if jti:
                with self._lock:
                    self._purge_expired()
                    self._revoked_jtis[str(jti)] = exp
                logger.info("[TokenBlacklistRegistry] Revoked JWT jti=%s (exp=%s)", jti, exp)
                return True
        except Exception as exc:
            logger.warning("[TokenBlacklistRegistry] Error revoking token: %s", exc)
        return False

    def is_revoked(self, jti: Optional[str]) -> bool:
        """Check if a JTI has been revoked.

        Args:
            jti: Unique JWT ID claim string.

        Returns:
            True if revoked and active, False otherwise.
        """
        if not jti:
            return False
        with self._lock:
            self._purge_expired()
            return jti in self._revoked_jtis

    def clear(self) -> None:
        """Clear all revoked tokens (for testing)."""
        with self._lock:
            self._revoked_jtis.clear()

    def _purge_expired(self) -> None:
        """Remove expired JTIs from memory."""
        now = time.time()
        expired_keys = [k for k, exp in self._revoked_jtis.items() if now > exp]
        for k in expired_keys:
            del self._revoked_jtis[k]


def get_token_blacklist() -> TokenBlacklistRegistry:
    """Return platform token blacklist registry singleton."""
    return TokenBlacklistRegistry.get_instance()


def revoke_jwt_token(token: str) -> bool:
    """Helper to blacklist an active JWT."""
    return get_token_blacklist().revoke_token(token)


def create_jwt_token(
    principal_id: str,
    roles: list[str],
    permitted_apps: list[str],
    tenant_id: str = "default_tenant",
    secret_key: str = "",
    expiry_seconds: int = _TOKEN_EXPIRY_SECONDS,
    jti: Optional[str] = None,
) -> str:
    """Create an HS256 JWT token for web admin authentication.

    Args:
        principal_id: User or API key identifier.
        roles: List of role strings.
        permitted_apps: App cartridges this principal may access.
        tenant_id: Tenant identifier.
        secret_key: HMAC signing secret.
        expiry_seconds: Token lifetime in seconds.
        jti: Optional explicit JWT identifier; generated securely if None.

    Returns:
        Compact JWT string (header.payload.signature).
    """
    if not secret_key:
        from core_platform.app.config import settings
        secret_key = getattr(settings, "JWT_SECRET_KEY", "release100_dev_secret_change_in_prod")

    token_jti = jti or str(uuid.uuid4())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": principal_id,
        "tenant": tenant_id,
        "roles": roles,
        "apps": permitted_apps,
        "iat": int(time.time()),
        "exp": int(time.time()) + expiry_seconds,
        "jti": token_jti,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"

    signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_jwt_token(token: str, secret_key: str = "") -> Optional[SecurityContext]:
    """Verify an HS256 JWT and return a SecurityContext.

    Validates signature, expiration, and checks blacklist registry (SEC-2).

    Args:
        token: Compact JWT string.
        secret_key: HMAC signing secret.

    Returns:
        SecurityContext if valid and not revoked, None otherwise.
    """
    if not secret_key:
        from core_platform.app.config import settings
        secret_key = getattr(settings, "JWT_SECRET_KEY", "release100_dev_secret_change_in_prod")

    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            secret_key.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        actual_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            logger.warning("[JWTUtils] Signature mismatch — token rejected")
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))

        # Expiry check.
        if int(time.time()) > payload.get("exp", 0):
            logger.debug("[JWTUtils] Token expired for sub=%s", payload.get("sub"))
            return None

        # JTI Revocation check (SEC-2).
        jti = payload.get("jti")
        if jti and get_token_blacklist().is_revoked(jti):
            logger.warning("[JWTUtils] Revoked token presented (jti=%s) — access denied", jti)
            return None

        return SecurityContext(
            principal_id=str(payload.get("sub", "unknown")),
            tenant_id=str(payload.get("tenant", "default_tenant")),
            user_roles=list(payload.get("roles", [])),
            permitted_apps=list(payload.get("apps", [])),
            auth_strategy="local_jwt",
            is_authenticated=True,
        )
    except Exception as exc:
        logger.warning("[JWTUtils] Token verification error: %s", exc)
        return None
