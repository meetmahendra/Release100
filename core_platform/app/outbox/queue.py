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
Platform-Level Edge Resilience Outbox Queue.

Adheres strictly to Plan 01 v1.4 Section 1 and Plan 02 v1.3 Section 11.
Provides a SQLite-backed offline transaction queue as a PLATFORM SERVICE
available to ALL domain application cartridges (not just temperature_marker).

Guarantees:
  1. Zero data loss during network outages at factory/retail kiosks.
  2. Auto-sync on network restoration via configurable drain interval.
  3. Thread-safe append, status update, and batch drain operations.
"""

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class PlatformOutboxQueue:
    """
    Shared SQLite-backed outbox queue for offline-first edge resilience.

    All application cartridges use this queue to stage downstream payloads
    when the target system (REST, DB, ERP, Sheets) is temporarily unreachable.
    Payloads are drained automatically when connectivity recovers.
    """

    STATUS_PENDING: str = "PENDING"
    STATUS_SYNCED: str = "SYNCED"
    STATUS_FAILED: str = "FAILED"

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize the PlatformOutboxQueue.

        Args:
            db_path: Path to SQLite database file. Defaults to logs/platform_outbox.db.
        """
        self.db_path = db_path or Path("logs/platform_outbox.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create the outbox table if it does not already exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS platform_outbox (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id     TEXT NOT NULL UNIQUE,
                    app_id      TEXT NOT NULL,
                    target      TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'PENDING',
                    attempts    INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT NOT NULL,
                    synced_at   TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON platform_outbox (status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_app ON platform_outbox (app_id)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with WAL mode for concurrent read performance."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def enqueue(
        self,
        app_id: str,
        target: str,
        payload: Dict[str, Any],
        item_id: Optional[str] = None,
    ) -> str:
        """Enqueue a payload for deferred downstream dispatch.

        Args:
            app_id: Source application cartridge ID ('temperature_marker', 'mail_organizer').
            target: Downstream target identifier ('in_house_rest', 'direct_db', 'erp_odoo').
            payload: Structured data dict to dispatch when online.
            item_id: Optional idempotency key (generated if omitted).

        Returns:
            The item_id string for tracking.
        """
        item_id = item_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO platform_outbox
                        (item_id, app_id, target, payload_json, status, attempts, created_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (item_id, app_id, target, json.dumps(payload), self.STATUS_PENDING, now),
                )
                conn.commit()

        return item_id

    def get_pending(
        self,
        app_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve pending outbox items for drain processing.

        Args:
            app_id: Optional filter by application cartridge.
            limit: Maximum batch size.

        Returns:
            List of item dicts with id, item_id, app_id, target, payload_json, attempts.
        """
        with self._connect() as conn:
            if app_id:
                rows = conn.execute(
                    "SELECT * FROM platform_outbox WHERE status=? AND app_id=? ORDER BY id LIMIT ?",
                    (self.STATUS_PENDING, app_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM platform_outbox WHERE status=? ORDER BY id LIMIT ?",
                    (self.STATUS_PENDING, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def mark_synced(self, item_id: str) -> None:
        """Mark an item as successfully synced.

        Args:
            item_id: The idempotency key of the synced item.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE platform_outbox SET status=?, synced_at=? WHERE item_id=?",
                    (self.STATUS_SYNCED, now, item_id),
                )
                conn.commit()

    def mark_failed(self, item_id: str) -> None:
        """Increment attempt counter and mark item as FAILED.

        Args:
            item_id: The idempotency key of the failed item.
        """
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE platform_outbox SET status=?, attempts=attempts+1 WHERE item_id=?",
                    (self.STATUS_FAILED, item_id),
                )
                conn.commit()

    def requeue_failed(self, max_attempts: int = 5) -> int:
        """Reset FAILED items back to PENDING if under retry threshold.

        Args:
            max_attempts: Items with attempts >= this value are permanently failed.

        Returns:
            Count of items requeued for retry.
        """
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE platform_outbox SET status=? WHERE status=? AND attempts<?",
                    (self.STATUS_PENDING, self.STATUS_FAILED, max_attempts),
                )
                conn.commit()
                return cursor.rowcount

    def get_stats(self, app_id: Optional[str] = None) -> Dict[str, int]:
        """Return counts by status for monitoring and /health endpoint.

        Args:
            app_id: Optional filter by application.

        Returns:
            Dict with 'pending', 'synced', 'failed' counts.
        """
        filter_clause = "AND app_id=?" if app_id else ""
        params: Tuple[Any, ...] = (app_id,) if app_id else ()

        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status='SYNCED'  THEN 1 ELSE 0 END) AS synced,
                    SUM(CASE WHEN status='FAILED'  THEN 1 ELSE 0 END) AS failed
                FROM platform_outbox WHERE 1=1 {filter_clause}
                """,
                params,
            ).fetchone()
            return {
                "pending": int(row["pending"] or 0),
                "synced": int(row["synced"] or 0),
                "failed": int(row["failed"] or 0),
            }


# ── Platform Singleton ────────────────────────────────────────────────────────

_instance: Optional[PlatformOutboxQueue] = None
_singleton_lock = threading.Lock()


def get_platform_outbox() -> PlatformOutboxQueue:
    """Return the singleton PlatformOutboxQueue instance.

    Returns:
        Shared PlatformOutboxQueue for the current process.
    """
    global _instance
    with _singleton_lock:
        if _instance is None:
            _instance = PlatformOutboxQueue()
        return _instance
