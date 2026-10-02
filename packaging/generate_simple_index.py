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

Generates a static HTML repository index for wheels in dist/ so that:
  set UV_EXTRA_INDEX_URL=https://meetmahendra.github.io/Release100/
  uv pip install release100-core
  uv pip install release100-cartridge-temperature-marker
works seamlessly across all machines.
"""

from pathlib import Path
import re
import shutil

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
SIMPLE_DIR = ROOT_DIR / "dist" / "simple"


def normalize_name(name: str) -> str:
    """PEP 503 normalization: lowercase and replace [._-] with -."""
    return re.sub(r"[-_.]+", "-", name).lower()


def generate_index() -> None:
    """Generate PEP 503 static index tree."""
    if SIMPLE_DIR.exists():
        shutil.rmtree(SIMPLE_DIR)
    SIMPLE_DIR.mkdir(parents=True, exist_ok=True)

    packages: dict[str, list[Path]] = {}
    seen_files: set[str] = set()

    search_dirs = [
        DIST_DIR / "all_wheels",
        DIST_DIR / "wheels",
        DIST_DIR,
    ]

    for d in search_dirs:
        if d.exists():
            for f in d.rglob("*"):
                if f.is_file() and (f.suffix == ".whl" or f.name.endswith(".tar.gz")):
                    if "simple" in f.parts:
                        continue
                    if f.name in seen_files:
                        continue
                    m = re.match(r"^([a-zA-Z0-9_\-\.]+?)-\d", f.name)
                    raw_pkg_name = m.group(1) if m else f.name.split("-")[0]
                    norm_pkg = normalize_name(raw_pkg_name)
                    packages.setdefault(norm_pkg, []).append(f)

    # 1. Root index.html (at / and /simple/)
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

    root_html = "\n".join(root_lines)
    (SIMPLE_DIR / "index.html").write_text(root_html, encoding="utf-8")
    (SIMPLE_DIR / ".nojekyll").touch(exist_ok=True)

    # 2. Also create simple/ subdirectory inside simple for backwards-compatible /simple/ URLs
    sub_simple = SIMPLE_DIR / "simple"
    sub_simple.mkdir(parents=True, exist_ok=True)
    (sub_simple / "index.html").write_text(root_html, encoding="utf-8")
    (sub_simple / ".nojekyll").touch(exist_ok=True)

    # 3. Per-package index.html and wheels
    for pkg, files in packages.items():
        pkg_dir = SIMPLE_DIR / pkg
        pkg_dir.mkdir(parents=True, exist_ok=True)

        # Also create nested under simple/{pkg}
        nested_pkg_dir = sub_simple / pkg
        nested_pkg_dir.mkdir(parents=True, exist_ok=True)

        pkg_lines = [
            "<!DOCTYPE html>",
            "<html>",
            f"<head><title>Links for {pkg}</title></head>",
            "<body>",
            f"<h1>Links for {pkg}</h1>",
        ]
        for f in sorted(files, key=lambda x: x.name):
            # Copy file to both pkg_dir and nested_pkg_dir
            dest_file = pkg_dir / f.name
            shutil.copy2(f, dest_file)
            shutil.copy2(f, nested_pkg_dir / f.name)
            pkg_lines.append(f'<a href="{f.name}">{f.name}</a><br/>')

        pkg_lines.extend(["</body>", "</html>"])
        pkg_html = "\n".join(pkg_lines)
        (pkg_dir / "index.html").write_text(pkg_html, encoding="utf-8")
        (nested_pkg_dir / "index.html").write_text(pkg_html, encoding="utf-8")

    print(f"[SUCCESS] PEP 503 Simple Index generated at: {SIMPLE_DIR}")
    print(f"Total Packages: {len(packages)}")
    for p, flist in packages.items():
        print(f"  - {p} ({len(flist)} file(s)): {[x.name for x in flist]}")


if __name__ == "__main__":
    generate_index()
