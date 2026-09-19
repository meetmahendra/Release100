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
Synthetic Unit Tests for Cryptographic Audit Engine (GEES v1.0 Pillar 3).

Tests:
1. Monotonic sequence numbering.
2. SHA-256 hash chaining non-repudiation.
3. Tri-format contemporaneous logging (.jsonl, .csv, .html).
4. Autonomous mathematical tamper detection.
"""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from core_platform.app.telemetry.audit_engine import AuditEngine
from core_platform.app.telemetry.audit_schema import AuditRecord


class TestAuditEngine:
    """Test suite for AuditEngine and SHA-256 hash chaining."""

    @pytest.fixture
    def audit_engine(self, tmp_path: Path) -> AuditEngine:
        """Provide an isolated AuditEngine instance rooted in a temporary folder."""
        return AuditEngine(audit_dir=tmp_path / "audit_logs")

    def test_record_event_monotonic_sequence(self, audit_engine: AuditEngine) -> None:
        """Audit records must strictly increment sequence numbers starting at 1."""
        rec1 = audit_engine.record_event(
            action_type="TEST_ACTION_1",
            payload_summary={"val": 100},
        )
        rec2 = audit_engine.record_event(
            action_type="TEST_ACTION_2",
            payload_summary={"val": 200},
        )
        assert rec1.sequence_number == 1
        assert rec2.sequence_number == 2
        assert rec2.prev_hash == rec1.record_hash

    def test_tri_format_contemporaneous_emission(self, audit_engine: AuditEngine) -> None:
        """Recording an event must contemporaneously write JSONL, CSV, and HTML."""
        audit_engine.record_event(
            action_type="CHILLER_TEMP_LOG",
            payload_summary={"chiller_temp_c": 3.2, "haccp_compliant": True},
        )

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl_file = audit_engine.audit_dir / f"{date_str}.jsonl"
        csv_file = audit_engine.audit_dir / f"{date_str}.csv"
        html_file = audit_engine.html_dir / f"{date_str}.html"

        assert jsonl_file.exists(), "JSONL log file must exist"
        assert csv_file.exists(), "CSV log file must exist"
        assert html_file.exists(), "HTML visual inspection report must exist"

        # Verify JSONL contains valid json line
        with open(jsonl_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 1
            assert "CHILLER_TEMP_LOG" in lines[0]

        # Verify CSV has header and row
        with open(csv_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) >= 2
            assert "CHILLER_TEMP_LOG" in lines[1]

        # Verify HTML has content
        with open(html_file, "r", encoding="utf-8") as f:
            html_text = f.read()
            assert "Compliance Audit Report" in html_text
            assert "CHILLER_TEMP_LOG" in html_text

    def test_mathematical_chain_integrity_validation(self, audit_engine: AuditEngine) -> None:
        """Valid chained records must return True on integrity verification."""
        records = []
        for i in range(5):
            rec = audit_engine.record_event(
                action_type=f"STEP_{i}",
                payload_summary={"step": i, "sensor_read": 3.0 + (i * 0.1)},
            )
            records.append(rec)

        is_valid, tampered_seq = AuditEngine.verify_chain_integrity(records)
        assert is_valid is True
        assert tampered_seq is None

    def test_detect_tampered_payload(self, audit_engine: AuditEngine) -> None:
        """Tampering with a historical payload must invalidate subsequent chain verification."""
        records = []
        for i in range(4):
            rec = audit_engine.record_event(
                action_type=f"TX_{i}",
                payload_summary={"amount": 10 * i},
            )
            records.append(rec)

        # Retrospectively tamper with record #2's payload
        tampered_record = records[1].model_copy(deep=True)
        tampered_record.payload_summary["amount"] = 999999  # Unauthorized modification
        records[1] = tampered_record

        is_valid, tampered_seq = AuditEngine.verify_chain_integrity(records)
        assert is_valid is False
        assert tampered_seq == 2, "Must detect tampering at sequence #2"

    def test_detect_tampered_sequence_skip(self, audit_engine: AuditEngine) -> None:
        """Deleting or omitting a record from the chain must be caught immediately."""
        records = []
        for i in range(4):
            rec = audit_engine.record_event(
                action_type=f"TX_{i}",
                payload_summary={"idx": i},
            )
            records.append(rec)

        # Omit record #2 (sequence 2 deleted)
        corrupted_chain = [records[0], records[2], records[3]]

        is_valid, tampered_seq = AuditEngine.verify_chain_integrity(corrupted_chain)
        assert is_valid is False
        assert tampered_seq == 3, "Must fail at record #3 because sequence skipped from 1 to 3"
