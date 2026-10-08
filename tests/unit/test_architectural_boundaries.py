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
GEES v2.0 Architectural Boundary & Typing Verification Suite.

Enforces Engine A Pillar 3 (Microkernel Isolation) & Pillar 5 (Type Discipline).
Verifies:
1. core_platform has ZERO imports or coupling to apps/ (Pure Microkernel).
2. All source files contain Apache 2.0 copyright notices.
3. All critical modules define complete type annotations.
"""

import ast
import os
from pathlib import Path
from typing import List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CORE_DIR = ROOT_DIR / "core_platform"
APPS_DIR = ROOT_DIR / "apps"


def test_core_platform_has_zero_imports_from_apps() -> None:
    """GEES v2.0 Pillar 3: Verify that core_platform never imports from apps/."""
    violations: List[Tuple[str, int, str]] = []

    for root, _, files in os.walk(CORE_DIR):
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root) / file
                rel_path = file_path.relative_to(ROOT_DIR)
                try:
                    tree = ast.parse(file_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    violations.append((str(rel_path), 0, f"Parse error: {exc}"))
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == "apps" or alias.name.startswith("apps."):
                                violations.append((str(rel_path), node.lineno, f"import {alias.name}"))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and (node.module == "apps" or node.module.startswith("apps.")):
                            violations.append((str(rel_path), node.lineno, f"from {node.module} import ..."))

    assert not violations, (
        f"GEES v2.0 MICROKERNEL VIOLATIONS DETECTED: core_platform must NEVER import from apps/\n"
        + "\n".join(f"  - {path}:{line} -> {detail}" for path, line, detail in violations)
    )


def test_all_source_files_have_apache_license_header() -> None:
    """GEES v2.0 Pillar 9: Verify Apache License 2.0 copyright header on all source files."""
    missing_headers: List[str] = []

    scan_dirs = [CORE_DIR, APPS_DIR]
    for base_dir in scan_dirs:
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith(".py"):
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(ROOT_DIR)
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    if "Copyright 2026 Mahendra GURAV" not in content or "Apache License, Version 2.0" not in content:
                        missing_headers.append(str(rel_path))

    assert not missing_headers, (
        f"GEES v2.0 LICENSING VIOLATIONS: The following source files lack Apache 2.0 headers:\n"
        + "\n".join(f"  - {path}" for path in missing_headers)
    )


def test_function_signatures_have_type_annotations() -> None:
    """GEES v2.0 Pillar 5: Verify that critical core modules feature complete function return type annotations."""
    untyped_functions: List[Tuple[str, str, int]] = []

    critical_files = [
        CORE_DIR / "app" / "config.py",
        CORE_DIR / "app" / "auth" / "jwt_utils.py",
        CORE_DIR / "app" / "auth" / "api_keys.py",
        CORE_DIR / "app" / "auth" / "strategies.py",
        CORE_DIR / "app" / "ingress" / "rate_limiter.py",
        CORE_DIR / "app" / "ingress" / "envelope.py",
        CORE_DIR / "app" / "outbox" / "queue.py",
        CORE_DIR / "app" / "telemetry" / "audit_engine.py",
    ]

    for file_path in critical_files:
        if not file_path.exists():
            continue
        rel_path = file_path.relative_to(ROOT_DIR)
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private dunder methods like __init__ if unannotated return
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue
                if node.returns is None:
                    untyped_functions.append((str(rel_path), node.name, node.lineno))

    assert not untyped_functions, (
        f"GEES v2.0 TYPING VIOLATIONS: The following functions lack return type annotations:\n"
        + "\n".join(f"  - {path} -> {fn}() on line {line}" for path, fn, line in untyped_functions)
    )


def test_core_templates_have_zero_hardcoded_cartridge_names() -> None:
    """GEES v3.0 Pillar 3 & 4: Core Jinja2 templates must NEVER hardcode domain cartridge names or routes."""
    banned_cartridge_tokens = [
        "mail_organizer",
        "temperature_marker",
        "/apps/mail-organizer",
        "/apps/temperature-marker",
    ]
    template_dirs = [
        CORE_DIR / "app" / "admin_shell" / "templates",
        ROOT_DIR / "ops_control_plane" / "super_admin" / "templates",
    ]

    violations: List[Tuple[str, int, str]] = []

    for template_dir in template_dirs:
        if not template_dir.exists():
            continue
        for root, _, files in os.walk(template_dir):
            for file in files:
                if file.endswith(".html"):
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(ROOT_DIR)
                    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for lineno, line in enumerate(lines, 1):
                        for token in banned_cartridge_tokens:
                            if token in line:
                                violations.append((str(rel_path), lineno, f"Contains hardcoded domain cartridge reference: '{token}'"))

    assert not violations, (
        "GEES v3.0 HARDCODING VIOLATION IN CORE TEMPLATES: Core UI templates must discover cartridges dynamically via plugin loader:\n"
        + "\n".join(f"  - {path}:{line} -> {msg}" for path, line, msg in violations)
    )

