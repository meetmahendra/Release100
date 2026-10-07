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

"""Entitlement error message keys and page wiring (Plan 11, T16)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from core_platform.app.i18n import catalog as cat
from core_platform.app.i18n.pseudo import PSEUDO_LOCALE, register_pseudo_locale

CODES = [
    "high_risk_confirmation_required",
    "service_group_cannot_hold_high_risk",
    "scope_not_allowed",
    "binding_already_exists",
    "group_not_found",
    "scope_unit_required",
    "unknown_bundle",
]
TEMPLATE = Path(__file__).resolve().parents[2] / "core_platform" / "app" / "admin_shell" / "templates" / "entitlements.html"


@pytest.fixture(autouse=True)
def _catalog() -> Iterator[None]:
    cat.reset_catalog()
    register_pseudo_locale(cat.get_catalog())
    yield
    cat.reset_catalog()


@pytest.mark.parametrize("code", CODES)
def test_each_reason_code_has_a_message(code: str) -> None:
    text = cat.get_catalog().translate("errors." + code, "en_US")
    assert not text.startswith("[[")
    assert cat.get_catalog().translate("errors." + code, PSEUDO_LOCALE).startswith("[")


def test_every_domain_reason_code_is_mapped() -> None:
    import re

    source = (Path(__file__).resolve().parents[2] / "core_platform" / "app" / "entitlements" / "admin_service.py").read_text(encoding="utf-8")
    domain = {m.lower() for m in re.findall(r'raise ValueError\("([A-Z_]+)"', source)}
    assert domain <= set(CODES)


def test_unknown_code_falls_back_to_generic() -> None:
    assert cat.get_catalog().translate("errors.weird_code", "en_US").startswith("[[")
    assert cat.get_catalog().translate("errors.generic", "en_US") == "Something went wrong. Please try again."


def test_page_uses_shared_fetch_helper() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "window.uiFetch(" in html
    assert "MESSAGES" not in html and "fetch(BASE" not in html
