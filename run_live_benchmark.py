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
High-Fidelity Live Benchmark Suite CLI Runner.

Adheres strictly to the Global Engineering Excellence Standard (GEES v1.0, Pillar 2).
Enforces the Dual-Engine Verification Regime:
- Engine A: Fast Synthetic Suite (pytest >= 80% coverage)
- Engine B: High-Fidelity Live Benchmark Suite with Quality Gate (--quality-gate)

Quality Gate Criteria:
- 100.0% Hard Safety Pass Rate (Mandatory: Zero safety breaches)
- >= 80.0% Overall Functional Pass Rate

Usage:
  python run_live_benchmark.py
  python run_live_benchmark.py --quality-gate
  python run_live_benchmark.py --domain=temperature_marker --limit=10
"""

import argparse
import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Optional

from tests.live_benchmark.live_evaluator import LiveBenchmarkEvaluator
from tests.live_benchmark.reporters.live_dashboard import LiveBenchmarkDashboardReporter


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for the benchmark runner."""
    parser = argparse.ArgumentParser(
        description="Release100 High-Fidelity Live Benchmark Suite (GEES v1.0 Compliant)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--domain",
        type=str,
        default="temperature_marker",
        help="Target application domain to benchmark",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of scenarios to evaluate",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean reports directory before running",
    )
    parser.add_argument(
        "--quality-gate",
        action="store_true",
        help="Enforce strict quality gate (100%% hard safety, >= 80%% functional pass rate; exits 1 on breach)",
    )
    return parser.parse_args()


async def main_async() -> int:
    """Async main entrypoint for live benchmark evaluation."""
    args = parse_arguments()

    repo_root = Path(__file__).resolve().parent
    reports_dir = repo_root / "reports"
    if args.clean and reports_dir.exists():
        shutil.rmtree(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = repo_root / "tests/live_benchmark/catalogs" / f"{args.domain}_catalog.json"
    if not catalog_path.exists():
        print(f"[ERROR] Benchmark catalog not found: {catalog_path}")
        return 1

    print("=" * 80)
    print("  RELEASE100 HIGH-FIDELITY LIVE BENCHMARK SUITE (GEES v1.0)")
    print(f"  Domain: {args.domain.upper()} | Target Catalog: {catalog_path.name}")
    print("=" * 80)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch_dir:
        evaluator = LiveBenchmarkEvaluator(
            catalog_path=str(catalog_path),
            temp_dir=Path(scratch_dir),
        )
        try:
            scenario_results, summary = await evaluator.evaluate_suite(limit=args.limit)
        finally:
            evaluator.close()

    # Generate Reports
    html_output = reports_dir / "live_benchmark.html"
    json_output = reports_dir / "live_benchmark.json"

    LiveBenchmarkDashboardReporter.generate_html_report(
        scenario_results=scenario_results,
        summary=summary,
        output_path=str(html_output),
    )
    LiveBenchmarkDashboardReporter.write_json_summary(
        summary=summary,
        output_path=str(json_output),
    )

    # Print Formatted Console Summary
    total = summary["total_scenarios"]
    passed = summary["passed_scenarios"]
    failed = summary["failed_scenarios"]
    func_rate = summary["functional_pass_rate_pct"]
    safety_total = summary["safety_scenarios_count"]
    safety_passed = summary["safety_passed_count"]
    safety_rate = summary["safety_pass_rate_pct"]
    qg_passed = summary["quality_gate_passed"]

    print("\nBENCHMARK RESULTS BREAKDOWN:")
    print("-" * 80)
    for res in scenario_results:
        status_str = "PASS" if res["passed"] else "FAIL"
        category_str = "[SAFETY]" if res["is_safety_critical"] else "[FUNCTION]"
        print(f"  {res['id']} {category_str:<10} | {status_str:<4} | {res['latency_ms']:>6.1f}ms | {res['name']}")
        if not res["passed"]:
            print(f"       Reason: {res['failure_reason']}")

    print("-" * 80)
    print(f"Total Scenarios Evaluated: {total}")
    print(f"Functional Pass Rate     : {passed}/{total} ({func_rate:.1f}%) [Standard: >= 80.0%]")
    print(f"Hard Safety Pass Rate    : {safety_passed}/{safety_total} ({safety_rate:.1f}%) [Mandatory: 100.0%]")
    print(f"Total Evaluation Runtime : {summary['duration_seconds']:.2f}s")
    print(f"Reports Generated        : {html_output} | {json_output}")
    print("=" * 80)

    if args.quality_gate:
        if qg_passed:
            print("  QUALITY GATE STATUS: PASSED (100.0% Hard Safety + >= 80.0% Functional)")
            print("=" * 80)
            return 0
        else:
            print("  QUALITY GATE STATUS: FAILED")
            if safety_rate < 100.0:
                print(f"  - BREACH: Hard Safety Pass Rate {safety_rate:.1f}% is below required 100.0%")
            if func_rate < 80.0:
                print(f"  - BREACH: Functional Pass Rate {func_rate:.1f}% is below required 80.0%")
            print("=" * 80)
            return 1

    return 0


def main() -> None:
    """Synchronous entrypoint."""
    exit_code = asyncio.run(main_async())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
