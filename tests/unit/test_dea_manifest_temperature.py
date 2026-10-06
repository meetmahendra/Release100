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

"""Manifest tests for the temperature_marker cartridge (Plan 10, T20)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from core_platform.app.entitlements.models import EntitlementManifest, RiskLevel
from core_platform.app.entitlements.registry import EntitlementRegistry

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "apps" / "temperature_marker" / "entitlements.json"


def _load() -> Dict[str, Any]:
    data: Dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


def test_manifest_validates_and_registers() -> None:
    manifest = EntitlementManifest.model_validate(_load())
    assert manifest.namespace == "temperature"
    assert len(manifest.actions) == 14
    assert EntitlementRegistry().register_raw("temperature_marker", _load()) is True


def test_derived_bundle_risks() -> None:
    manifest = EntitlementManifest.model_validate(_load())
    assert manifest.bundle_risk("field_operator") == RiskLevel.LOW
    assert manifest.bundle_risk("shift_supervisor") == RiskLevel.MEDIUM
    assert manifest.bundle_risk("fleet_engineer") == RiskLevel.HIGH


def test_separation_of_duties_conflict_is_symmetric() -> None:
    bundles = {b["bundle_id"]: b for b in _load()["bundles"]}
    assert "fleet_engineer" in bundles["shift_supervisor"]["conflicts_with"]
    assert "shift_supervisor" in bundles["fleet_engineer"]["conflicts_with"]


def test_mcp_tools_mapped_once_and_no_wildcards() -> None:
    tools = [t for a in _load()["actions"] for t in a.get("mcp_tools", [])]
    assert len(tools) == len(set(tools)) == 5
    assert "*" not in MANIFEST_PATH.read_text(encoding="ascii")
