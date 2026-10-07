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

"""Unit tests for UI locale negotiation (Plan 11, T05)."""

from __future__ import annotations

from typing import List

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core_platform.app.i18n.negotiation import LocaleMiddleware, negotiate_locale, parse_accept_language

SUPPORTED: List[str] = ["en_US", "hi_IN"]


def test_query_beats_cookie_beats_header() -> None:
    assert negotiate_locale("hi_IN", "en_US", "en-US", SUPPORTED, "en_US") == "hi_IN"
    assert negotiate_locale(None, "hi_IN", "en-US", SUPPORTED, "en_US") == "hi_IN"
    assert negotiate_locale(None, None, "hi-IN,en;q=0.5", SUPPORTED, "en_US") == "hi_IN"


def test_default_when_nothing_matches() -> None:
    assert negotiate_locale(None, None, None, SUPPORTED, "en_US") == "en_US"
    assert negotiate_locale("fr_FR", "de_DE", "fr-FR,de;q=0.8", SUPPORTED, "en_US") == "en_US"


def test_unsupported_query_falls_through_to_next_source() -> None:
    assert negotiate_locale("fr_FR", "hi_IN", None, SUPPORTED, "en_US") == "hi_IN"


def test_language_only_and_case_insensitive_matching() -> None:
    assert negotiate_locale("hi", None, None, SUPPORTED, "en_US") == "hi_IN"
    assert negotiate_locale("EN-us", None, None, SUPPORTED, "en_US") == "en_US"
    assert negotiate_locale("en_gb", None, None, SUPPORTED, "en_US") == "en_US"


def test_accept_language_quality_ordering_and_garbage() -> None:
    assert parse_accept_language("en;q=0.4, hi-IN;q=0.9") == ["hi-IN", "en"]
    assert parse_accept_language("*, ;;;, en;q=abc, !!!, hi") == ["hi"]
    assert parse_accept_language("") == []


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(LocaleMiddleware, supported=SUPPORTED, default="en_US", cookie_name="ui_locale")

    @app.get("/probe")
    def probe(request: Request) -> dict[str, str]:
        return {"locale": request.state.locale}

    return TestClient(app)


def test_middleware_sets_state_and_cookie_for_explicit_lang(client: TestClient) -> None:
    resp = client.get("/probe?lang=hi_IN")
    assert resp.json() == {"locale": "hi_IN"}
    assert "ui_locale=hi_IN" in resp.headers["set-cookie"]
    # cookie now drives the next request without a query value
    assert client.get("/probe").json() == {"locale": "hi_IN"}


def test_middleware_does_not_set_cookie_for_unsupported_lang(client: TestClient) -> None:
    resp = client.get("/probe?lang=fr_FR")
    assert resp.json() == {"locale": "en_US"}
    assert "set-cookie" not in resp.headers


def test_middleware_uses_accept_language_header(client: TestClient) -> None:
    resp = client.get("/probe", headers={"Accept-Language": "hi-IN,en;q=0.5"})
    assert resp.json() == {"locale": "hi_IN"}
    assert "set-cookie" not in resp.headers


def test_real_app_applies_locale_middleware() -> None:
    """The platform app negotiates a locale for every request (cookie set from ?lang=)."""
    from core_platform.main import app

    client = TestClient(app, follow_redirects=False)
    resp = client.get("/admin/login?lang=en_US")
    assert resp.status_code == 200
    assert "ui_locale=en_US" in resp.headers.get("set-cookie", "")
