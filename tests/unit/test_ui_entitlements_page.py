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

"""Entitlements page on the shared shell, Pass A (Plan 11, T15)."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any, Dict, Iterator

import pytest

from core_platform.app.admin_shell import entitlements_routes as er
from core_platform.app.admin_shell import routes as admin_routes
from core_platform.app.i18n import catalog as cat
from core_platform.app.i18n.pseudo import PSEUDO_LOCALE, register_pseudo_locale
from core_platform.app.ui import status_registry as sr
from core_platform.app.ui.contracts import Breadcrumb
from core_platform.app.ui.ui_context import UiContext
from tests.unit.test_ui_guards import hardcoded_text


@pytest.fixture(autouse=True)
def _catalog() -> Iterator[None]:
    cat.reset_catalog()
    sr.reset_status_registry()
    register_pseudo_locale(cat.get_catalog())
    yield
    cat.reset_catalog()
    sr.reset_status_registry()


def _render(locale: str) -> str:
    ui = UiContext(
        locale=locale, tenant_name="", tenant_slug="", principal_label="", role_label_key="core.role.admin",
        runtime_mode="preview", breadcrumbs=[Breadcrumb(label_key="core.entitlements.heading")], nav=[],
    )
    ctx: Dict[str, Any] = {
        "request": SimpleNamespace(state=SimpleNamespace(locale=locale)), "ui": ui, "csrf_token": "x",
        "principal": "", "tenant_id": "", "tenant_name": "", "organization": "",
    }
    return str(admin_routes.templates.env.get_template("entitlements.html").render(**ctx))


def _visible_lines(html: str) -> list[str]:
    for pattern in (r"<script\b.*?</script>", r"<style\b.*?</style>", r"<!--.*?-->"):
        html = re.sub(pattern, " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", "\n", html)
    return [ln.strip() for ln in html.splitlines() if re.search(r"[A-Za-z]{2,}", ln)]


def test_pseudo_locale_shows_no_unwrapped_english() -> None:
    lines = _visible_lines(_render(PSEUDO_LOCALE))
    assert lines, "page produced no visible text"
    raw = [ln for ln in lines if not (ln.startswith("[") and ln.endswith("]"))]
    assert raw == []


def test_pseudo_locale_attributes_are_wrapped() -> None:
    html = _render(PSEUDO_LOCALE)
    for attr in ("placeholder", "aria-label"):
        values = re.findall(attr + r'="([^"]*)"', html)
        assert values and all(v.startswith("[") for v in values), attr


def test_english_page_matches_catalog_text() -> None:
    html = _render("en_US")
    assert "Groups and Access" in html and "Create group" in html and "4. What can this person do?" in html


def test_bundle_embeds_all_script_keys() -> None:
    html = _render("en_US")
    match = re.search(r'id="i18n-bundle">(.*?)</script>', html, re.S)
    assert match
    bundle = json.loads(match.group(1))
    used = set(re.findall(r'\bT\("([a-z_]+)"', html))
    assert used, "no T() calls found"
    missing = sorted(k for k in used if "core.entitlements." + k not in bundle)
    assert missing == []
    assert "errors.generic" in bundle


def test_template_script_is_free_of_hardcoded_visible_text_scanner_view() -> None:
    from pathlib import Path

    source = (Path(er.__file__).parent / "templates" / "entitlements.html").read_text(encoding="utf-8")
    assert hardcoded_text(source) == []
