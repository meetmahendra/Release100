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

"""Manifest tests for the mail_organizer cartridge (Plan 10, T18)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, Set

from core_platform.app.entitlements.models import EntitlementManifest, RiskLevel
from core_platform.app.entitlements.registry import EntitlementRegistry

APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "mail_organizer"
MANIFEST_PATH = APP_DIR / "entitlements.json"


def _load() -> Dict[str, Any]:
    data: Dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


def _literals(source_path: Path) -> Set[str]:
    """Return string literals passed to require_action(...) / authorize_action(..., '...')."""
    found: Set[str] = set()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if name == "require_action" and node.args and isinstance(node.args[0], ast.Constant):
            found.add(str(node.args[0].value))
        if name == "authorize_action" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            found.add(str(node.args[1].value))
    return found


def test_manifest_validates_and_registers() -> None:
    manifest = EntitlementManifest.model_validate(_load())
    assert manifest.namespace == "mail"
    reg = EntitlementRegistry()
    assert reg.register_raw("mail_organizer", _load()) is True


def test_derived_bundle_risks() -> None:
    manifest = EntitlementManifest.model_validate(_load())
    assert manifest.bundle_risk("inbox_user") == RiskLevel.LOW
    assert manifest.bundle_risk("project_lead") == RiskLevel.MEDIUM
    assert manifest.bundle_risk("mailbox_admin") == RiskLevel.HIGH


def test_every_route_literal_is_declared() -> None:
    declared = {a["action_id"] for a in _load()["actions"]}
    used = _literals(APP_DIR / "ui" / "routes.py")
    assert used, "mail routes must be gated"
    assert used <= declared, used - declared


def test_manifest_has_no_wildcards_or_real_names() -> None:
    raw = MANIFEST_PATH.read_text(encoding="ascii")
    assert "*" not in raw
    for forbidden in ("Jira", "Linear", "Google"):
        assert forbidden not in raw
