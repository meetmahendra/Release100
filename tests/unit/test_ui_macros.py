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

"""Component macro tests with clean-slate data and escaping (Plan 11, T13)."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from core_platform.app.i18n import catalog as cat
from core_platform.app.ui import status_registry as sr
from core_platform.app.ui.templating import build_templates

IMPORT = '{% from "components/macros.html" import empty_state, kpi_card, badge, data_table, form_field, alert, modal, confirm_dialog with context %}'


@pytest.fixture(autouse=True)
def _catalog() -> Iterator[None]:
    cat.reset_catalog()
    sr.reset_status_registry()
    cat.get_catalog()
    yield
    cat.reset_catalog()
    sr.reset_status_registry()


def _r(body: str, **ctx: Any) -> str:
    templates = build_templates([])
    ctx.setdefault("request", SimpleNamespace(state=SimpleNamespace(locale="en_US")))
    return str(templates.env.from_string(IMPORT + body).render(**ctx))


def test_empty_state_defaults_and_action() -> None:
    out = _r("{{ empty_state() }}")
    assert "Nothing here yet" in out
    out = _r("{{ empty_state(action_key='common.search', action_href='/go') }}")
    assert 'href="/go"' in out and "Search" in out


def test_kpi_card_zero_value_and_escape() -> None:
    out = _r("{{ kpi_card('common.search', 0, 'common.close') }}")
    assert ">0<" in out and "Close" in out
    assert "&lt;b&gt;" in _r("{{ kpi_card('common.search', v) }}", v="<b>")


def test_data_table_empty_shows_empty_state() -> None:
    out = _r("{{ data_table(['common.search'], []) }}")
    assert "<table" not in out and "Nothing here yet" in out


def test_data_table_rows_escaped_with_scoped_headers() -> None:
    out = _r("{{ data_table(['common.search', 'common.close'], rows, 'common.search') }}", rows=[["<i>x</i>", "ok"]])
    assert 'scope="col"' in out and "<caption" in out
    assert "<i>x</i>" not in out and "&lt;i&gt;x&lt;/i&gt;" in out


def test_badge_text_and_icon_present() -> None:
    out = _r("{{ badge('active') }}")
    assert "Active" in out and 'data-icon="check"' in out
    assert "Unknown" in _r("{{ badge('nonexistent_code') }}")


def test_form_field_label_placeholder_help_error() -> None:
    cat.get_catalog().register_entries("en_US", {"test.label": "Name", "test.ph": "e.g. Jane Rao", "test.help": "Your full name"})
    out = _r("{{ form_field('name', 'test.label', placeholder_key='test.ph', help_key='test.help', required=true) }}")
    assert '<label for="f-name"' in out and 'placeholder="e.g. Jane Rao"' in out
    assert "Your full name" in out and "aria-required" in out and 'aria-describedby="f-name-note"' in out
    out = _r("{{ form_field('name', 'test.label', error=e) }}", e="<bad>")
    assert 'aria-invalid="true"' in out and "&lt;bad&gt;" in out and "border-danger" in out


def test_form_field_value_escaped() -> None:
    cat.get_catalog().register_entries("en_US", {"test.label": "Name"})
    out = _r("{{ form_field('n', 'test.label', value=v) }}", v='"><script>')
    assert "<script>" not in out


@pytest.mark.parametrize("tone,role", [("danger", "alert"), ("info", "status"), ("warning", "status"), ("success", "status")])
def test_alert_role_by_tone(tone: str, role: str) -> None:
    out = _r("{{ alert(tone, message=m) }}", tone=tone, m="<x>")
    assert f'role="{role}"' in out and "&lt;x&gt;" in out


def test_alert_with_message_key() -> None:
    assert "Close" in _r("{{ alert('info', message_key='common.close') }}")


def test_modal_has_dialog_semantics() -> None:
    out = _r("{% call modal('m1', 'common.close') %}BODY{% endcall %}")
    assert 'role="dialog"' in out and 'aria-modal="true"' in out and 'aria-labelledby="m1-title"' in out and "BODY" in out


def test_confirm_dialog_is_alertdialog_with_plain_buttons() -> None:
    out = _r("{{ confirm_dialog('c1', 'common.close', action='/do') }}")
    assert 'role="alertdialog"' in out and 'action="/do"' in out
    assert "Yes, continue" in out and "No, go back" in out
    assert re.search(r'type="submit"', out)
