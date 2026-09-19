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
Operator Shift Session & Attendance Lifecycle Manager.

Ensures:
1. Daily duty attendance is marked ONCE per shift/day.
2. Subsequent kiosk check-ins record periodic HACCP Chiller Temperature logs.
3. In-memory session cache evicts on idle timeout and seamlessly reloads from SQLite on return.
4. Role-based configurable shift duration (Operator=12h, Technician=4h, Admin=8h).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("apps.temperature_marker.session_manager")

ROLE_SESSION_TTL_SECONDS: Dict[str, int] = {
    "OPERATOR": 12 * 3600,   # 12-hour retail shift
    "TECHNICIAN": 4 * 3600,  # 4-hour maintenance window
    "SUPERVISOR": 8 * 3600,  # 8-hour duty
    "ADMIN": 8 * 3600,
}


@dataclass
class ActiveSession:
    """Represents an active operator shift session in memory."""
    emp_code: str
    role: str
    shift_start_utc: datetime
    last_activity_time: float
    duty_checkin_recorded: bool
    duty_checkin_time_str: str
    kiosk_id: str


class OperatorSessionManager:
    """Thread-safe shift session and duty attendance manager."""

    _instance: Optional["OperatorSessionManager"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "OperatorSessionManager":
        """Singleton accessor."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        """Initialize session store."""
        self._sessions: Dict[str, ActiveSession] = {}
        self._lock = threading.Lock()

    def record_or_verify_checkin(
        self,
        emp_code: str,
        kiosk_id: str,
        role: str = "OPERATOR",
    ) -> Tuple[bool, str]:
        """Evaluate if this is the operator's first duty check-in of the day.

        Args:
            emp_code: Employee code.
            kiosk_id: Kiosk code.
            role: Operator role.

        Returns:
            Tuple of (is_new_attendance_today: bool, checkin_time_display: str).
        """
        now = datetime.now(timezone.utc)
        today_date = now.strftime("%Y-%m-%d")
        now_time_str = now.strftime("%I:%M %p UTC")

        with self._lock:
            session = self._sessions.get(emp_code)

            # 1. Check in-memory session if active today
            if session and session.duty_checkin_recorded:
                if session.shift_start_utc.strftime("%Y-%m-%d") == today_date:
                    session.last_activity_time = time.time()
                    return False, session.duty_checkin_time_str

            # 2. Check persistent SQLite database if memory was evicted
            from apps.temperature_marker.database.db_service import DatabaseService
            db = DatabaseService.get_instance()
            existing_today = db.has_attendance_today(emp_code)

            if existing_today is not None:
                chk_time = existing_today.checkin_time_utc.strftime("%I:%M %p UTC")
                self._sessions[emp_code] = ActiveSession(
                    emp_code=emp_code,
                    role=role,
                    shift_start_utc=existing_today.checkin_time_utc,
                    last_activity_time=time.time(),
                    duty_checkin_recorded=True,
                    duty_checkin_time_str=chk_time,
                    kiosk_id=kiosk_id,
                )
                logger.info("[SessionManager] Reloaded existing attendance session for %s from DB (check-in: %s)", emp_code, chk_time)
                return False, chk_time

            # 3. Fresh check-in for today
            self._sessions[emp_code] = ActiveSession(
                emp_code=emp_code,
                role=role,
                shift_start_utc=now,
                last_activity_time=time.time(),
                duty_checkin_recorded=True,
                duty_checkin_time_str=now_time_str,
                kiosk_id=kiosk_id,
            )
            logger.info("[SessionManager] Registered fresh duty check-in for %s at %s (%s)", emp_code, kiosk_id, now_time_str)
            return True, now_time_str

    def prune_idle_sessions(self, max_idle_seconds: int = 3600) -> int:
        """Evict inactive sessions from RAM to conserve memory while preserving DB truth."""
        now = time.time()
        pruned = 0
        with self._lock:
            for emp_code, session in list(self._sessions.items()):
                if (now - session.last_activity_time) > max_idle_seconds:
                    del self._sessions[emp_code]
                    pruned += 1
        if pruned > 0:
            logger.info("[SessionManager] Pruned %d idle operator sessions from memory", pruned)
        return pruned
