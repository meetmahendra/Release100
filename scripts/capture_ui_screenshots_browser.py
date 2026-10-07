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
Capture browser screenshots of all UI pages using headless Chrome/Edge and snapshot_lib.
"""

import os
from pathlib import Path
import subprocess
import sys
import time

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.ui_snapshots.snapshot_lib import PAGES, make_client

CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
if not CHROME_PATH.exists():
    CHROME_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

ARTIFACT_DIR = Path(r"C:\Users\depali Gurav\.gemini\antigravity\brain\5dcee49a-51c8-4a1f-aa91-489aba7c34ba\ui_screenshots")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR = Path(r"C:\Users\depali Gurav\.gemini\antigravity\brain\5dcee49a-51c8-4a1f-aa91-489aba7c34ba\scratch\ui_html")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def capture_all() -> None:
    print(f"Browser: {CHROME_PATH}")
    print(f"Output: {ARTIFACT_DIR}")

    success_count = 0
    for idx, spec in enumerate(PAGES, 1):
        client = make_client(spec.persona)
        resp = client.get(spec.path, headers={"Accept": "text/html"})
        if resp.status_code != 200:
            print(f"[FAIL] {spec.name} ({spec.path}) -> HTTP {resp.status_code}")
            continue

        html_text = resp.text
        # Ensure static paths point to active server localhost:8000
        html_text = html_text.replace('href="/ui-static/', 'href="http://localhost:8000/ui-static/')
        html_text = html_text.replace('src="/ui-static/', 'src="http://localhost:8000/ui-static/')

        temp_file = TEMP_DIR / f"{spec.name}.html"
        temp_file.write_text(html_text, encoding="utf-8")

        out_png = ARTIFACT_DIR / f"{spec.name}.png"
        cmd = [
            str(CHROME_PATH),
            "--headless=new",
            "--disable-gpu",
            "--window-size=1280,850",
            "--virtual-time-budget=2000",
            f"--screenshot={out_png}",
            f"file:///{temp_file.as_posix()}",
        ]
        res = subprocess.run(cmd, capture_output=True)
        if out_png.exists():
            size_kb = out_png.stat().st_size // 1024
            print(f"[{idx:02d}/20] Wrote {out_png.name} ({size_kb} KB)")
            success_count += 1
        else:
            print(f"[ERROR] Screenshot failed for {spec.name}: {res.stderr.decode('utf-8', errors='ignore')}")

    print(f"[SUCCESS] {success_count}/20 screenshots captured successfully.")


if __name__ == "__main__":
    capture_all()
