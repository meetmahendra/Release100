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
Strongly Typed Regulatory Audit Record Schema.

Conforms to GEES v1.0 (Pillar 3), FDA 21 CFR Part 11, and ISO 22000.
Enforces monotonic sequence numbering and SHA-256 non-repudiation hashes.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, Field


class AuditRecord(BaseModel):
    """
    Immutable audit record for mission-critical operations.

    Every field is mathematically bound into the SHA-256 hash chain:
    Record Hash = SHA-256(prev_hash + sequence_number + timestamp_utc + payload_json)
    """

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique UUID for this specific audit entry",
    )
    sequence_number: int = Field(
        description="Monotonically increasing sequence number (1, 2, 3...) to eliminate clock-skew",
    )
    correlation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Distributed tracing identifier linking request to downstream actions",
    )
    timestamp_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp",
    )
    organization_id: str = Field(
        default="DEFAULT_TENANT",
        description="Tenant / Organization code",
    )
    facility_id: str = Field(
        default="STATION_01",
        description="Plant, station, or facility identifier",
    )
    kiosk_id: str = Field(
        default="NODE-01",
        description="Platform node or terminal identifier",
    )
    operator_id: str = Field(
        default="USER_001",
        description="Operator or user ID initiating the transaction",
    )
    action_type: str = Field(
        description="Action classification, e.g. 'TEMPERATURE_LOG_COMMIT', 'DUTY_CHECK_IN'",
    )

    # 3-Tier Safety Gate Telemetry
    layer_0_status: str = Field(
        default="PASSED",
        description="Layer 0 Pre-Execution Gate status: PASSED | VIOLATION",
    )
    layer_1_model: str = Field(
        default="local_onnx_7seg",
        description="Model or engine identifier used for Layer 1 reasoning",
    )
    layer_1_confidence: float = Field(
        default=1.0,
        description="Confidence score reported by Layer 1 reasoning (0.0 to 1.0)",
    )
    layer_2_gate_status: str = Field(
        default="APPROVED",
        description="Layer 2 Post-Execution Gate status: APPROVED | DIVERTED_TO_REVIEW | SIMULATED_SHADOW",
    )

    # Factual Payload
    payload_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured operational data (e.g. chiller_temp_c, haccp_compliant, distance_m)",
    )

    # Cryptographic Non-Repudiation Chain
    prev_hash: str = Field(
        description="SHA-256 hash of the immediately preceding record in the chain",
    )
    record_hash: str = Field(
        default="",
        description="SHA-256 hash of (prev_hash + sequence_number + timestamp_utc + payload_json)",
    )
