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

"""Base shell rendering tests (Plan 11, T12)."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from core_platform.app.i18n import catalog as cat
from core_platform.app.i18n.pseudo import PSEUDO_LOCALE, register_pseudo_locale
from core_platform.app.ui import status_registry as sr
from core_platform.app.ui.contracts import Breadcrumb, NavItem
from core_platform.app.ui.templating import build_templates
from core_platform.app.ui.ui_context import UiContext

CHILD = '{% extends "base_shell.html" %}{% block title %}T{% endblock %}{% block content %}<p id="body">BODY</p>{% endblock %}'


@pytest.fixture(autouse=True)
def _catalog() -> Iterator[None]:
    cat.reset_catalog()
    sr.reset_status_registry()
    register_pseudo_locale(cat.get_catalog())
    yield
    cat.reset_catalog()
    sr.reset_status_registry()


def _ui(**kw: Any) -> UiContext:
    base: dict[str, Any] = dict(
        locale="en_US", tenant_name="Acme Test", tenant_slug="acme_test", principal_label="u1",
        role_label_key="core.role.admin", runtime_mode="preview",
        breadcrumbs=[Breadcrumb(label_key="core.shell.home", path="/admin/"), Breadcrumb(label_key="common.save")],
        nav=[NavItem(label_key="common.search", path="/x")],
    )
    base.update(kw)
    return UiContext(**base)


def _render(ui: Any, locale: str = "en_US", tmp: Path | None = None) -> str:
    templates = build_templates([tmp] if tmp else [])
    ctx: dict[str, Any] = {"request": SimpleNamespace(state=SimpleNamespace(locale=locale))}
    if ui is not None:
        ctx["ui"] = ui
    return str(templates.env.from_string(CHILD).render(**ctx))


def test_full_shell_has_landmarks_and_content() -> None:
    html = _render(_ui())
    assert "<aside" in html and "<header" in html and "<main" in html
    assert html.count('aria-label="Main navigation"') == 1
    assert 'aria-label="Breadcrumb"' in html
    assert 'aria-current="page"' in html
    assert 'id="body"' in html
    assert "Acme Test" in html and "Preview" in html and "Sign out" in html
    assert 'href="/x"' in html


def test_bare_shell_has_no_chrome() -> None:
    html = _render(_ui(shell_mode="bare"))
    assert "<aside" not in html and "<header" not in html
    assert "<main" in html and 'id="body"' in html


def test_missing_ui_degrades_to_bare() -> None:
    html = _render(None)
    assert "<aside" not in html and 'id="body"' in html


def test_no_external_urls() -> None:
    html = _render(_ui())
    assert re.findall(r"""(?:src|href)=["']https?://""", html) == []
    assert "/ui-static/tailwind.standalone.js" in html


def test_platform_scope_label_when_no_tenant() -> None:
    html = _render(_ui(tenant_name="", tenant_slug=""))
    assert "All workspaces" in html


@pytest.mark.parametrize("mode", ["live", "preview", "off"])
def test_runtime_mode_badge_has_text_not_colour_only(mode: str) -> None:
    html = _render(_ui(runtime_mode=mode))
    assert f'data-runtime-mode="{mode}"' in html
    assert {"live": "Live", "preview": "Preview", "off": "Off"}[mode] in html


def test_tenant_name_is_escaped() -> None:
    html = _render(_ui(tenant_name="<script>alert(1)</script>"))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_pseudo_locale_wraps_every_shell_string() -> None:
    html = _render(_ui(), locale=PSEUDO_LOCALE)
    assert re.search(r">\[[^<\]]*~+\]<", html)
    for plain in ("Sign out", "Main navigation", "Skip to main content", "Breadcrumb"):
        assert plain not in html


def test_locale_switcher_lists_supported_locales() -> None:
    html = _render(_ui())
    assert "?lang=en_US" in html and "English (US)" in html
