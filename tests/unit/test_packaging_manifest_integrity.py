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
Automated Packaging & Dependency Manifest Integrity Guard (GEES v3.0).

Ensures that:
1. Every third-party library imported in source code is explicitly declared in `pyproject.toml`.
2. Every top-level package and template folder is included in wheel packaging rules.
3. Wheel archives build cleanly and bundle all required HTML templates and static assets.
4. Prevents incomplete code, missing modules, or missing templates from ever being pushed to git.
"""

import ast
import os
from pathlib import Path
import sys
import sysconfig
import zipfile
import tomllib
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

# Mapping of Python import module names to their PyPI distribution package names (normalized lowercase)
MODULE_TO_PYPI_MAP: dict[str, str] = {
    "jwt": "pyjwt",
    "pil": "pillow",
    "cv2": "opencv-python-headless",
    "yaml": "pyyaml",
    "pydantic_settings": "pydantic-settings",
    "dotenv": "python-dotenv",
    "multipart": "python-multipart",
    "googleapiclient": "google-api-python-client",
    "google": "google-api-python-client",
    "markupsafe": "markupsafe",
    "starlette": "starlette",
    "jinja2": "jinja2",
    "onnxruntime": "onnxruntime",
    "pystray": "pystray",
    "psycopg2": "psycopg2-binary",
    "pymysql": "pymysql",
    "duckdb": "duckdb",
}

# Standard library modules to ignore during third-party dependency auditing
STDLIB_MODULES = set(sys.builtin_module_names)
_stdlib_dir = sysconfig.get_path("stdlib")
if _stdlib_dir and os.path.exists(_stdlib_dir):
    for entry in os.listdir(_stdlib_dir):
        if entry.endswith(".py"):
            STDLIB_MODULES.add(entry[:-3].lower())
        elif os.path.isdir(os.path.join(_stdlib_dir, entry)) and os.path.exists(os.path.join(_stdlib_dir, entry, "__init__.py")):
            STDLIB_MODULES.add(entry.lower())

STDLIB_MODULES.update([
    "email", "zoneinfo", "typing_extensions", "concurrent", "ipaddress", "sqlite3",
    "unittest", "urllib", "http", "xml", "html", "json", "csv", "logging", "argparse",
    "hashlib", "dataclasses", "contextvars", "asyncio", "contextlib", "shutil",
    "subprocess", "tempfile", "threading", "time", "math", "re", "uuid", "io",
    "base64", "enum", "pathlib", "abc", "copy", "functools", "itertools", "collections",
    "inspect", "socket", "types", "warnings", "hmac", "secrets", "mimetypes", "struct",
    "signal", "traceback", "__future__", "importlib", "random", "ssl", "zipfile",
    "tarfile", "gzip", "ctypes", "typing", "sys", "os", "tomllib", "site"
])

INTERNAL_ROOTS = {"core_platform", "ops_control_plane", "deployment", "apps", "tests", "packaging", "scripts"}


def _extract_imported_modules(dir_path: Path) -> set[str]:
    """Scan all python files in directory and return all imported top-level module names."""
    imported_modules: set[str] = set()
    for root, _, files in os.walk(dir_path):
        for f in files:
            if f.endswith(".py"):
                p = Path(root) / f
                try:
                    with open(p, "r", encoding="utf-8") as fp:
                        tree = ast.parse(fp.read(), filename=str(p))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                top = alias.name.split(".")[0].strip()
                                if top:
                                    imported_modules.add(top)
                        elif isinstance(node, ast.ImportFrom) and node.module:
                            top = node.module.split(".")[0].strip()
                            if top:
                                imported_modules.add(top)
                except Exception as exc:
                    raise AssertionError(f"Failed to parse AST of {p}: {exc}") from exc
    return imported_modules


def _load_declared_dependencies(pyproject_path: Path) -> set[str]:
    """Extract and normalize all package names declared in pyproject.toml."""
    with open(pyproject_path, "rb") as fp:
        data = tomllib.load(fp)
    declared_raw = data.get("project", {}).get("dependencies", [])
    optional_deps = data.get("project", {}).get("optional-dependencies", {})
    for group_deps in optional_deps.values():
        declared_raw.extend(group_deps)
        
    declared_normalized: set[str] = set()
    for item in declared_raw:
        # Extract base package name before any comparison operators or extras (e.g. 'fastapi>=0.100.0' -> 'fastapi')
        clean = item.split(">=")[0].split("<=")[0].split("==")[0].split(">")[0].split("<")[0].split("~=")[0].split("[")[0].strip().lower()
        declared_normalized.add(clean.replace("_", "-"))
    return declared_normalized


def test_core_platform_all_imports_declared_in_pyproject() -> None:
    """Every third-party library imported in core_platform, ops_control_plane, and deployment must be in pyproject.toml."""
    core_imports = (
        _extract_imported_modules(ROOT_DIR / "core_platform")
        | _extract_imported_modules(ROOT_DIR / "ops_control_plane")
        | _extract_imported_modules(ROOT_DIR / "deployment")
    )
    declared_deps = _load_declared_dependencies(ROOT_DIR / "pyproject.toml")

    missing_deps: list[str] = []
    for mod in sorted(core_imports):
        mod_lower = mod.lower()
        if mod_lower in STDLIB_MODULES or mod in INTERNAL_ROOTS or mod.startswith("release100"):
            continue
        # Map module name to expected PyPI package name
        pypi_name = MODULE_TO_PYPI_MAP.get(mod_lower, mod_lower).replace("_", "-")
        if pypi_name not in declared_deps:
            missing_deps.append(f"Module '{mod}' (PyPI package: '{pypi_name}') is imported but missing in pyproject.toml dependencies")

    assert not missing_deps, "\n".join(missing_deps)


def test_top_level_packages_included_in_pyproject_discovery() -> None:
    """All top-level production packages must be listed in [tool.setuptools.packages.find] include."""
    with open(ROOT_DIR / "pyproject.toml", "rb") as fp:
        data = tomllib.load(fp)
    included = data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("include", [])
    
    # Required core top-level production packages
    assert "core_platform*" in included, "core_platform* must be in [tool.setuptools.packages.find] include"
    assert "ops_control_plane*" in included, "ops_control_plane* must be in [tool.setuptools.packages.find] include"
    assert "deployment*" in included, "deployment* must be in [tool.setuptools.packages.find] include"


def test_package_data_includes_all_template_directories() -> None:
    """All HTML template directories must be registered in [tool.setuptools.package-data]."""
    with open(ROOT_DIR / "pyproject.toml", "rb") as fp:
        data = tomllib.load(fp)
    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    
    assert "core_platform.app.admin_shell" in package_data
    assert "ops_control_plane.super_admin" in package_data


def test_cartridge_manifest_dependencies() -> None:
    """Cartridges must declare all their third-party dependencies."""
    mail_imports = _extract_imported_modules(ROOT_DIR / "apps" / "mail_organizer")
    mail_declared = _load_declared_dependencies(ROOT_DIR / "apps" / "mail_organizer" / "pyproject.toml")

    missing_mail: list[str] = []
    for mod in sorted(mail_imports):
        mod_lower = mod.lower()
        if mod_lower in STDLIB_MODULES or mod in INTERNAL_ROOTS or mod.startswith("release100"):
            continue
        pypi_name = MODULE_TO_PYPI_MAP.get(mod_lower, mod_lower).replace("_", "-")
        if pypi_name not in mail_declared:
            missing_mail.append(f"Mail Organizer imports '{mod}' but '{pypi_name}' is missing in apps/mail_organizer/pyproject.toml")

    assert not missing_mail, "\n".join(missing_mail)

    tm_imports = _extract_imported_modules(ROOT_DIR / "apps" / "temperature_marker")
    tm_declared = _load_declared_dependencies(ROOT_DIR / "apps" / "temperature_marker" / "pyproject.toml")

    missing_tm: list[str] = []
    for mod in sorted(tm_imports):
        mod_lower = mod.lower()
        if mod_lower in STDLIB_MODULES or mod in INTERNAL_ROOTS or mod.startswith("release100"):
            continue
        pypi_name = MODULE_TO_PYPI_MAP.get(mod_lower, mod_lower).replace("_", "-")
        if pypi_name not in tm_declared:
            missing_tm.append(f"Temperature Marker imports '{mod}' but '{pypi_name}' is missing in apps/temperature_marker/pyproject.toml")

    assert not missing_tm, "\n".join(missing_tm)


def test_wheel_archive_contains_all_modules_and_templates() -> None:
    """Build a wheel in a clean temp directory and verify all modules and templates exist inside the .whl."""
    import subprocess
    import tempfile
    
    with tempfile.TemporaryDirectory() as temp_out:
        venv_py = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
        py_bin = str(venv_py) if venv_py.exists() else sys.executable
        
        cmd = [
            py_bin,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            temp_out,
            str(ROOT_DIR),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT_DIR))
        assert res.returncode == 0, f"Wheel build failed: {res.stderr}\n{res.stdout}"
        
        wheels = list(Path(temp_out).glob("*.whl"))
        assert len(wheels) == 1, f"Expected 1 wheel file, found {wheels}"
        
        with zipfile.ZipFile(wheels[0], "r") as zf:
            file_names = zf.namelist()
            
        # 1. Verify Core Platform modules
        assert any("core_platform/main.py" in f for f in file_names), "core_platform/main.py missing from wheel"
        assert any("core_platform/app/admin_shell/routes.py" in f for f in file_names), "admin_shell missing from wheel"
        
        # 2. Verify DevOps Control Plane modules
        assert any("ops_control_plane/super_admin/routes.py" in f for f in file_names), "ops_control_plane missing from wheel"
        assert any("ops_control_plane/tenant_lifecycle.py" in f for f in file_names), "tenant_lifecycle missing from wheel"
        
        # 3. Verify Jinja2 HTML Templates
        assert any("super_admin_tenants.html" in f for f in file_names), "super_admin_tenants.html template missing from wheel"
        assert any("super_admin_audit.html" in f for f in file_names), "super_admin_audit.html template missing from wheel"
        assert any("base_shell.html" in f for f in file_names), "base_shell.html template missing from wheel"
        
        # 4. Verify Static Assets
        assert any("tokens.css" in f for f in file_names), "tokens.css missing from wheel"
        assert any("ui.js" in f for f in file_names), "ui.js missing from wheel"


def test_package_version_synchronization() -> None:
    """GEES v3.1 Invariant: Verify that pyproject.toml versions match __version__ across Core and all cartridges."""
    # 1. Core Platform
    core_toml = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    core_ver = core_toml["project"]["version"]
    from core_platform.app import __version__ as core_py_ver
    assert core_ver == core_py_ver, f"Core pyproject.toml version ({core_ver}) != __version__ ({core_py_ver})"

    # 2. Temperature Marker Cartridge
    tm_toml = tomllib.loads((ROOT_DIR / "apps" / "temperature_marker" / "pyproject.toml").read_text(encoding="utf-8"))
    tm_ver = tm_toml["project"]["version"]
    from apps.temperature_marker import __version__ as tm_py_ver
    assert tm_ver == tm_py_ver, f"Temperature Marker pyproject.toml version ({tm_ver}) != __version__ ({tm_py_ver})"

    # 3. Mail Organizer Cartridge
    mo_toml = tomllib.loads((ROOT_DIR / "apps" / "mail_organizer" / "pyproject.toml").read_text(encoding="utf-8"))
    mo_ver = mo_toml["project"]["version"]
    from apps.mail_organizer import __version__ as mo_py_ver
    assert mo_ver == mo_py_ver, f"Mail Organizer pyproject.toml version ({mo_ver}) != __version__ ({mo_py_ver})"


