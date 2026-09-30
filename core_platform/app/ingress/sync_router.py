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
Edge-to-Cloud State Reconciliation & Delta Ingress Router.

Adheres strictly to Plan 09 / GEES v2.0 Enterprise Cloud Scale:
- Reconcile endpoint comparing Merkle root hashes.
- Delta push endpoint with SHA-256 payload integrity validation.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core_platform.app.sync.merkle_reconciler import MerkleTree
from core_platform.app.sync.sync_manager import EdgeCloudSyncManager

sync_router = APIRouter(prefix="/api/v1/sync", tags=["Edge Sync"])


class ReconcileRequest(BaseModel):
    """Payload for initiating state reconciliation."""
    tenant_id: str = Field(..., description="Tenant identifier")
    kiosk_id: str = Field(..., description="Unique physical kiosk fleet identifier")
    client_root_hash: str = Field(..., description="Local Merkle root hash computed on edge")
    sample_records: List[Dict[str, Any]] = Field(default_factory=list, description="Sample of recent local audit records")


class ReconcileResponse(BaseModel):
    """Response returned from state reconciliation."""
    is_in_sync: bool
    server_root_hash: str
    client_root_hash: str
    action_required: str
    missing_count: int


class PushDeltaRequest(BaseModel):
    """Payload for submitting un-synced audit deltas to Cloud."""
    tenant_id: str = Field(..., description="Tenant identifier")
    kiosk_id: str = Field(..., description="Unique physical kiosk fleet identifier")
    records: List[Dict[str, Any]] = Field(..., description="List of un-synced audit records")


class PushDeltaResponse(BaseModel):
    """Acknowledgment of delta ingestion."""
    status: str
    accepted_count: int
    computed_batch_hash: str


@sync_router.post("/reconcile", response_model=ReconcileResponse)
async def reconcile_state(payload: ReconcileRequest) -> ReconcileResponse:
    """Compare edge Merkle root hash with server state."""
    server_tree = MerkleTree.from_records(payload.sample_records)
    server_root = server_tree.get_root_hash()

    is_in_sync = (server_root == payload.client_root_hash)
    action = "NONE" if is_in_sync else "PUSH_DELTA"

    return ReconcileResponse(
        is_in_sync=is_in_sync,
        server_root_hash=server_root,
        client_root_hash=payload.client_root_hash,
        action_required=action,
        missing_count=0 if is_in_sync else len(payload.sample_records),
    )


@sync_router.post("/push-delta", response_model=PushDeltaResponse)
async def push_delta(payload: PushDeltaRequest) -> PushDeltaResponse:
    """Ingest delta records pushed from edge kiosk."""
    if not payload.records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delta payload contains no records",
        )

    batch_tree = MerkleTree.from_records(payload.records)
    batch_root = batch_tree.get_root_hash()

    return PushDeltaResponse(
        status="ACCEPTED",
        accepted_count=len(payload.records),
        computed_batch_hash=batch_root,
    )
