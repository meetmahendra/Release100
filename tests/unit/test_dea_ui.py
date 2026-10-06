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

"""Unit tests for the groups-and-access admin page (Plan 10, T17)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from core_platform.app.admin_shell import entitlements_routes as er
from core_platform.app.auth.jwt_utils import create_jwt_token
from core_platform.app.entitlements import dependencies as deps
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository

TEMPLATE = Path(er.__file__).parent / "templates" / "entitlements.html"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite:///{tmp_path / 'ui.db'}")
    deps.set_repository(EntitlementRepository(engine=engine))
    deps.set_registry(EntitlementRegistry())  # clean slate: empty catalog
    app = FastAPI()
    app.include_router(er.router)
    yield TestClient(app)
    deps.set_repository(None)
    deps.set_registry(None)
    engine.dispose()


def _cookies(role: str = "admin") -> Dict[str, str]:
    return {"admin_token": create_jwt_token(
        principal_id="ui_admin", roles=[role], permitted_apps=[], tenant_id="tenant_a")}


def test_page_renders_on_clean_slate(client: TestClient) -> None:
    for path in ("/admin/entitlements", "/admin/entitlements/"):
        r = client.get(path, cookies=_cookies())
        assert r.status_code == 200
        assert "Groups and Access" in r.text
        assert "tenant_a" in r.text


def test_page_requires_admin(client: TestClient) -> None:
    assert client.get("/admin/entitlements/").status_code == 401
    assert client.get("/admin/entitlements/", cookies=_cookies("operator")).status_code == 403


def test_template_has_required_vocabulary() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    for needle in (
        "They CAN", "They CANNOT",
        "Members of ", " will be able to ", "They will not be able to",
        "I understand this grants high-governance access",
        "Not available to AI assistants",
        "Changed since granted - review", "Conflicts with: ",
        "Reach: ", "AI assistants and integrations", "People",
    ):
        assert needle in html, needle
    for shape in ("circle", "triangle", "diamond"):
        assert shape in html


def test_risk_badge_texts_come_from_catalog_view() -> None:
    from core_platform.app.entitlements.catalog_view import RISK_LABELS

    assert sorted(RISK_LABELS.values()) == ["High governance", "Low risk", "Operational risk"]

def test_template_is_ascii_only() -> None:
    TEMPLATE.read_bytes().decode("ascii")


def test_template_uses_safe_dom_writes() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "innerHTML" not in html
