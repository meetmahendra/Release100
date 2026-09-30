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
Packaging Distribution ZIP Suite.

Adheres to Plan 05 v1.2 (Deployment & Packaging Hub).
Packages portable retail installation archive with batch launcher,
clean .env template, and offline models.
"""

import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"


def package_retail_zip(version: str = "v1.3.0") -> Path:
    """Create portable distribution ZIP archive for physical edge kiosk deployment."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    zip_name = f"Kiosk_Retail_{version}_Portable.zip"
    zip_path = DIST_DIR / zip_name

    include_patterns = [
        "core_platform/**/*.py",
        "apps/**/*.py",
        "apps/**/*.html",
        "apps/**/*.css",
        "apps/**/*.js",
        "apps/**/*.json",
        "core_platform/**/*.html",
        "main.py",
        "requirements.txt",
        ".env.example",
        "README.md",
    ]

    print(f"[PACKAGING] Packaging portable release archive: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for pat in include_patterns:
            for file_path in ROOT_DIR.glob(pat):
                if file_path.is_file() and not any(p in file_path.parts for p in [".venv", "__pycache__", ".git", "dist", "build", "logs"]):
                    arcname = file_path.relative_to(ROOT_DIR)
                    zf.write(file_path, arcname)

    print(f"[SUCCESS] Portable ZIP created successfully! ({zip_path.stat().st_size / 1024:.1f} KB)")
    return zip_path


if __name__ == "__main__":
    package_retail_zip()

