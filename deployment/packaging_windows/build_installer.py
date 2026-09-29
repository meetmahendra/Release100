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
Automated Multi-Stage Windows Executable & Installer Build Script.

Supports:
- Cartridge Combinations:
    --edition=kiosk  (Kiosk & Retail Edition: temperature_marker only)
    --edition=all    (Full Enterprise Suite: temperature_marker + mail_organizer)
- Stage 1: PyInstaller Multi-Binary Directory Bundler
- Stage 2: Authenticode Code Signing & Root Certificate Generation
- Stage 3: Inno Setup (.iss) Single Executable Installer Compiler
- Stage 4: Self-Contained Portable Deployment ZIP Packaging for Windows VM Testing
- Supports --dry-run for fast CI validation.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple
import zipfile


class WindowsInstallerBuilder:
    """Build orchestrator for Windows distribution packages."""

    def __init__(self, root_dir: Optional[Path] = None, edition: str = "all") -> None:
        """Initialize builder with project root directory and edition."""
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.packaging_dir = self.root_dir / "deployment" / "packaging_windows"
        self.dist_dir = self.root_dir / "dist"
        self.edition = edition.lower().strip()

        if self.edition == "kiosk":
            self.target_name = "Release100_Kiosk"
            self.spec_file = self.packaging_dir / "Kiosk_Retail_Edition.spec"
            self.iss_file = self.packaging_dir / "installer_kiosk.iss"
            self.zip_name = "CaneBot_Kiosk_Retail_v1.3.0_Portable.zip"
            self.edition_title = "Release100 Kiosk & Retail Edition"
        else:
            self.target_name = "Release100"
            self.spec_file = self.packaging_dir / "Release100.spec"
            self.iss_file = self.packaging_dir / "installer.iss"
            self.zip_name = "Release100_Full_Suite_v1.3.0_Portable.zip"
            self.edition_title = "Release100 Industrial Automation Platform (Full Suite)"

        self.cert_script = self.packaging_dir / "generate_test_cert.ps1"
        self.vm_cert_installer = self.packaging_dir / "install_cert_on_vm.ps1"

    def find_inno_setup_compiler(self) -> Optional[Path]:
        """Locate ISCC.exe compiler on Windows system."""
        path_iscc = shutil.which("ISCC.exe")
        if path_iscc:
            return Path(path_iscc)

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
        if not self.cert_script.exists():
            missing.append(f"Certificate script: {self.cert_script}")

        return len(missing) == 0, missing

    def sign_binaries(self) -> bool:
        """Sign generated binaries using generate_test_cert.ps1."""
        print(f"\n[STAGE 2] Executing Code Signing Pipeline via {self.cert_script.name}...")
        try:
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.cert_script),
                "-DistDir",
                str(self.dist_dir),
            ]
            res = subprocess.run(cmd, cwd=str(self.packaging_dir), check=True)
            return res.returncode == 0
        except Exception as e:
            print(f"⚠️ Code signing execution encountered an issue: {e}")
            return False

    def populate_kiosk_assets(self, target_folder: Path) -> None:
        """Deploy default .env, launcher batch scripts, cert installer, and VM testing guide."""
        print(f"\n[STAGE 3] Deploying Kiosk operational scripts and certificates into: {target_folder.name}...")

        # 1. Kiosk default .env
        kiosk_env = target_folder / ".env"
        kiosk_env_content = (
            "# Release100 Kiosk & Retail Edition Configuration\n"
            "PORT=8002\n"
            "ORCHESTRATOR_PORT=8002\n"
            'ENABLED_APPLICATIONS=["temperature_marker"]\n'
            "EXECUTION_MODE=shadow\n"
            "DRY_RUN=false\n"
            "STATION_NAME=Kiosk #04 (Phoenix Mall)\n"
            "KIOSK_ID=CANEBOT-PUNE-04\n"
            "ORGANIZATION_NAME=Canectar Foods Pvt Ltd\n"
            "# Outbound Cloudflare Worker / Enterprise Relay URL (leave blank for local network mode)\n"
            "RELAY_WS_URL=\n"
            "RELAY_ROUTER_ID=CANEBOT-PUNE-04\n"
        )
        kiosk_env.write_text(kiosk_env_content, encoding="utf-8")

        # 2. Batch launchers
        (target_folder / "start_kiosk_tray.bat").write_text(
            "@echo off\r\n"
            "title Release100 Kiosk - System Tray Controller\r\n"
            "echo ======================================================================\r\n"
            "echo   Starting Release100 Kiosk & Retail Edition (System Tray Mode)\r\n"
            "echo ======================================================================\r\n"
            f'pushd "%~dp0"\r\n'
            f'"{self.target_name}.exe" run --mode tray --host 127.0.0.1 --port 8002\r\n'
            "popd\r\n"
            "pause\r\n",
            encoding="utf-8",
        )

        (target_folder / "start_kiosk_headless.bat").write_text(
            "@echo off\r\n"
            "title Release100 Kiosk - Headless Server\r\n"
            "echo ======================================================================\r\n"
            "echo   Starting Release100 Kiosk & Retail Edition (Headless Daemon)\r\n"
            "echo ======================================================================\r\n"
            f'pushd "%~dp0"\r\n'
            f'"{self.target_name}.exe" run --mode headless --host 127.0.0.1 --port 8002\r\n'
            "popd\r\n"
            "pause\r\n",
            encoding="utf-8",
        )

        (target_folder / "health_check.bat").write_text(
            "@echo off\r\n"
            "title Release100 Kiosk - Health Diagnostic\r\n"
            f'pushd "%~dp0"\r\n'
            f'"{self.target_name}.exe" health\r\n'
            "popd\r\n"
            "pause\r\n",
            encoding="utf-8",
        )

        (target_folder / "seed_test_operators.bat").write_text(
            "@echo off\r\n"
            "title Release100 Kiosk - Seed Operators\r\n"
            f'pushd "%~dp0"\r\n'
            f'"{self.target_name}.exe" seed\r\n'
            "popd\r\n"
            "pause\r\n",
            encoding="utf-8",
        )

        # 3. Copy certificate & installer scripts into folder
        cer_src = self.dist_dir / "Release100_TestCert.cer"
        if cer_src.exists():
            shutil.copy2(cer_src, target_folder / "Release100_TestCert.cer")

        if self.vm_cert_installer.exists():
            shutil.copy2(self.vm_cert_installer, target_folder / "install_cert_on_vm.ps1")

        bat_cert_installer = self.packaging_dir / "install_cert.bat"
        if bat_cert_installer.exists():
            shutil.copy2(bat_cert_installer, target_folder / "install_cert.bat")

        # 4. Write VM Testing Guide
        guide_path = target_folder / "VM_TESTING_GUIDE.md"
        guide_content = f"""# {self.edition_title} — Windows VM Deployment & Testing Guide

This standalone distribution is pre-packaged for zero-dependency execution on Windows 10/11 or Windows Server VMs.

---

## Step 1: Trust the Code-Signing Certificate (Eliminate SmartScreen Warnings)
Before launching, install the test code-signing certificate into the VM's Trusted Root store:
1. Open PowerShell as **Administrator** in this directory.
2. Run:
   ```powershell
   .\\install_cert_on_vm.ps1
   ```
   *(Or double-click `install_cert_on_vm.ps1` and choose "Run with PowerShell".)*
3. Once completed, right-click `{self.target_name}.exe` -> **Properties** -> **Digital Signatures** to verify the signature is valid.

---

## Step 2: Run Health Preflight Diagnostics
Double-click `health_check.bat`.
This verifies:
- System NTP clock sanity.
- Port 8002 availability.
- Local SQLite database & AES-256 encrypted credential vaults.
- Cognitive Skills: Display OCR, Biometric Face Recognizer, Geofence Validator, HACCP Engine.

---

## Step 3: Launch Platform
Choose either mode:
- **System Tray Mode (Recommended)**: Double-click `start_kiosk_tray.bat`.
  - Look for the green CaneBot icon in the Windows Notification Area (bottom-right taskbar).
  - Right-click the icon to open the Fleet Monitoring Dashboard, Trigger Audit Export, or inspect settings.
- **Headless Service Mode**: Double-click `start_kiosk_headless.bat`.
  - Runs in background console on port 8002.

---

## Step 4: Access Browser Dashboards
Open Google Chrome or Microsoft Edge on the VM and navigate to:
- **Fleet & Kiosk Monitoring**: [http://127.0.0.1:8002/admin/apps/temperature-marker/fleet](http://127.0.0.1:8002/admin/apps/temperature-marker/fleet)
- **Live Health Heartbeat (JSON)**: [http://127.0.0.1:8002/health](http://127.0.0.1:8002/health)
- **Platform Settings & Diagnostic Verifier**: [http://127.0.0.1:8002/settings](http://127.0.0.1:8002/settings)

---

## Step 5: Seed Sample Test Operators
To test attendance and shift clock-in workflows immediately:
- Double-click `seed_test_operators.bat`.
- Reload the Fleet Dashboard to see active operators assigned to `{kiosk_env_content.split('KIOSK_ID=')[1].splitlines()[0]}`.
"""
        guide_path.write_text(guide_content, encoding="utf-8")
        print("  [PASS] Operational scripts, .env, and VM testing guide written.")

    def create_portable_zip(self, source_folder: Path) -> Path:
        """Create a self-contained portable ZIP package ready for VM file transfer."""
        zip_path = self.dist_dir / self.zip_name
        print(f"\n[STAGE 4] Creating Portable VM Deployment Package: {zip_path.name}...")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root, _, files in os.walk(source_folder):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(self.dist_dir)
                    zip_file.write(file_path, arcname)

        size_mb = round(zip_path.stat().st_size / (1024 * 1024), 2)
        print(f"  [PASS] Portable ZIP ready for VM extraction: {zip_path.name} ({size_mb} MB)")
        return zip_path

    def build(self, dry_run: bool = False) -> int:
        """Execute the complete build, sign, and packaging process."""
        print("=" * 75)
        print(f"  RELEASE100 WINDOWS PACKAGING SUITE")
        print(f"  Edition : {self.edition_title}")
        print(f"  Dry-Run : {dry_run}")
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
            print("  [INFO] Inno Setup compiler (ISCC.exe) not in default paths (Portable ZIP will be created)")

        if dry_run:
            print("\n[SUCCESS] DRY-RUN COMPLETED: All packaging assets are validated and ready.")
            print("=" * 75)
            return 0

        # Stage 1: Run PyInstaller
        print(f"\n[STAGE 1] Compiling binaries via PyInstaller ({self.spec_file.name})...")
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

        target_folder = self.dist_dir / self.target_name
        print(f"[PASS] PyInstaller compilation completed. Target: {target_folder}")

        # Stage 2: Code Signing
        self.sign_binaries()

        # Stage 3: Populate Assets & Scripts
        self.populate_kiosk_assets(target_folder)

        # Re-sign with newly populated scripts/certs if needed
        self.sign_binaries()

        # Stage 4: Create Portable ZIP package
        self.create_portable_zip(target_folder)

        # Stage 5: Compile Inno Setup if ISCC available
        if not iscc:
            print("\n[STAGE 5] ISCC.exe not found on host. Skipping installer compilation.")
            print(f"Portable distribution ready in: {self.dist_dir / self.zip_name}")
            return 0

        print(f"\n[STAGE 5] Compiling Windows installer with {iscc}...")
        try:
            res = subprocess.run([str(iscc), str(self.iss_file)], cwd=str(self.packaging_dir), check=True)
            if res.returncode != 0:
                print(f"❌ Inno Setup compiler failed with code {res.returncode}")
                return res.returncode
            # Sign the generated installer executable
            self.sign_binaries()
        except Exception as e:
            print(f"❌ Inno Setup execution failed: {e}")
            return 1

        print(f"\n[SUCCESS] {self.edition_title} Windows Installer generated successfully!")
        print(f"Output: {self.dist_dir / 'installer'}")
        return 0


def main() -> None:
    """CLI Entrypoint for build_installer.py."""
    parser = argparse.ArgumentParser(description="Release100 Windows Installer Builder")
    parser.add_argument("--edition", choices=["kiosk", "all"], default="kiosk", help="Platform edition to package")
    parser.add_argument("--dry-run", action="store_true", help="Validate specs without compiling")
    args = parser.parse_args()

    builder = WindowsInstallerBuilder(edition=args.edition)
    sys.exit(builder.build(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
