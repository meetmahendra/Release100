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
Automated Version Bump & Strict Parity Guard (GEES v3.1).

Enforces Rule 11 & Rule 14 mechanically:
1. Strict Version Parity: pyproject.toml and __version__ constants MUST match exactly.
2. Semantic Versioning: All versions MUST follow semantic versioning (X.Y.Z).
3. Automated Version Increment Invariant:
   Whenever files in a package (apps/mail_organizer, apps/temperature_marker, core_platform)
   are modified relative to the parent commit, that package's version MUST be incremented.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Dict, List, Optional, Tuple
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass
class PackageSpec:
    name: str
    prefix: str
    toml_rel: str
    toml_abs: Path


def parse_semver(ver_str: str) -> Tuple[int, int, int]:
    """Parse semantic version string 'X.Y.Z' into tuple of integers."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", ver_str.strip())
    if not match:
        raise ValueError(f"Version string '{ver_str}' is not valid semver (expected X.Y.Z)")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def get_git_changed_files(base_ref: str = "HEAD~1") -> Optional[List[str]]:
    """Return list of files changed relative to base_ref (including working tree), or None if git unavailable."""
    try:
        # Check against base_ref
        res = subprocess.run(
            ["git", "diff", base_ref, "--name-only"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            return None
        changed = [line.strip().replace("\\", "/") for line in res.stdout.splitlines() if line.strip()]

        # Also include uncommitted staged/unstaged changes
        res_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res_status.returncode == 0:
            for line in res_status.stdout.splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    changed.append(parts[1].strip().replace("\\", "/"))
        return list(set(changed))
    except Exception:
        return None


def get_git_base_version(file_rel_path: str, base_ref: str = "HEAD~1") -> Optional[str]:
    """Extract pyproject.toml version from a git revision."""
    try:
        git_path = f"{base_ref}:{file_rel_path.replace('\\', '/')}"
        res = subprocess.run(
            ["git", "show", git_path],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            return None
        data = tomllib.loads(res.stdout)
        project_dict = data.get("project")
        if isinstance(project_dict, dict):
            ver = project_dict.get("version")
            if isinstance(ver, str):
                return ver
        return None
    except Exception:
        return None


def test_version_format_and_parity() -> None:
    """GEES Invariant: Verify all pyproject.toml versions match __version__ and follow X.Y.Z."""
    packages: Dict[str, Tuple[Path, str]] = {
        "core": (ROOT_DIR / "pyproject.toml", "core_platform.app"),
        "temperature_marker": (ROOT_DIR / "apps" / "temperature_marker" / "pyproject.toml", "apps.temperature_marker"),
        "mail_organizer": (ROOT_DIR / "apps" / "mail_organizer" / "pyproject.toml", "apps.mail_organizer"),
    }

    for pkg_name, (toml_path, module_name) in packages.items():
        assert toml_path.exists(), f"Missing pyproject.toml for {pkg_name} at {toml_path}"
        toml_data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        toml_ver = toml_data["project"]["version"]

        # Validate format
        parsed_ver = parse_semver(toml_ver)
        assert len(parsed_ver) == 3, f"{pkg_name} version '{toml_ver}' is not valid X.Y.Z"

        # Validate parity with python __version__
        import importlib
        mod = importlib.import_module(module_name)
        py_ver = getattr(mod, "__version__", None)
        assert py_ver is not None, f"Module {module_name} is missing __version__ attribute"
        assert toml_ver == py_ver, (
            f"Strict Version Parity Failed for {pkg_name}: "
            f"pyproject.toml ({toml_ver}) != {module_name}.__version__ ({py_ver})"
        )


def test_package_modification_requires_version_increment() -> None:
    """GEES Invariant: If code in a package was modified relative to base commit, its version MUST be incremented."""
    changed_files = get_git_changed_files("HEAD~1")
    if changed_files is None:
        pytest.skip("Git history not available in current environment")

    # Define packages and their watched paths
    packages: List[PackageSpec] = [
        PackageSpec(
            name="apps/mail_organizer",
            prefix="apps/mail_organizer/",
            toml_rel="apps/mail_organizer/pyproject.toml",
            toml_abs=ROOT_DIR / "apps" / "mail_organizer" / "pyproject.toml",
        ),
        PackageSpec(
            name="apps/temperature_marker",
            prefix="apps/temperature_marker/",
            toml_rel="apps/temperature_marker/pyproject.toml",
            toml_abs=ROOT_DIR / "apps" / "temperature_marker" / "pyproject.toml",
        ),
        PackageSpec(
            name="core_platform",
            prefix="core_platform/",
            toml_rel="pyproject.toml",
            toml_abs=ROOT_DIR / "pyproject.toml",
        ),
    ]

    for pkg in packages:
        prefix = pkg.prefix
        # Check if any substantive code files in this package were modified
        pkg_changes = [
            f for f in changed_files
            if f.startswith(prefix) and not f.endswith(("pyproject.toml", "__pycache__", ".pyc"))
        ]

        if not pkg_changes:
            continue

        toml_abs = pkg.toml_abs
        toml_rel = pkg.toml_rel
        curr_toml = tomllib.loads(toml_abs.read_text(encoding="utf-8"))
        curr_ver_str = curr_toml["project"]["version"]
        curr_semver = parse_semver(curr_ver_str)

        base_ver_str = get_git_base_version(toml_rel, "HEAD~1")
        if base_ver_str is None:
            # New file or no prior commit, skip comparison
            continue

        base_semver = parse_semver(base_ver_str)

        assert curr_semver > base_semver, (
            f"[VERSION-GUARD ERROR] Package '{pkg.name}' has {len(pkg_changes)} modified files "
            f"relative to HEAD~1, but its version was NOT incremented!\n"
            f"  Base Version:    {base_ver_str}\n"
            f"  Current Version: {curr_ver_str}\n"
            f"  Sample Changed Files: {pkg_changes[:5]}\n"
            f"Rule 11 & 14 Directive: You MUST bump the version in {toml_rel} "
            f"and the corresponding __version__ before committing or pushing."
        )
