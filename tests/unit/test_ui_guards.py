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

"""UI guards: locale parity, no unsafe translation output, no hard-coded text (Plan 11, T10)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Set

import pytest

from core_platform.app.i18n.catalog import I18nCatalog
from core_platform.app.i18n.pseudo import PSEUDO_LOCALE, pseudo_localize, register_pseudo_locale

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / "tests" / "ui_guards" / "migrated_templates.txt"
_PLACEHOLDER = re.compile(r"\{[a-z_][a-z0-9_]*\}")


def _locale_dirs() -> List[Path]:
    dirs = [ROOT / "core_platform" / "locales"]
    dirs.extend(sorted((ROOT / "apps").glob("*/locales")))
    return [d for d in dirs if d.is_dir()]


def _flat(node: object, prefix: str = "") -> Dict[str, str]:
    out: Dict[str, str] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix] = str(node)
    return out


def _load(directory: Path) -> Dict[str, Dict[str, str]]:
    return {p.stem: _flat(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(directory.glob("*.json"))}


def _base_key(key: str) -> str:
    return re.sub(r"_(zero|one|two|few|many|other)$", "", key)


@pytest.mark.parametrize("directory", _locale_dirs(), ids=lambda d: d.parent.name)
def test_locale_key_and_placeholder_parity(directory: Path) -> None:
    bundles = _load(directory)
    base = bundles.get("en_US")
    assert base is not None, f"{directory} has no en_US.json"
    for locale, entries in bundles.items():
        if locale == "en_US":
            continue
        assert {_base_key(k) for k in entries} <= {_base_key(k) for k in base}, locale
        for key, text in entries.items():
            if key in base:
                assert set(_PLACEHOLDER.findall(text)) == set(_PLACEHOLDER.findall(base[key])), f"{locale}:{key}"


def _template_files() -> List[Path]:
    roots = [ROOT / "core_platform", ROOT / "apps", ROOT / "ops_control_plane"]
    return [p for r in roots if r.is_dir() for p in r.rglob("*.html")]


_SAFE_ON_T = re.compile(r"\{\{[^}]*\bt\([^}]*\)\s*\|\s*safe")


def test_no_safe_filter_on_translations() -> None:
    offenders = [str(p.relative_to(ROOT)) for p in _template_files() if _SAFE_ON_T.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert offenders == []


_STRIP = [
    re.compile(r"<script\b.*?</script>", re.S | re.I),
    re.compile(r"<style\b.*?</style>", re.S | re.I),
    re.compile(r"\{#.*?#\}", re.S),
    re.compile(r"\{%.*?%\}", re.S),
    re.compile(r"\{\{.*?\}\}", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<[^>]+>"),
]


def hardcoded_text(source: str) -> List[str]:
    """Return visible text fragments containing letters that are not catalog output."""
    for pattern in _STRIP:
        source = pattern.sub("\n" if pattern.pattern.startswith("<[^>]") else " ", source)
    found = []
    for line in source.splitlines():
        text = re.sub(r"&[a-z]+;|&#\d+;", " ", line).strip()
        if re.search(r"[A-Za-z]{2,}", text):
            found.append(text)
    return found


def _migrated() -> List[str]:
    if not ALLOWLIST.exists():
        return []
    lines = [ln.strip() for ln in ALLOWLIST.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


@pytest.mark.parametrize("rel", _migrated() or ["__none__"])
def test_migrated_templates_have_no_hardcoded_text(rel: str) -> None:
    if rel == "__none__":
        pytest.skip("no templates migrated yet")
    path = ROOT / rel
    assert path.is_file(), rel
    assert hardcoded_text(path.read_text(encoding="utf-8")) == []


def test_scanner_detects_plain_text_and_ignores_markup() -> None:
    assert hardcoded_text("<h1>Hello there</h1>") == ["Hello there"]
    assert hardcoded_text("<h1>{{ t('a.b') }}</h1>{% if x %}<p>{{ y }}</p>{% endif %}") == []
    assert hardcoded_text("<script>var a = 'text';</script><style>p{color:red}</style>") == []
    assert hardcoded_text("<td>&nbsp;</td><td>42</td>") == []


def test_pseudo_localize_preserves_placeholders() -> None:
    out = pseudo_localize("Found {count} records")
    assert out.startswith("[") and out.endswith("]")
    assert "{count}" in out
    assert "Found" not in out
    assert len(out) > len("Found {count} records")


def test_pseudo_locale_registers_every_default_key() -> None:
    cat = I18nCatalog()
    cat.load_core(ROOT / "core_platform" / "locales")
    count = register_pseudo_locale(cat)
    assert count == len(cat.keys("en_US"))
    assert PSEUDO_LOCALE in cat.locales()
    assert cat.translate("common.save", PSEUDO_LOCALE).startswith("[")
    assert cat.translate("common.records_found", PSEUDO_LOCALE, count=3).count("3") >= 1


def test_every_pseudo_value_is_bracketed() -> None:
    cat = I18nCatalog()
    cat.load_core(ROOT / "core_platform" / "locales")
    register_pseudo_locale(cat)
    unwrapped: Set[str] = {k for k in cat.keys(PSEUDO_LOCALE) if not cat.translate(k, PSEUDO_LOCALE).startswith("[")}
    assert unwrapped == set()
