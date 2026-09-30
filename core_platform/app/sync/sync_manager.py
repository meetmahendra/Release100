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
Edge-to-Cloud Bidirectional Sync & Conflict Resolution Manager.

Adheres strictly to Plan 09 / GEES v2.0 Section 5:
- 3-Way Conflict Resolution Matrix:
  1. Audit Records: Append-only (non-destructive immutable replication).
  2. Roster / Operator Credentials: Cloud authoritative.
  3. Sensor State / Telemetry: Edge authoritative for physical readings; Cloud authoritative for lockouts.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from core_platform.app.sync.merkle_reconciler import MerkleTree

logger = logging.getLogger("core_platform.sync.manager")


class EdgeCloudSyncManager:
    """Manages state delta calculation and conflict resolution between Edge and Cloud."""

    @staticmethod
    def reconcile_audit_records(
        local_records: List[Dict[str, Any]],
        cloud_records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Reconcile append-only audit records between Edge and Cloud using Merkle trees.

        Returns:
            Dict containing:
                - 'is_in_sync': bool
                - 'local_root_hash': str
                - 'cloud_root_hash': str
                - 'missing_on_cloud': List of records present on Edge but missing on Cloud.
                - 'missing_on_local': List of records present on Cloud but missing on Edge.
        """
        local_tree = MerkleTree.from_records(local_records)
        cloud_tree = MerkleTree.from_records(cloud_records)

        local_root = local_tree.get_root_hash()
        cloud_root = cloud_tree.get_root_hash()

        if local_root == cloud_root:
            return {
                "is_in_sync": True,
                "local_root_hash": local_root,
                "cloud_root_hash": cloud_root,
                "missing_on_cloud": [],
                "missing_on_local": [],
            }

        # Build hash maps for exact record lookups
        local_hash_map = {MerkleTree.hash_record(r): r for r in local_records}
        cloud_hash_map = {MerkleTree.hash_record(r): r for r in cloud_records}

        missing_on_cloud = [r for h, r in local_hash_map.items() if h not in cloud_hash_map]
        missing_on_local = [r for h, r in cloud_hash_map.items() if h not in local_hash_map]

        logger.info(
            f"[Sync] Audit reconciliation: {len(missing_on_cloud)} records to push, {len(missing_on_local)} records to pull."
        )

        return {
            "is_in_sync": False,
            "local_root_hash": local_root,
            "cloud_root_hash": cloud_root,
            "missing_on_cloud": missing_on_cloud,
            "missing_on_local": missing_on_local,
        }

    @staticmethod
    def apply_cloud_roster_snapshot(
        local_roster: List[Dict[str, Any]],
        cloud_roster: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Apply Cloud-Authoritative roster updates to local edge roster.
        Cloud records supersede local records with matching 'emp_code' or 'phone_number'.
        """
        roster_by_code: Dict[str, Dict[str, Any]] = {}

        # Load local records first
        for emp in local_roster:
            code = emp.get("emp_code") or emp.get("phone_number") or ""
            if code:
                roster_by_code[code] = dict(emp)

        # Overwrite with cloud-authoritative records
        for cloud_emp in cloud_roster:
            code = cloud_emp.get("emp_code") or cloud_emp.get("phone_number") or ""
            if code:
                roster_by_code[code] = dict(cloud_emp)

        return list(roster_by_code.values())

    @staticmethod
    def reconcile_kiosk_status(
        edge_state: Dict[str, Any],
        cloud_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge Kiosk status according to Plan 09 Section 5.2:
        - Sensor temperature and physical hardware health: Edge authoritative.
        - Administrative lockout, emergency stop, maintenance flags: Cloud authoritative.
        """
        merged = dict(edge_state)

        # Cloud overrides administrative controls
        if "admin_locked" in cloud_state:
            merged["admin_locked"] = cloud_state["admin_locked"]
        if "maintenance_mode" in cloud_state:
            merged["maintenance_mode"] = cloud_state["maintenance_mode"]
        if "emergency_stop" in cloud_state:
            merged["emergency_stop"] = cloud_state["emergency_stop"]

        # Timestamp reconciliation
        merged["last_synced_at_utc"] = datetime.now(timezone.utc).isoformat()
        return merged
