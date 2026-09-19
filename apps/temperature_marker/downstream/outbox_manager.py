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
Edge Outbox Synchronization Manager.

Adheres to Plan 03 v1.3. Handles background draining of the local SQLite
outbox queue, guaranteeing zero data loss during network dropouts at retail kiosks.
"""

import json
from typing import Dict, List, Optional, Tuple

from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.downstream.base_connector import BaseDownstreamConnector


class OutboxManager:
    """Manages offline-first outbox queuing and upstream synchronization."""

    def __init__(
        self,
        db_service: DatabaseService,
        connector: Optional[BaseDownstreamConnector] = None,
    ) -> None:
        """Initialize OutboxManager.

        Args:
            db_service: DatabaseService instance.
            connector: Optional default downstream dispatch connector.
        """
        self.db_service = db_service
        self.default_connector = connector
        self._connector_cache: Dict[str, BaseDownstreamConnector] = {}
        if connector:
            self._connector_cache[connector.connector_name] = connector

    def _resolve_connector(self, target_gateway: str) -> BaseDownstreamConnector:
        """Resolve or dynamically create the appropriate downstream connector."""
        if target_gateway in self._connector_cache:
            return self._connector_cache[target_gateway]

        from apps.temperature_marker.downstream.base_connector import create_downstream_connector
        conn = create_downstream_connector(target_type=target_gateway)
        self._connector_cache[target_gateway] = conn
        return conn

    async def sync_pending_outbox(self, max_batch: int = 50) -> Tuple[int, int]:
        """Attempt to flush pending outbox items to their target downstream gateways.

        Args:
            max_batch: Maximum items to process in one sync cycle.

        Returns:
            Tuple of (synced_count: int, failed_count: int).
        """
        pending_items = self.db_service.get_pending_outbox_items(limit=max_batch)
        synced_count = 0
        failed_count = 0

        for item in pending_items:
            try:
                payload = json.loads(item.payload_json)
                target = getattr(item, "target_gateway", None) or "in_house_rest"
                connector = self._resolve_connector(target) if target else (self.default_connector or self._resolve_connector("in_house_rest"))
                success, msg = await connector.dispatch(payload)
                if success:
                    self.db_service.mark_outbox_synced(item.id)
                    synced_count += 1
                else:
                    self.db_service.mark_outbox_failed(item.id)
                    failed_count += 1
            except Exception:
                self.db_service.mark_outbox_failed(item.id)
                failed_count += 1

        return synced_count, failed_count
