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
PyInstaller Standalone Executable Build Script for Kiosk Retail Station (GEES v2.0).

Packages FastAPI application, static HTML/CSS assets, ONNX runtime, and SQLite schemas
into a standalone, zero-dependency Windows executable.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"


def build_kiosk_binary() -> int:
    """Execute PyInstaller build for the platform."""
    print("====================================================================")
    print("[BUILD] Kiosk Platform -- Standalone Executable Packaging Suite")
    print(f"[SOURCE] Source Root: {ROOT_DIR}")
    print("====================================================================")

    # Ensure output directory exists
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # Data folders to bundle
    data_bundles = [
        ("core_platform/app/admin_shell/templates", "core_platform/app/admin_shell/templates"),
        ("apps/temperature_marker/ui/templates", "apps/temperature_marker/ui/templates"),
        ("apps/temperature_marker/ui/static", "apps/temperature_marker/ui/static"),
        ("apps/temperature_marker/knowledge_graph", "apps/temperature_marker/knowledge_graph"),
        ("apps/mail_organizer/ui/templates", "apps/mail_organizer/ui/templates"),
    ]

    add_data_args = []
    for src, dst in data_bundles:
        src_path = ROOT_DIR / src
        if src_path.exists():
            add_data_args.extend(["--add-data", f"{src_path}{os.pathsep}{dst}"])

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=Release100_Kiosk",
        "--noconfirm",
        "--onedir",
        "--clean",
        "--collect-all=apps",
        "--collect-all=core_platform",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespans",
        "--hidden-import=uvicorn.lifespans.on",
        "--hidden-import=sqlite3",
        "--hidden-import=jinja2",
        "--hidden-import=pydantic",
        "--hidden-import=pydantic_settings",
        "--hidden-import=duckdb",
        "--hidden-import=psycopg2",
        "--hidden-import=pymysql",
        *add_data_args,
        str(ROOT_DIR / "manage.py"),
    ]

    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if result.returncode == 0:
        print("\n[SUCCESS] Build succeeded! Executable located in: dist/Release100_Kiosk/")
    else:
        print(f"\n[ERROR] Build failed with exit code {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(build_kiosk_binary())
