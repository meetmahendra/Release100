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

"""Unit tests for the bundle catalog view model (Plan 10, T15)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator

import pytest
from sqlalchemy import create_engine

from core_platform.app.entitlements.catalog_view import build_catalog
from core_platform.app.entitlements.models import RiskLevel, Scope
from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.entitlements.repository import EntitlementRepository

LOW = "demo:item:view"
HIGH = "demo:item:erase"


def _payload() -> Dict[str, Any]:
    return {
        "schema_version": 1, "namespace": "demo", "app_title": "Demo Widget Tracker",
        "actions": [
            {"action_id": LOW, "plain_title": "View the item list",
             "plain_description": "Lets the person look at the list of items.",
             "effect": "READ", "risk": "LOW", "touches": ["Item list"]},
            {"action_id": HIGH, "plain_title": "Erase the item list",
             "plain_description": "Lets the person permanently erase item records.",
             "effect": "WRITE", "risk": "HIGH", "touches": ["Item list", "Archive"]},
        ],
        "bundles": [
            {"bundle_id": "viewer", "title": "Viewer",
             "summary": "Can look at items but not change anything at all.",
             "who_its_for": "Anyone who only needs to look",
             "allowed_scopes": ["SELF", "TENANT"], "default_scope": "SELF", "actions": [LOW]},
            {"bundle_id": "eraser", "title": "Eraser",
             "summary": "Can erase item records, which cannot be undone.",
             "who_its_for": "Trusted administrators only", "cannot_do": ["Cannot view reports"],
             "allowed_scopes": ["TENANT"], "default_scope": "TENANT",
             "actions": [LOW, HIGH], "conflicts_with": ["viewer"]},
        ],
    }


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EntitlementRepository]:
    engine = create_engine(f"sqlite:///{tmp_path / 'cat.db'}")
    yield EntitlementRepository(engine=engine)
    engine.dispose()


def _registry() -> EntitlementRegistry:
    reg = EntitlementRegistry()
    assert reg.register_raw("app_x", _payload())
    return reg


def test_empty_registry_gives_empty_catalog(repo: EntitlementRepository) -> None:
    assert build_catalog("t", EntitlementRegistry(), repo, ["app_x"]) == []


def test_cards_content_and_derived_risk(repo: EntitlementRepository) -> None:
    cards = {c.bundle_id: c for c in build_catalog("t", _registry(), repo, ["app_x"])}
    assert cards["viewer"].risk == RiskLevel.LOW and cards["viewer"].risk_label == "Low risk"
    eraser = cards["eraser"]
    assert eraser.risk == RiskLevel.HIGH and eraser.risk_label == "High governance"
    assert eraser.can_do == ["View the item list", "Erase the item list"]
    assert eraser.touches == ["Item list", "Archive"]
    assert eraser.conflicts_with_titles == ["Viewer"]
    assert eraser.action_count == 2
    assert cards["viewer"].scope_labels["SELF"] == "Only their own records"
    assert cards["viewer"].default_scope == Scope.SELF


def test_apps_not_enabled_omitted(repo: EntitlementRepository) -> None:
    assert build_catalog("t", _registry(), repo, ["other_app"]) == []


def test_assigned_and_drift_counts(repo: EntitlementRepository) -> None:
    reg = _registry()
    manifest = reg.get_manifest("app_x")
    assert manifest is not None
    g1 = repo.create_group("t", "g1", None, "USER")
    g2 = repo.create_group("t", "g2", None, "USER")
    good = manifest.bundle_digest("viewer")
    repo.create_binding("t", g1.id, "app_x", "viewer", Scope.TENANT, None, good, "a")
    repo.create_binding("t", g2.id, "app_x", "viewer", Scope.TENANT, None, "0" * 64, "a")
    other = repo.create_group("other", "g1", None, "USER")
    repo.create_binding("other", other.id, "app_x", "viewer", Scope.TENANT, None, good, "a")
    cards = {c.bundle_id: c for c in build_catalog("t", reg, repo, ["app_x"])}
    assert cards["viewer"].assigned_group_count == 2
    assert cards["viewer"].drifted_binding_count == 1
    assert cards["eraser"].assigned_group_count == 0
