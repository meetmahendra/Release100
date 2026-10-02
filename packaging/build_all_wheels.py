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
Local Wheel Build Automation Script for Release100 & Cartridges (GEES v2.0).

Builds distributable .whl and .tar.gz packages for:
  1. Core Platform (release100-core)
  2. Temperature Marker Cartridge (release100-cartridge-temperature-marker)
  3. Mail Organizer Cartridge (release100-cartridge-mail-organizer)
"""

from pathlib import Path
import shutil
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "dist" / "wheels"


def build_package(src_dir: Path, out_dir: Path) -> int:
    """Build a python package wheel and sdist into target output directory."""
    print(f"\n[BUILD] Compiling package in: {src_dir}")
    python_bin = sys.executable
    venv_py = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        python_bin = str(venv_py)
    cmd = [
        python_bin,
        "-m",
        "build",
        "--sdist",
        "--wheel",
        "--outdir",
        str(out_dir),
        str(src_dir),
    ]
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    return result.returncode


def main() -> int:
    """Build all platform packages."""
    print("=" * 70)
    print("  RELEASE100 WHEEL & DISTRIBUTION BUILD SUITE")
    print("=" * 70)

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    packages = [
        ("Core Platform", ROOT_DIR),
        ("Temperature Marker Cartridge", ROOT_DIR / "apps" / "temperature_marker"),
        ("Mail Organizer Cartridge", ROOT_DIR / "apps" / "mail_organizer"),
    ]

    for name, path in packages:
        if not (path / "pyproject.toml").exists():
            print(f"[ERROR] Missing pyproject.toml in {path}")
            return 1
        rc = build_package(path, OUTPUT_DIR)
        if rc != 0:
            print(f"[ERROR] Failed to build {name}")
            return rc

    print("\n" + "=" * 70)
    print("[SUCCESS] All packages built successfully! Distributable files:")
    print("=" * 70)
    for f in sorted(OUTPUT_DIR.glob("*")):
        print(f"  - {f.name} ({f.stat().st_size:,} bytes)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
