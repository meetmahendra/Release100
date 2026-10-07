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

"""Offline static assets and design tokens (Plan 11, T11)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from core_platform.main import app

STATIC = Path(__file__).resolve().parents[2] / "core_platform" / "app" / "ui" / "static"


def test_tokens_css_served_and_has_no_urls() -> None:
    response = TestClient(app).get("/ui-static/tokens.css")
    assert response.status_code == 200
    assert "--ui-primary" in response.text
    assert "http" not in response.text


def test_tailwind_build_served_with_licence_header() -> None:
    response = TestClient(app).get("/ui-static/tailwind.standalone.js")
    assert response.status_code == 200
    assert response.text.startswith("/*!")
    assert "MIT License" in response.text[:300]


def test_tokens_partial_has_theme_and_no_urls() -> None:
    text = (STATIC.parent / "templates" / "components" / "_tokens.html").read_text(encoding="utf-8")
    assert "@theme" in text and "http" not in text


def test_unknown_static_asset_is_404() -> None:
    assert TestClient(app).get("/ui-static/nope.css").status_code == 404
