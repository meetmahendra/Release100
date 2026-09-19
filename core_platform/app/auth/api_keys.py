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
API Key Manager — Scoped API Key Engine (Strategy D).

Adheres strictly to Plan 02 v1.3 Section 3 (Auth Strategy D).
Features:
- Keys hashed SHA-256 at rest — raw key shown ONCE at creation.
- Key format: ak_live_<random_hex_32>
- Keys carry explicit scopes and per-key rate limits.
- In-memory store backed by persistent SQLite for edge reliability.
"""

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core_platform.app.auth.models import SecurityContext

logger = logging.getLogger("core_platform.auth.api_keys")

_DB_PATH = Path("logs/api_keys.db")
_KEY_PREFIX = "ak_live_"


class APIKeyManager:
    """Scoped API key creation, validation, and revocation.

    Uses SQLite for persistence so keys survive process restarts.
    Keys are hashed with SHA-256; the raw key is NEVER stored.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialise the APIKeyManager.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = db_path or _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── DB Layer ──────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the api_keys table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_hash       TEXT PRIMARY KEY,
                    label          TEXT NOT NULL,
                    principal_id   TEXT NOT NULL,
                    tenant_id      TEXT NOT NULL DEFAULT 'default_tenant',
                    roles          TEXT NOT NULL DEFAULT '[]',
                    permitted_apps TEXT NOT NULL DEFAULT '[]',
                    scopes         TEXT NOT NULL DEFAULT '[]',
                    max_rpm        INTEGER NOT NULL DEFAULT 60,
                    created_at     REAL NOT NULL,
                    expires_at     REAL,
                    revoked        INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.commit()

    # ── Key Operations ────────────────────────────────────────────────────────

    def create_key(
        self,
        label: str,
        principal_id: str,
        roles: List[str],
        permitted_apps: List[str],
        scopes: Optional[List[str]] = None,
        max_rpm: int = 60,
        tenant_id: str = "default_tenant",
        expiry_days: Optional[int] = None,
    ) -> Tuple[str, str]:
        """Create a new scoped API key.

        Args:
            label: Human-readable label (e.g. "Cursor MCP Integration").
            principal_id: Principal this key represents.
            roles: Role list for RBAC.
            permitted_apps: App cartridges this key can access.
            scopes: Fine-grained scope strings (e.g. ["temp_marker:read"]).
            max_rpm: Maximum requests per minute for this key.
            tenant_id: Tenant identifier.
            expiry_days: Key lifetime in days; None means no expiry.

        Returns:
            Tuple of (raw_key, key_hash). raw_key is shown ONCE — never stored.
        """
        raw_key = _KEY_PREFIX + secrets.token_hex(32)
        key_hash = _hash_key(raw_key)
        expires_at = time.time() + expiry_days * 86400 if expiry_days else None

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO api_keys
                   (key_hash, label, principal_id, tenant_id, roles, permitted_apps,
                    scopes, max_rpm, created_at, expires_at, revoked)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    key_hash, label, principal_id, tenant_id,
                    json.dumps(roles), json.dumps(permitted_apps),
                    json.dumps(scopes or []), max_rpm,
                    time.time(), expires_at,
                ),
            )
            conn.commit()

        logger.info("[APIKeyManager] Created key '%s' for principal=%s", label, principal_id)
        return raw_key, key_hash

    def validate_key(self, raw_key: str) -> Optional[SecurityContext]:
        """Validate an API key and return its SecurityContext.

        Args:
            raw_key: The raw API key string (Bearer header value).

        Returns:
            SecurityContext if valid, None if invalid/revoked/expired.
        """
        if not raw_key or not raw_key.startswith(_KEY_PREFIX):
            return None

        key_hash = _hash_key(raw_key)

        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM api_keys WHERE key_hash = ? AND revoked = 0",
                    (key_hash,),
                ).fetchone()

            if not row:
                return None

            # Expiry check.
            if row["expires_at"] and time.time() > row["expires_at"]:
                logger.debug("[APIKeyManager] Key expired for principal=%s", row["principal_id"])
                return None

            return SecurityContext(
                principal_id=str(row["principal_id"]),
                tenant_id=str(row["tenant_id"]),
                user_roles=json.loads(row["roles"]),
                permitted_apps=json.loads(row["permitted_apps"]),
                auth_strategy="api_key",
                is_authenticated=True,
            )
        except Exception as exc:
            logger.warning("[APIKeyManager] Validation error: %s", exc)
            return None

    def revoke_key(self, key_hash: str) -> bool:
        """Revoke an API key by its hash.

        Args:
            key_hash: SHA-256 hash of the key to revoke.

        Returns:
            True if a row was updated.
        """
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE api_keys SET revoked = 1 WHERE key_hash = ?", (key_hash,)
                )
                conn.commit()
                return cur.rowcount > 0
        except Exception as exc:
            logger.warning("[APIKeyManager] Revoke error: %s", exc)
            return False

    def list_keys(self) -> List[Dict[str, Any]]:
        """Return all non-secret key metadata (no raw keys, no hashes exposed in API).

        Returns:
            List of dicts with label, principal_id, created_at, revoked, etc.
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT key_hash, label, principal_id, tenant_id, permitted_apps, "
                    "scopes, max_rpm, created_at, expires_at, revoked FROM api_keys ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_key(raw_key: str) -> str:
    """SHA-256 hash a raw API key for storage.

    Args:
        raw_key: Raw API key string.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# Singleton
_api_key_manager: Optional[APIKeyManager] = None


def get_api_key_manager() -> APIKeyManager:
    """Return the platform APIKeyManager singleton."""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager
