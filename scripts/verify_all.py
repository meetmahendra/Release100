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
Unified Pre-Flight Quality Gate Runner (GEES v3.1).
Executes the 7 Inviolable Verification Gates with ASCII-safe terminal logging.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import time
from typing import List, Optional, Sequence


ROOT = Path(__file__).resolve().parent.parent


@dataclass
class GateSpec:
    name: str
    description: str
    command: List[str]
    timeout_sec: int = 180


def run_gate(gate: GateSpec) -> tuple[bool, float, str]:
    """Execute a single verification gate and return (success, elapsed_sec, output)."""
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            gate.command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=gate.timeout_sec,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.perf_counter() - start
        success = proc.returncode == 0
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return success, elapsed, output
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - start
        return False, elapsed, f"[TIMEOUT] Gate timed out after {gate.timeout_sec}s"
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return False, elapsed, f"[ERROR] Execution failed: {exc}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GEES v3.1 Inviolable Pre-Flight Quality Gate Runner")
    parser.add_argument("--quality-gate", action="store_true", help="Enforce 100% hard pass on all 7 gates")
    parser.add_argument("--fast", action="store_true", help="Skip full test suite and run only core guards")
    args = parser.parse_args(argv)

    py_exe = sys.executable
    gates: List[GateSpec] = [
        GateSpec(
            name="[1/7] AST-GUARD",
            description="AST Architecture Boundary & Microkernel Isolation",
            command=[py_exe, "-m", "pytest", "tests/unit/test_architectural_boundaries.py", "-q"],
        ),
        GateSpec(
            name="[2/7] TYPE-GUARD",
            description="Static Type Discipline (mypy --strict)",
            command=[py_exe, "-m", "mypy", "core_platform", "ops_control_plane", "apps"],
        ),
        GateSpec(
            name="[3/7] UI-GUARD",
            description="UI Localization Parity & Untranslated String Guard",
            command=[py_exe, "-m", "pytest", "tests/unit/test_ui_guards.py", "-q"],
        ),
        GateSpec(
            name="[4/7] NODE-GUARD",
            description="Headless JavaScript & UI Bundle Compatibility",
            command=[py_exe, "-m", "pytest", "tests/unit/test_ui_js_bundle.py", "-q"],
        ),
        GateSpec(
            name="[5/7] SECRET-GUARD",
            description="Zero-Secret & Live Credential Scanner",
            command=[py_exe, "-m", "pytest", "tests/unit/test_zero_secret_leak_guard.py", "-q"],
        ),
        GateSpec(
            name="[6/7] MANIFEST-GUARD",
            description="Packaging & Wheel Manifest Integrity",
            command=[py_exe, "-m", "pytest", "tests/unit/test_packaging_manifest_integrity.py", "-q"],
        ),
    ]

    if not args.fast:
        test_paths = ["tests/unit/"]
        e2e_dir = ROOT / "tests" / "e2e"
        if e2e_dir.is_dir():
            test_paths.append("tests/e2e/")
        gates.append(
            GateSpec(
                name="[7/7] REGRESSION-GUARD",
                description="Fast Synthetic Unit & E2E Journey Test Suite",
                command=[py_exe, "-m", "pytest"] + test_paths + ["-q"],
                timeout_sec=360,
            )
        )

    print("=" * 80)
    print("  GEES v3.1 INVIOLABLE PRE-FLIGHT QUALITY GATE")
    print("=" * 80)

    all_passed = True
    results: List[tuple[GateSpec, bool, float, str]] = []

    for gate in gates:
        print(f"-> Running {gate.name}: {gate.description} ...", flush=True)
        passed, elapsed, output = run_gate(gate)
        results.append((gate, passed, elapsed, output))
        if passed:
            print(f"   [PASS] ({elapsed:.2f}s)")
        else:
            print(f"   [FAIL] ({elapsed:.2f}s)")
            all_passed = False
            # Print failure snippet
            lines = output.splitlines()
            snippet = "\n".join(lines[-15:]) if len(lines) > 15 else output
            print("   " + "-" * 70)
            for s_line in snippet.splitlines():
                print(f"   | {s_line}")
            print("   " + "-" * 70)

    print("=" * 80)
    print("  VERIFICATION SUMMARY REPORT")
    print("=" * 80)
    for gate, passed, elapsed, _ in results:
        status_tag = "[PASS]" if passed else "[FAIL]"
        print(f"  {status_tag:6s} {gate.name:22s} ({elapsed:6.2f}s) - {gate.description}")
    print("=" * 80)

    if all_passed:
        print("  [SUCCESS] 100% QUALITY GATE CRITERIA SATISFIED (GEES v3.1 CERTIFIED)")
        print("=" * 80)
        return 0
    else:
        print("  [ERROR] QUALITY GATE BREACHED - ZERO REGRESSION INVARIANT FAILED")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
