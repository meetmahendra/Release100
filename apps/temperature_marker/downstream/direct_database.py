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
Direct Enterprise Database Downstream Connector.

Adheres to Plan 03 v1.3 Section 7.
Inserts verified KioskNode temperature and attendance transactions directly
into an external relational database (PostgreSQL, MySQL, SQL Server) via SQLAlchemy.
"""

from typing import Any, Dict, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from apps.temperature_marker.downstream.base_connector import BaseDownstreamConnector


class DirectDatabaseConnector(BaseDownstreamConnector):
    """Dispatches attendance and chiller readings directly to an external relational database."""

    def __init__(
        self,
        connection_string: Optional[str] = None,
        table_name: str = "enterprise_attendance_logs",
        mock_mode: Optional[bool] = None,
    ) -> None:
        """Initialize DirectDatabaseConnector.

        Args:
            connection_string: SQLAlchemy DB URL (e.g. 'postgresql://user:pass@host/db').
            table_name: Destination enterprise table name.
            mock_mode: If explicitly set, controls mock simulation.
        """
        super().__init__(connector_name="direct_database")
        self.connection_string = connection_string or "sqlite:///:memory:"
        self.table_name = table_name
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = self.connection_string.startswith("sqlite:///:memory:")

        self._engine: Optional[Engine] = None
        if not self.mock_mode:
            try:
                self._engine = create_engine(self.connection_string, echo=False)
            except Exception:
                self._engine = None

    async def dispatch(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Insert payload into external relational database.

        Args:
            payload: Structured operational data dictionary.

        Returns:
            Tuple of (success: bool, status_message: str).
        """
        if "mock_offline" in payload and payload["mock_offline"]:
            return False, "Simulated database connection timeout: host unreachable"

        if self.mock_mode or self._engine is None:
            correlation_id = payload.get("correlation_id", "UNKNOWN")
            return True, f"Simulated DB Insert: Record '{correlation_id}' persisted to table '{self.table_name}'"

        try:
            with self._engine.connect() as conn:
                query = text(
                    f"INSERT INTO {self.table_name} "
                    f"(correlation_id, emp_code, kiosk_id, chiller_temp_c, haccp_status, distance_meters) "
                    f"VALUES (:correlation_id, :emp_code, :kiosk_id, :chiller_temp_c, :haccp_status, :distance_meters)"
                )
                conn.execute(query, {
                    "correlation_id": str(payload.get("correlation_id", "")),
                    "emp_code": str(payload.get("emp_code", "")),
                    "kiosk_id": str(payload.get("kiosk_id", "")),
                    "chiller_temp_c": float(payload.get("chiller_temp_c", 0.0)),
                    "haccp_status": str(payload.get("haccp_status", "UNKNOWN")),
                    "distance_meters": float(payload.get("distance_meters", 0.0)),
                })
                conn.commit()
            return True, f"Successfully committed record to {self.table_name}"
        except Exception as exc:
            return False, f"Database insert failed on {self.table_name}: {exc}"
