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
Conversation Memory Store — Multi-Turn SQLite-Backed Dialogue History.

Adheres strictly to GEES v1.0 (Pillar 1 - Layer 1 Context & Pillar 3 Cryptographic Audit).
Addresses ISSUE-004: Multi-turn conversational memory for WhatsApp operators and fleet managers.
"""

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("core_platform.messaging.conversation_memory")

_DB_PATH = Path("logs/conversation_history.db")


class ConversationMemory:
    """Thread-safe SQLite store for multi-turn dialogue memory per phone number."""

    _instance: Optional["ConversationMemory"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "ConversationMemory":
        """Get or initialize singleton ConversationMemory instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path=db_path)
            return cls._instance

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize ConversationMemory with SQLite database file."""
        self._db_path = db_path or _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the conversation_turns table and indexes."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_phone   TEXT NOT NULL,
                    role           TEXT NOT NULL,
                    content        TEXT NOT NULL,
                    intent         TEXT,
                    timestamp_utc  REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conv_phone_time
                ON conversation_turns (sender_phone, timestamp_utc DESC)
            """)
            conn.commit()

    def record_turn(
        self,
        sender_phone: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
    ) -> None:
        """Record a dialogue turn into SQLite history.

        Args:
            sender_phone: Normalized phone number.
            role: 'user', 'assistant', or 'system'.
            content: Text message body.
            intent: Optional classified intent tag.
        """
        if not sender_phone or not content:
            return

        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """INSERT INTO conversation_turns
                           (sender_phone, role, content, intent, timestamp_utc)
                           VALUES (?, ?, ?, ?, ?)""",
                        (sender_phone, role, content, intent, time.time()),
                    )
                    conn.commit()
            except Exception as exc:
                logger.warning("[ConversationMemory] Failed to record turn: %s", exc)

    def get_recent_turns(
        self,
        sender_phone: str,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent dialogue turns for a sender ordered chronologically.

        Args:
            sender_phone: Sender phone number.
            limit: Maximum turns to return (default 6).

        Returns:
            List of dicts with role, content, intent, timestamp_utc.
        """
        if not sender_phone:
            return []

        with self._lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        """SELECT role, content, intent, timestamp_utc
                           FROM conversation_turns
                           WHERE sender_phone = ?
                           ORDER BY timestamp_utc DESC
                           LIMIT ?""",
                        (sender_phone, limit),
                    ).fetchall()
                # Reverse to chronological order (oldest -> newest)
                return [dict(r) for r in reversed(rows)]
            except Exception as exc:
                logger.warning("[ConversationMemory] Failed to get turns: %s", exc)
                return []

    def format_history_for_prompt(
        self,
        sender_phone: str,
        limit: int = 6,
    ) -> str:
        """Format recent dialogue turns into a prompt context string.

        Args:
            sender_phone: Sender phone number.
            limit: Number of turns to include.

        Returns:
            Formatted dialogue string or empty string if no history.
        """
        turns = self.get_recent_turns(sender_phone, limit=limit)
        if not turns:
            return ""

        formatted_lines = []
        for t in turns:
            speaker = "Operator" if t["role"] == "user" else "CaneBot Coordinator"
            formatted_lines.append(f"{speaker}: {t['content']}")

        return "\n".join(formatted_lines)

    def clear_history(self, sender_phone: str) -> None:
        """Clear conversation history for a specific phone number (e.g. on new shift)."""
        if not sender_phone:
            return

        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "DELETE FROM conversation_turns WHERE sender_phone = ?",
                        (sender_phone,),
                    )
                    conn.commit()
            except Exception as exc:
                logger.warning("[ConversationMemory] Failed to clear history: %s", exc)
