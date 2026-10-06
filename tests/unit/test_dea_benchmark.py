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


"""Runs the entitlement live-benchmark catalog inside pytest (Plan 10, T23)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.live_benchmark.live_evaluator import LiveBenchmarkEvaluator

CATALOG = Path(__file__).resolve().parents[1] / "live_benchmark" / "catalogs" / "entitlements_catalog.json"


def test_entitlement_catalog_passes_quality_gate(tmp_path: Path) -> None:
    """Every entitlement scenario passes, so safety is 100 percent."""
    evaluator = LiveBenchmarkEvaluator(str(CATALOG), tmp_path)
    try:
        results, summary = asyncio.run(evaluator.evaluate_suite())
    finally:
        evaluator.close()
    failed = [r["id"] + ": " + r["failure_reason"] for r in results if not r["passed"]]
    assert failed == []
    assert len(results) >= 12
