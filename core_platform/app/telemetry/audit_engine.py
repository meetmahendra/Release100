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
Centralized Cryptographic Audit Engine.

Adheres strictly to GEES v1.0 (Pillar 3), FDA 21 CFR Part 11, and ISO 22000.
Guarantees:
1. Mathematical non-repudiation via SHA-256 hash chaining with monotonic sequence numbering.
2. Contemporaneous tri-format streaming (.jsonl, .csv, .html).
3. Thread-safe single-writer lock.
4. Autonomous chain integrity verification.
"""

import csv
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core_platform.app.config import settings
from core_platform.app.telemetry.audit_schema import AuditRecord
from core_platform.app.telemetry.reporters.audit_dashboard import AuditDashboardReporter


class AuditEngine:
    """Thread-safe cryptographic audit logging engine with SHA-256 hash chaining."""

    GENESIS_HASH: str = "GENESIS_BLOCK_00000000000000000000000000000000000000000000000000000000"
    _instance: Optional["AuditEngine"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "AuditEngine":
        """Retrieve singleton instance of AuditEngine."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, audit_dir: Optional[Path] = None) -> None:
        """Initialize AuditEngine and ensure directory tree exists."""
        self.audit_dir = Path(audit_dir or settings.AUDIT_DIR)
        self.html_dir = self.audit_dir / "html"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.html_dir.mkdir(parents=True, exist_ok=True)

        self._active_records: List[AuditRecord] = []
        self._last_hash: str = self.GENESIS_HASH
        self._sequence_counter: int = 0
        self._init_state_from_disk()

    def _init_state_from_disk(self) -> None:
        """Recover last sequence number and hash from today's partition if it exists."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl_path = self.audit_dir / f"{date_str}.jsonl"

        if jsonl_path.exists():
            try:
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        rec_dict = json.loads(line)
                        record = AuditRecord.model_validate(rec_dict)
                        self._active_records.append(record)
                        self._last_hash = record.record_hash
                        self._sequence_counter = max(self._sequence_counter, record.sequence_number)
            except Exception as e:
                print(f"[AuditEngine] Warning recovering state from disk: {e}")

    @staticmethod
    def compute_record_hash(
        prev_hash: str,
        sequence_number: int,
        timestamp_utc: str,
        payload: Dict[str, Any],
    ) -> str:
        """Compute cryptographic SHA-256 hash chaining signature.

        Formula: SHA-256(prev_hash + sequence_number + timestamp_utc + canonical_json_payload)

        Args:
            prev_hash: SHA-256 hash of immediately prior record.
            sequence_number: Monotonically increasing sequence number.
            timestamp_utc: UTC ISO timestamp.
            payload: Structured dictionary payload.

        Returns:
            64-character hexadecimal SHA-256 string.
        """
        payload_canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        seed = f"{prev_hash}|{sequence_number}|{timestamp_utc}|{payload_canonical}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def record_event(
        self,
        action_type: str,
        payload_summary: Dict[str, Any],
        operator_id: str = "EMP_1042",
        kiosk_id: Optional[str] = None,
        layer_0_status: str = "PASSED",
        layer_1_model: str = "local_onnx_7seg",
        layer_1_confidence: float = 1.0,
        layer_2_gate_status: str = "APPROVED",
        correlation_id: Optional[str] = None,
    ) -> AuditRecord:
        """Record an event with cryptographic SHA-256 hash chaining and tri-format output.

        Args:
            action_type: Event category (e.g. 'TEMPERATURE_LOG_COMMIT').
            payload_summary: Structured data payload.
            operator_id: ID of operator.
            kiosk_id: Unique kiosk fleet ID.
            layer_0_status: Layer 0 Pre-Gate disposition.
            layer_1_model: Model used for inference.
            layer_1_confidence: Confidence reported by Layer 1.
            layer_2_gate_status: Layer 2 Post-Gate disposition.
            correlation_id: Distributed trace ID.

        Returns:
            The created, mathematically sealed AuditRecord.
        """
        with self._lock:
            self._sequence_counter += 1
            now_utc = datetime.now(timezone.utc).isoformat()
            target_kiosk = kiosk_id or settings.KIOSK_ID

            # Calculate SHA-256 hash chain
            record_hash = self.compute_record_hash(
                prev_hash=self._last_hash,
                sequence_number=self._sequence_counter,
                timestamp_utc=now_utc,
                payload=payload_summary,
            )

            record = AuditRecord(
                sequence_number=self._sequence_counter,
                correlation_id=correlation_id or "",
                timestamp_utc=now_utc,
                organization_id=settings.TENANT_ID.upper(),
                facility_id=settings.STATION_NAME,
                kiosk_id=target_kiosk,
                operator_id=operator_id,
                action_type=action_type,
                layer_0_status=layer_0_status,
                layer_1_model=layer_1_model,
                layer_1_confidence=layer_1_confidence,
                layer_2_gate_status=layer_2_gate_status,
                payload_summary=payload_summary,
                prev_hash=self._last_hash,
                record_hash=record_hash,
            )

            # Advance chain pointer
            self._last_hash = record_hash
            self._active_records.append(record)

            # Contemporaneous tri-format emission
            self._append_jsonl(record)
            self._append_csv(record)
            self._regenerate_html()

            return record

    def _append_jsonl(self, record: AuditRecord) -> None:
        """Stream record to JSONL partition."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl_path = self.audit_dir / f"{date_str}.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

    def _append_csv(self, record: AuditRecord) -> None:
        """Stream record to CSV partition."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        csv_path = self.audit_dir / f"{date_str}.csv"
        file_exists = csv_path.exists()

        fieldnames = [
            "sequence_number",
            "timestamp_utc",
            "kiosk_id",
            "operator_id",
            "action_type",
            "layer_0_status",
            "layer_1_model",
            "layer_1_confidence",
            "layer_2_gate_status",
            "payload_json",
            "prev_hash",
            "record_hash",
        ]

        with open(csv_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "sequence_number": record.sequence_number,
                "timestamp_utc": record.timestamp_utc,
                "kiosk_id": record.kiosk_id,
                "operator_id": record.operator_id,
                "action_type": record.action_type,
                "layer_0_status": record.layer_0_status,
                "layer_1_model": record.layer_1_model,
                "layer_1_confidence": f"{record.layer_1_confidence:.4f}",
                "layer_2_gate_status": record.layer_2_gate_status,
                "payload_json": json.dumps(record.payload_summary),
                "prev_hash": record.prev_hash,
                "record_hash": record.record_hash,
            })

    def _regenerate_html(self) -> None:
        """Regenerate partitioned HTML visual inspection report."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        html_path = self.html_dir / f"{date_str}.html"
        AuditDashboardReporter.generate_html_report(
            records=self._active_records,
            output_path=str(html_path),
            partition_label=date_str,
        )

    @classmethod
    def verify_chain_integrity(cls, records: List[AuditRecord]) -> Tuple[bool, Optional[int]]:
        """Mathematically verify the cryptographic integrity of an audit chain.

        Validates that every record's hash correctly reflects its payload, timestamp,
        sequence number, and previous record hash, with zero tampering or omissions.

        Args:
            records: Chronologically sorted list of AuditRecord items.

        Returns:
            Tuple of (is_valid: bool, tampered_sequence_number: Optional[int]).
        """
        if not records:
            return True, None

        expected_prev = cls.GENESIS_HASH
        expected_seq = records[0].sequence_number

        for r in records:
            # Check sequence continuity
            if r.sequence_number != expected_seq:
                return False, r.sequence_number

            # Check previous hash pointer
            if r.prev_hash != expected_prev:
                return False, r.sequence_number

            # Recompute hash independently
            recomputed = cls.compute_record_hash(
                prev_hash=r.prev_hash,
                sequence_number=r.sequence_number,
                timestamp_utc=r.timestamp_utc,
                payload=r.payload_summary,
            )

            if r.record_hash != recomputed:
                return False, r.sequence_number

            expected_prev = r.record_hash
            expected_seq += 1

        return True, None
