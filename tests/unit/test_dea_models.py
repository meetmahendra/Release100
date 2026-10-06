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

"""Unit tests for the entitlement manifest contract (Plan 10, T02)."""

import copy
from typing import Any, Callable, Dict

import pytest
from pydantic import ValidationError

from core_platform.app.entitlements.models import EntitlementManifest, RiskLevel


def _valid() -> Dict[str, Any]:
    """Return a minimal valid manifest payload using imaginary domain names."""
    return {
        "schema_version": 1,
        "namespace": "demo",
        "app_title": "Demo Widget Tracker",
        "actions": [
            {
                "action_id": "demo:item:view",
                "plain_title": "View the item list",
                "plain_description": "Lets the person look at the list of items.",
                "effect": "READ",
                "risk": "LOW",
            },
            {
                "action_id": "demo:item:approve",
                "plain_title": "Approve an item change",
                "plain_description": "Lets the person approve a pending item change.",
                "effect": "APPROVE",
                "risk": "MEDIUM",
                "touches": ["ledger"],
            },
        ],
        "bundles": [
            {
                "bundle_id": "viewer",
                "title": "Viewer",
                "summary": "Can look at items but not change anything at all.",
                "who_its_for": "Anyone who only needs to look",
                "allowed_scopes": ["SELF", "TENANT"],
                "default_scope": "SELF",
                "actions": ["demo:item:view"],
            },
            {
                "bundle_id": "approver",
                "title": "Approver",
                "summary": "Can look at items and approve pending changes.",
                "who_its_for": "Team leads who sign off changes",
                "cannot_do": ["Change settings"],
                "allowed_scopes": ["UNIT"],
                "default_scope": "UNIT",
                "actions": ["demo:item:view", "demo:item:approve"],
                "conflicts_with": [],
            },
        ],
    }


def _mutated(fn: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    payload = copy.deepcopy(_valid())
    fn(payload)
    return payload


def test_valid_manifest_parses() -> None:
    m = EntitlementManifest.model_validate(_valid())
    assert m.namespace == "demo"
    assert set(m.action_map()) == {"demo:item:view", "demo:item:approve"}


def test_bundle_risk_is_max_of_actions() -> None:
    m = EntitlementManifest.model_validate(_valid())
    assert m.bundle_risk("viewer") == RiskLevel.LOW
    assert m.bundle_risk("approver") == RiskLevel.MEDIUM


def test_bundle_digest_is_stable_and_order_independent() -> None:
    m1 = EntitlementManifest.model_validate(_valid())
    swapped = _mutated(lambda p: p["bundles"][1]["actions"].reverse())
    m2 = EntitlementManifest.model_validate(swapped)
    assert m1.bundle_digest("approver") == m2.bundle_digest("approver")
    assert len(m1.bundle_digest("approver")) == 64
    assert m1.bundle_digest("viewer") != m1.bundle_digest("approver")


@pytest.mark.parametrize(
    "mutator, fragment",
    [
        (lambda p: p["actions"].append(copy.deepcopy(p["actions"][0])), "duplicate action_id"),
        (lambda p: p["actions"][0].update(action_id="demo:Bad:View"), "malformed"),
        (lambda p: p["actions"][0].update(action_id="other:item:view"), "outside namespace"),
        (lambda p: p["actions"][1].update(effect="CONFIGURE", risk="MEDIUM"), "below floor"),
        (lambda p: p["bundles"].append(copy.deepcopy(p["bundles"][0])), "duplicate bundle_id"),
        (lambda p: p["bundles"][0]["actions"].append("demo:item:ghost"), "undeclared action"),
        (lambda p: p["bundles"][0].update(default_scope="UNIT"), "default_scope not in allowed_scopes"),
        (lambda p: p["bundles"][0].update(conflicts_with=["nope"]), "conflicts_with unknown/self"),
        (lambda p: p["bundles"][0].update(conflicts_with=["viewer"]), "conflicts_with unknown/self"),
        (lambda p: p["bundles"][0]["actions"].append("demo:item:view"), "duplicate actions"),
        (lambda p: p["bundles"][1].update(cannot_do=[]), "must list cannot_do"),
        (lambda p: p["bundles"].pop(1), "not in any bundle"),
        (lambda p: p.update(namespace="Bad-NS"), "namespace"),
    ],
)
def test_validation_errors(mutator: Callable[[Dict[str, Any]], None], fragment: str) -> None:
    with pytest.raises(ValidationError) as exc:
        EntitlementManifest.model_validate(_mutated(mutator))
    assert fragment in str(exc.value)


def test_bundle_cannot_declare_risk() -> None:
    payload = _mutated(lambda p: p["bundles"][0].update(risk="LOW"))
    with pytest.raises(ValidationError):
        EntitlementManifest.model_validate(payload)


def test_schema_version_2_rejected() -> None:
    with pytest.raises(ValidationError):
        EntitlementManifest.model_validate(_mutated(lambda p: p.update(schema_version=2)))


def test_manifest_is_frozen() -> None:
    m = EntitlementManifest.model_validate(_valid())
    with pytest.raises(ValidationError):
        m.namespace = "changed"  # type: ignore[misc]
