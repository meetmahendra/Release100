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

"""JS i18n bundle and ui.js behaviour tests (Plan 11, T14)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator

import pytest

from core_platform.app.i18n import catalog as cat
from core_platform.app.ui.templating import build_templates

UI_JS = Path(__file__).resolve().parents[2] / "core_platform" / "app" / "ui" / "static" / "ui.js"


@pytest.fixture(autouse=True)
def _catalog() -> Iterator[None]:
    cat.reset_catalog()
    cat.get_catalog()
    yield
    cat.reset_catalog()


def _bundle(expr: str, locale: str = "en_US") -> Dict[str, str]:
    templates = build_templates([])
    html = templates.env.from_string("{{ " + expr + " }}").render(
        request=SimpleNamespace(state=SimpleNamespace(locale=locale))
    )
    match = re.search(r'id="i18n-bundle">(.*)</script>', html, re.S)
    assert match
    data: Dict[str, str] = json.loads(match.group(1))
    return data


def test_bundle_contains_only_requested_prefixes_plus_errors() -> None:
    data = _bundle("i18n_bundle(['common'])")
    assert "common.save" in data and "errors.generic" in data
    assert not any(k.startswith("core.shell") for k in data)


def test_bundle_default_has_errors_only() -> None:
    data = _bundle("i18n_bundle()")
    assert data and all(k.startswith("errors.") for k in data)


def test_bundle_is_safe_inside_script_element() -> None:
    cat.get_catalog().register_entries("en_US", {"test.evil": "</script><b>&"})
    templates = build_templates([])
    html = templates.env.from_string("{{ i18n_bundle(['test']) }}").render()
    body = html.split(">", 1)[1].rsplit("</script>", 1)[0]
    assert "<" not in body and ">" not in body and "&" not in body
    assert json.loads(body)["test.evil"] == "</script><b>&"


def test_ui_js_is_ascii() -> None:
    UI_JS.read_bytes().decode("ascii")


NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs');
const bundle = JSON.parse(process.argv[1]);
const alerts = [];
global.Element = class {};
global.document = {
  getElementById: (id) => id === 'i18n-bundle' ? { textContent: JSON.stringify(bundle) } :
    (id === 'ui-alerts' ? { appendChild: (n) => alerts.push(n.textContent) } : null),
  createElement: () => ({ setAttribute() {}, className: '', textContent: '' }),
  addEventListener: () => {},
};
global.window = {};
let reply;
global.fetch = () => reply();
eval(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};
(async () => {
  out.t1 = window.t('a.hello', { name: 'Ann' });
  out.t2 = window.t('a.items', { count: 1 });
  out.t3 = window.t('a.items', { count: 4 });
  out.t4 = window.t('no.key');
  const mk = (ok, status, body) => () => Promise.resolve({ ok, status, text: () => Promise.resolve(body) });
  reply = mk(false, 403, JSON.stringify({ code: 'HIGH_RISK_CONFIRMATION_REQUIRED' }));
  out.known = await window.uiFetch('/x');
  reply = mk(false, 400, JSON.stringify({ detail: { code: 'WEIRD_CODE' } }));
  out.unknown = await window.uiFetch('/x');
  reply = mk(false, 500, 'not json');
  out.nonjson = await window.uiFetch('/x');
  reply = mk(true, 200, JSON.stringify({ a: 1 }));
  out.okay = await window.uiFetch('/x');
  reply = () => Promise.reject(new Error('down'));
  out.net = await window.uiFetch('/x');
  window.uiShowError('boom');
  out.alerts = alerts;
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_ui_js_behaviour_under_node() -> None:
    bundle = {
        "a.hello": "Hello {name}", "a.items_one": "{count} item", "a.items_other": "{count} items",
        "errors.generic": "G", "errors.network": "N", "errors.high_risk_confirmation_required": "Confirm first",
    }
    proc = subprocess.run(
        [str(NODE), "-e", HARNESS, json.dumps(bundle), str(UI_JS)],
        capture_output=True, text=True, check=True, timeout=60,
    )
    out: Dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["t1"] == "Hello Ann" and out["t2"] == "1 item" and out["t3"] == "4 items"
    assert out["t4"] == "[[no.key]]"
    assert out["known"]["message"] == "Confirm first" and out["known"]["code"] == "HIGH_RISK_CONFIRMATION_REQUIRED"
    assert out["unknown"]["message"] == "G" and out["unknown"]["code"] == "WEIRD_CODE"
    assert out["nonjson"]["message"] == "G"
    assert out["okay"]["ok"] is True and out["okay"]["data"] == {"a": 1}
    assert out["net"]["message"] == "N" and out["net"]["status"] == 0
    assert out["alerts"] == ["boom"]
