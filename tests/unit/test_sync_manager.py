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
Unit Tests for EdgeCloudSyncManager and Ingress Sync Router.

Adheres strictly to GEES v2.0 Dual-Engine Verification Regime (Engine A).
"""

from fastapi.testclient import TestClient
import pytest

from core_platform.app.sync.merkle_reconciler import MerkleTree
from core_platform.app.sync.sync_manager import EdgeCloudSyncManager
from core_platform.main import app


def test_audit_records_reconciliation() -> None:
    """Verify 3-way reconciliation separates missing records accurately."""
    local_records = [
        {"seq": 1, "payload": "p1"},
        {"seq": 2, "payload": "p2_local_only"},
    ]
    cloud_records = [
        {"seq": 1, "payload": "p1"},
        {"seq": 3, "payload": "p3_cloud_only"},
    ]

    result = EdgeCloudSyncManager.reconcile_audit_records(local_records, cloud_records)
    assert not result["is_in_sync"]
    assert len(result["missing_on_cloud"]) == 1
    assert result["missing_on_cloud"][0]["payload"] == "p2_local_only"
    assert len(result["missing_on_local"]) == 1
    assert result["missing_on_local"][0]["payload"] == "p3_cloud_only"


def test_cloud_roster_snapshot_override() -> None:
    """Verify cloud roster records supersede local records by emp_code."""
    local_roster = [
        {"emp_code": "EMP-01", "name": "Alice Old", "role": "OPERATOR"},
        {"emp_code": "EMP-02", "name": "Bob", "role": "OPERATOR"},
    ]
    cloud_roster = [
        {"emp_code": "EMP-01", "name": "Alice Updated", "role": "SUPERVISOR"},
        {"emp_code": "EMP-03", "name": "Charlie", "role": "OPERATOR"},
    ]

    merged = EdgeCloudSyncManager.apply_cloud_roster_snapshot(local_roster, cloud_roster)
    merged_by_code = {m["emp_code"]: m for m in merged}

    assert len(merged) == 3
    assert merged_by_code["EMP-01"]["name"] == "Alice Updated"
    assert merged_by_code["EMP-01"]["role"] == "SUPERVISOR"
    assert merged_by_code["EMP-02"]["name"] == "Bob"
    assert merged_by_code["EMP-03"]["name"] == "Charlie"


def test_kiosk_status_reconciliation() -> None:
    """Verify sensor state is edge-authoritative while lockout flags are cloud-authoritative."""
    edge_state = {
        "kiosk_id": "K-04",
        "temperature_celsius": 3.8,
        "door_sensor": "CLOSED",
        "admin_locked": False,
    }
    cloud_state = {
        "admin_locked": True,
        "maintenance_mode": True,
    }

    reconciled = EdgeCloudSyncManager.reconcile_kiosk_status(edge_state, cloud_state)
    assert reconciled["temperature_celsius"] == 3.8
    assert reconciled["door_sensor"] == "CLOSED"
    assert reconciled["admin_locked"] is True
    assert reconciled["maintenance_mode"] is True
    assert "last_synced_at_utc" in reconciled


def test_sync_router_endpoints() -> None:
    """Verify /api/v1/sync/reconcile and /api/v1/sync/push-delta HTTP APIs."""
    client = TestClient(app)

    sample = [{"seq": 1, "data": "test_record"}]
    sample_tree = MerkleTree.from_records(sample)
    sample_root = sample_tree.get_root_hash()

    # 1. Reconcile matching hash
    rec_resp = client.post(
        "/api/v1/sync/reconcile",
        json={
            "tenant_id": "canectar_foods",
            "kiosk_id": "CANEBOT-PUNE-04",
            "client_root_hash": sample_root,
            "sample_records": sample,
        },
    )
    assert rec_resp.status_code == 200
    data = rec_resp.json()
    assert data["is_in_sync"] is True
    assert data["action_required"] == "NONE"

    # 2. Push Delta
    delta_resp = client.post(
        "/api/v1/sync/push-delta",
        json={
            "tenant_id": "canectar_foods",
            "kiosk_id": "CANEBOT-PUNE-04",
            "records": sample,
        },
    )
    assert delta_resp.status_code == 200
    delta_data = delta_resp.json()
    assert delta_data["status"] == "ACCEPTED"
    assert delta_data["accepted_count"] == 1
    assert delta_data["computed_batch_hash"] == sample_root
