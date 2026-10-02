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
PEP 503 Compliant Static Simple Index Generator for Release100.

Generates a static HTML repository index for wheels in dist/wheels/ so that:
  set UV_EXTRA_INDEX_URL=https://.../simple/
  uv pip install release100-core
  uv pip install release100-cartridge-temperature-marker
works seamlessly across all machines.
"""

from pathlib import Path
import re
import shutil

ROOT_DIR = Path(__file__).resolve().parent.parent
WHEELS_DIR = ROOT_DIR / "dist" / "wheels"
SIMPLE_DIR = ROOT_DIR / "dist" / "simple"


def normalize_name(name: str) -> str:
    """PEP 503 normalization: lowercase and replace [._-] with -."""
    return re.sub(r"[-_.]+", "-", name).lower()


def generate_index(base_url: str = "") -> None:
    """Generate PEP 503 static index tree."""
    if SIMPLE_DIR.exists():
        shutil.rmtree(SIMPLE_DIR)
    SIMPLE_DIR.mkdir(parents=True, exist_ok=True)

    packages: dict[str, list[Path]] = {}

    for wheel_file in WHEELS_DIR.glob("*.whl"):
        # Wheel filename format: {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
        parts = wheel_file.name.split("-")
        raw_pkg_name = parts[0]
        norm_pkg = normalize_name(raw_pkg_name)
        packages.setdefault(norm_pkg, []).append(wheel_file)

    for sdist_file in WHEELS_DIR.glob("*.tar.gz"):
        raw_pkg_name = sdist_file.name.split("-")[0]
        norm_pkg = normalize_name(raw_pkg_name)
        packages.setdefault(norm_pkg, []).append(sdist_file)

    # 1. Root index.html
    root_lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head><title>Release100 Private Package Index</title></head>",
        "<body>",
        "<h1>Release100 Private Package Index</h1>",
    ]
    for pkg in sorted(packages.keys()):
        root_lines.append(f'<a href="{pkg}/">{pkg}</a><br/>')
    root_lines.extend(["</body>", "</html>"])

    (SIMPLE_DIR / "index.html").write_text("\n".join(root_lines), encoding="utf-8")

    # 2. Per-package index.html
    for pkg, files in packages.items():
        pkg_dir = SIMPLE_DIR / pkg
        pkg_dir.mkdir(parents=True, exist_ok=True)

        pkg_lines = [
            "<!DOCTYPE html>",
            "<html>",
            f"<head><title>Links for {pkg}</title></head>",
            "<body>",
            f"<h1>Links for {pkg}</h1>",
        ]
        for f in sorted(files, key=lambda x: x.name):
            # Copy the file into the package dir for direct hosting
            dest_file = pkg_dir / f.name
            shutil.copy2(f, dest_file)
            pkg_lines.append(f'<a href="{f.name}">{f.name}</a><br/>')

        pkg_lines.extend(["</body>", "</html>"])
        (pkg_dir / "index.html").write_text("\n".join(pkg_lines), encoding="utf-8")

    print(f"[SUCCESS] PEP 503 Simple Index generated at: {SIMPLE_DIR}")
    print(f"Total Packages: {len(packages)}")
    for p in packages:
        print(f"  - {p} ({len(packages[p])} file(s))")


if __name__ == "__main__":
    generate_index()
