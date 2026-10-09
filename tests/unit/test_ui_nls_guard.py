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

"""Automated NLS (National Language Support / I18n) Completeness Guard.

Scans all Jinja2 templates across core platform and domain cartridges to ensure
that 100% of translation keys referenced via ``t('key')`` or ``t("key")`` are
fully defined in the locale catalog (``en_US.json``). Future-proofs against
untranslated UI strings, missing catalog keys, or localization drift.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Set

import pytest

from core_platform.app.i18n.catalog import I18nCatalog, reset_catalog, get_catalog

_T_INVOCATION_RE = re.compile(r"\bt\(\s*['\"]([a-zA-Z0-9_.]+)['\"]")


def _flatten_keys(prefix: str, data: object, keys: Set[str]) -> None:
    if isinstance(data, dict):
        for k, v in data.items():
            full_key = f"{prefix}.{k}" if prefix else str(k)
            _flatten_keys(full_key, v, keys)
    elif isinstance(data, str):
        keys.add(prefix)


def _load_catalog_keys(json_path: Path) -> Set[str]:
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    keys: Set[str] = set()
    _flatten_keys("", raw, keys)
    return keys


def test_core_templates_nls_completeness() -> None:
    """Every t('key') in core platform templates must be defined in core_platform/locales/en_US.json."""
    repo_root = Path(__file__).resolve().parents[2]
    core_locale_file = repo_root / "core_platform" / "locales" / "en_US.json"
    assert core_locale_file.is_file(), f"Missing core locale catalog: {core_locale_file}"

    defined_keys = _load_catalog_keys(core_locale_file)
    assert len(defined_keys) > 50, "Core catalog has unexpectedly few keys"

    # Find all core templates
    core_template_dirs = [
        repo_root / "core_platform" / "app" / "ui" / "templates",
        repo_root / "core_platform" / "app" / "admin_shell" / "templates",
        repo_root / "ops_control_plane" / "super_admin" / "templates",
    ]

    missing_keys: Dict[str, Set[str]] = {}

    for t_dir in core_template_dirs:
        if not t_dir.is_dir():
            continue
        for html_file in t_dir.rglob("*.html"):
            content = html_file.read_text(encoding="utf-8")
            used_keys = set(_T_INVOCATION_RE.findall(content))
            for k in used_keys:
                # Dynamic concatenation keys like t('core.locale.' ~ code) or t('core.shell.mode_' ~ mode)
                if k.endswith((".", "_")):
                    continue
                if not (k in defined_keys or any(k.startswith(f"{dk}_") for dk in defined_keys)):
                    # Check if plural form (e.g. items_one / items_other) or status badge key
                    if f"{k}_one" in defined_keys or f"{k}_other" in defined_keys:
                        continue
                    missing_keys.setdefault(str(html_file.relative_to(repo_root)), set()).add(k)

    assert not missing_keys, f"Found templates with missing NLS catalog keys: {missing_keys}"


def test_cartridge_templates_nls_completeness() -> None:
    """Every t('apps.<app_id>.*') in cartridge templates must be defined in its locales catalog."""
    repo_root = Path(__file__).resolve().parents[2]
    apps_dir = repo_root / "apps"
    if not apps_dir.is_dir():
        return

    for app_path in apps_dir.iterdir():
        if not app_path.is_dir() or app_path.name.startswith((".", "_", "build", "dist")):
            continue
        app_id = app_path.name
        locale_file = app_path / "locales" / "en_US.json"
        if not locale_file.is_file():
            continue

        app_keys = _load_catalog_keys(locale_file)
        core_locale = repo_root / "core_platform" / "locales" / "en_US.json"
        all_keys = app_keys | _load_catalog_keys(core_locale)

        template_dir = app_path / "ui" / "templates"
        if not template_dir.is_dir():
            continue

        missing_keys: Dict[str, Set[str]] = {}
        for html_file in template_dir.rglob("*.html"):
            content = html_file.read_text(encoding="utf-8")
            used_keys = set(_T_INVOCATION_RE.findall(content))
            for k in used_keys:
                if k.endswith("."):
                    continue
                if not (k in all_keys or f"{k}_one" in all_keys or f"{k}_other" in all_keys):
                    missing_keys.setdefault(str(html_file.relative_to(repo_root)), set()).add(k)

        assert not missing_keys, f"Cartridge '{app_id}' has missing NLS keys: {missing_keys}"


def test_catalog_rendering_no_missing_markers() -> None:
    """Verify runtime catalog has zero missing translation warnings on core shell rendering."""
    reset_catalog()
    catalog = get_catalog()
    assert catalog.translate("core.settings.heading", "en_US") == "Master Settings & Diagnostics"
    assert catalog.translate("core.settings.apps_desc", "en_US") == "Installed and operational domain cartridges running on this node."
    assert catalog.translate("core.users.all_cartridges", "en_US") == "All Cartridges (System-Wide)"
    assert catalog.translate("core.tenants.active_configured", "en_US") == "Active (Configured)"
    assert catalog.translate("core.tenants.not_configured", "en_US") == "Not Configured (Missing Key)"
    assert len(catalog.missing_keys()) == 0
