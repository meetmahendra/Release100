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

"""Capture or refresh the UI render-snapshot baselines (Plan 11, T02).

Usage:
    python scripts/capture_ui_snapshots.py            # compare, exit 1 on drift
    python scripts/capture_ui_snapshots.py --update   # rewrite baselines
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.ui_snapshots import snapshot_lib  # noqa: E402


def main(argv: list[str]) -> int:
    """Run capture; with ``--update`` write baselines, otherwise report drift."""
    snapshots = snapshot_lib.capture_all()
    if "--update" in argv:
        for path in snapshot_lib.write_baselines(snapshots):
            sys.stdout.write(f"[SNAPSHOT] wrote {path.name}\n")
        sys.stdout.write(f"[SUCCESS] {len(snapshots)} baselines written\n")
        return 0
    drift = []
    for name, text in sorted(snapshots.items()):
        target = snapshot_lib.baseline_path(name)
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            drift.append(name)
    for name in drift:
        sys.stdout.write(f"[DRIFT] {name}\n")
    sys.stdout.write(f"[{'ERROR' if drift else 'SUCCESS'}] {len(drift)} of {len(snapshots)} pages drifted\n")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
