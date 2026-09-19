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
Automated 2-Stage Windows Executable & Installer Build Script.

Stage 1: PyInstaller Multi-Binary Directory Bundler
Stage 2: Inno Setup (.iss) Single Executable Installer Compiler

Supports --dry-run for fast CI validation.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple


class WindowsInstallerBuilder:
    """Build orchestrator for Windows distribution packages."""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        """Initialize builder with project root directory."""
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.packaging_dir = self.root_dir / "deployment" / "packaging_windows"
        self.spec_file = self.packaging_dir / "Release100.spec"
        self.iss_file = self.packaging_dir / "installer.iss"
        self.dist_dir = self.root_dir / "dist"

    def find_inno_setup_compiler(self) -> Optional[Path]:
        """Locate ISCC.exe compiler on Windows system."""
        # Check PATH
        path_iscc = shutil.which("ISCC.exe")
        if path_iscc:
            return Path(path_iscc)

        # Standard installation locations
        program_files = [
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("LocalAppData", ""),
        ]
        for pf in program_files:
            if not pf:
                continue
            candidate = Path(pf) / "Inno Setup 6" / "ISCC.exe"
            if candidate.exists():
                return candidate
            candidate_v5 = Path(pf) / "Inno Setup 5" / "ISCC.exe"
            if candidate_v5.exists():
                return candidate_v5

        return None

    def validate_prerequisites(self) -> Tuple[bool, List[str]]:
        """Verify presence of all mandatory source code files and specifications."""
        missing = []
        if not self.spec_file.exists():
            missing.append(f"PyInstaller Spec: {self.spec_file}")
        if not self.iss_file.exists():
            missing.append(f"Inno Setup Script: {self.iss_file}")
        if not (self.root_dir / "manage.py").exists():
            missing.append("manage.py entrypoint")
        if not (self.root_dir / "core_platform" / "main.py").exists():
            missing.append("core_platform/main.py")

        return len(missing) == 0, missing

    def build(self, dry_run: bool = False) -> int:
        """Execute the 2-stage build process or dry-run validation."""
        print("=" * 75)
        print(f"  RELEASE100 WINDOWS PACKAGING SUITE (DryRun={dry_run})")
        print("=" * 75)

        valid, missing = self.validate_prerequisites()
        if not valid:
            print("❌ Build validation failed. Missing prerequisites:")
            for m in missing:
                print(f"   - {m}")
            return 1

        print("  [PASS] Build specifications & entrypoints verified.")
        print(f"  [PASS] PyInstaller spec: {self.spec_file.name}")
        print(f"  [PASS] Inno Setup recipe: {self.iss_file.name}")

        iscc = self.find_inno_setup_compiler()
        if iscc:
            print(f"  [PASS] Inno Setup compiler detected: {iscc}")
        else:
            print("  [INFO] Inno Setup compiler (ISCC.exe) not in default paths (Stage 2 will require manual run or ISCC installation)")

        if dry_run:
            print("\n[SUCCESS] DRY-RUN COMPLETED: All packaging assets are validated and ready.")
            print("=" * 75)
            return 0

        # Stage 1: Run PyInstaller
        print("\n[STAGE 1] Compiling binaries via PyInstaller...")
        pyinstaller_cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(self.spec_file),
        ]
        try:
            res = subprocess.run(pyinstaller_cmd, cwd=str(self.root_dir), check=True)
            if res.returncode != 0:
                print(f"❌ PyInstaller build failed with return code {res.returncode}")
                return res.returncode
        except Exception as e:
            print(f"❌ PyInstaller execution failed: {e}")
            return 1

        print("[PASS] PyInstaller compilation completed.")

        # Stage 2: Compile Inno Setup
        if not iscc:
            print("\n[STAGE 2] ISCC.exe not found on host. Skipping installer compilation.")
            print(f"Raw binary distribution ready in: {self.dist_dir / 'Release100'}")
            return 0

        print(f"\n[STAGE 2] Compiling Windows installer with {iscc}...")
        try:
            res = subprocess.run([str(iscc), str(self.iss_file)], cwd=str(self.packaging_dir), check=True)
            if res.returncode != 0:
                print(f"❌ Inno Setup compiler failed with code {res.returncode}")
                return res.returncode
        except Exception as e:
            print(f"❌ Inno Setup execution failed: {e}")
            return 1

        print("\n[SUCCESS] Release100 Windows Single Executable Installer generated successfully!")
        print(f"Output: {self.dist_dir / 'installer'}")
        return 0


def main() -> None:
    """CLI Entrypoint for build_installer.py."""
    parser = argparse.ArgumentParser(description="Release100 Windows Installer Builder")
    parser.add_argument("--dry-run", action="store_true", help="Validate specs without compiling")
    args = parser.parse_args()

    builder = WindowsInstallerBuilder()
    sys.exit(builder.build(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
