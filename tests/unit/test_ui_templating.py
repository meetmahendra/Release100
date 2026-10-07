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

"""Unit tests for the shared templating factory (Plan 11, T08)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import jinja2
import pytest

from core_platform.app.i18n import catalog as cat
from core_platform.app.ui import status_registry as sr
from core_platform.app.ui import templating
from core_platform.app.ui.templating import build_templates


@pytest.fixture(autouse=True)
def _clean_singletons() -> Any:
    cat.reset_catalog()
    sr.reset_status_registry()
    yield
    cat.reset_catalog()
    sr.reset_status_registry()


def _render(templates: Any, source: str, context: Dict[str, Any]) -> str:
    return str(templates.env.from_string(source).render(**context))


def _request(locale: str = "en_US") -> Any:
    return SimpleNamespace(state=SimpleNamespace(locale=locale))


def test_t_resolves_key_for_request_locale(tmp_path: Path) -> None:
    templates = build_templates([tmp_path])
    assert _render(templates, "{{ t('common.save') }}", {"request": _request()}) == "Save"


def test_t_without_request_uses_default_locale(tmp_path: Path) -> None:
    templates = build_templates([tmp_path])
    assert _render(templates, "{{ t('common.save') }}", {}) == "Save"


def test_t_plural_and_variables(tmp_path: Path) -> None:
    templates = build_templates([tmp_path])
    out = _render(templates, "{{ t('common.records_found', count=1) }}|{{ t('common.records_found', count=4) }}",
                  {"request": _request()})
    assert out == "1 record found|4 records found"


def test_t_missing_key_renders_marker(tmp_path: Path) -> None:
    templates = build_templates([tmp_path])
    assert _render(templates, "{{ t('no.such.key') }}", {"request": _request()}) == "[[no.such.key]]"


def test_interpolated_script_is_escaped(tmp_path: Path) -> None:
    cat.get_catalog().register_entries("en_US", {"test.greet": "Hello {name}"})
    templates = build_templates([tmp_path])
    out = _render(templates, "{{ t('test.greet', name=payload) }}", {"request": _request(), "payload": "<script>alert(1)</script>"})
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_translated_text_is_not_marked_safe(tmp_path: Path) -> None:
    cat.get_catalog().register_entries("en_US", {"test.html": "<b>bold</b>"})
    templates = build_templates([tmp_path])
    out = _render(templates, "{{ t('test.html') }}", {"request": _request()})
    assert out == "&lt;b&gt;bold&lt;/b&gt;"


def test_status_badge_output(tmp_path: Path) -> None:
    templates = build_templates([tmp_path])
    out = _render(templates, "{{ status_badge('active') }}", {"request": _request()})
    assert 'class="ui-badge ui-badge--success"' in out
    assert 'data-icon="check"' in out
    assert ">Active<" in out
    unknown = _render(templates, "{{ status_badge('zzz') }}", {"request": _request()})
    assert "ui-badge--neutral" in unknown and ">Unknown<" in unknown


def test_status_info_global(tmp_path: Path) -> None:
    templates = build_templates([tmp_path])
    assert _render(templates, "{{ status_info('failed').tone }}", {"request": _request()}) == "danger"


def test_loader_prefers_own_dir_then_shared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    own = tmp_path / "own"
    shared = tmp_path / "shared"
    own.mkdir()
    shared.mkdir()
    (own / "base.html").write_text("OWN-BASE", encoding="utf-8")
    (shared / "base.html").write_text("SHARED-BASE", encoding="utf-8")
    (shared / "only_shared.html").write_text("ONLY-SHARED", encoding="utf-8")
    monkeypatch.setattr(templating, "SHARED_TEMPLATE_DIR", shared)
    templates = build_templates([own])
    assert templates.env.get_template("base.html").render() == "OWN-BASE"
    assert templates.env.get_template("only_shared.html").render() == "ONLY-SHARED"
    with pytest.raises(jinja2.TemplateNotFound):
        templates.env.get_template("missing.html")


def test_extra_filters_and_globals_preserved(tmp_path: Path) -> None:
    templates = build_templates([tmp_path], extra_filters={"shout": lambda s: str(s).upper()},
                                extra_globals={"app_label": "demo"})
    assert _render(templates, "{{ 'ab'|shout }}-{{ app_label }}", {}) == "AB-demo"


def test_autoescape_enabled_for_every_template(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("{{ value }}", encoding="utf-8")
    templates = build_templates([tmp_path])
    assert templates.env.get_template("page.html").render(value="<i>") == "&lt;i&gt;"
