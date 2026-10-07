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

"""Unit tests for the status registry (Plan 11, T07)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_platform.app.i18n.catalog import I18nCatalog
from core_platform.app.ui import status_registry as sr
from core_platform.app.ui.status_registry import StatusInfo, StatusRegistry


def test_generic_lookup_and_normalisation() -> None:
    reg = StatusRegistry()
    assert reg.get("active").tone == "success"
    assert reg.get("  ACTIVE ").code == "active"
    assert reg.get("shadow").label_key == "core.status.shadow"


def test_unknown_code_returns_neutral_fallback() -> None:
    info = StatusRegistry().get("Some Weird-Code")
    assert info.tone == "neutral"
    assert info.label_key == "core.status.unknown"
    assert info.code == "some_weird_code"
    assert StatusRegistry().get("").code == "unknown"


def _app_status(code: str, app: str = "demo") -> StatusInfo:
    return StatusInfo(code=code, tone="warning", icon="clock", label_key=f"apps.{app}.status.{code}")


def test_cartridge_status_scoped_to_its_app() -> None:
    reg = StatusRegistry()
    reg.register_app("demo", {"on_route": _app_status("on_route")})
    assert reg.get("on_route", app_id="demo").label_key == "apps.demo.status.on_route"
    assert reg.get("on_route").label_key == "core.status.unknown"
    assert reg.get("on_route", app_id="other").label_key == "core.status.unknown"
    assert "on_route" in reg.codes("demo")
    assert "on_route" not in reg.codes()


def test_cartridge_cannot_override_core_status() -> None:
    reg = StatusRegistry()
    reg.register_app("demo", {"active": _app_status("active")})
    assert reg.get("active").label_key == "core.status.active"  # core wins outside the app
    assert reg.get("active", app_id="demo").label_key == "apps.demo.status.active"


@pytest.mark.parametrize(
    "code,key",
    [("Bad Code", "apps.demo.status.x"), ("ok", "core.status.ok"), ("ok", "apps.other.status.ok")],
)
def test_register_app_validation(code: str, key: str) -> None:
    info = StatusInfo(code=code.lower().replace(" ", "_"), tone="info", icon="eye", label_key=key)
    with pytest.raises(ValueError):
        StatusRegistry().register_app("demo", {code: info})


def test_mismatched_code_rejected() -> None:
    info = StatusInfo(code="other", tone="info", icon="eye", label_key="apps.demo.status.other")
    with pytest.raises(ValueError):
        StatusRegistry().register_app("demo", {"ok": info})


def test_every_label_key_exists_in_real_core_catalog() -> None:
    core = Path(sr.__file__).resolve().parents[2] / "locales"
    catalog = I18nCatalog()
    catalog.load_core(core)
    missing = [k for k in StatusRegistry().label_keys() if k not in catalog.keys("en_US")]
    assert missing == []


def test_singleton_and_reset() -> None:
    sr.reset_status_registry()
    first = sr.get_status_registry()
    assert first is sr.get_status_registry()
    sr.reset_status_registry()
    assert sr.get_status_registry() is not first
    sr.reset_status_registry()
