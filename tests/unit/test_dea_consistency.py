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

"""Cross-cartridge consistency tests for the entitlement manifests (Plan 10, T22)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest

from apps.mail_organizer.plugin import MailOrganizerApplication
from apps.temperature_marker.plugin import TemperatureMarkerApplication
from core_platform.app.entitlements.models import EntitlementManifest

ROOT = Path(__file__).resolve().parents[2]
APPS_DIR = ROOT / "apps"
ENTITLEMENTS_DIR = ROOT / "core_platform" / "app" / "entitlements"

# Actions that are declared but intentionally have no route/guard/MCP call site yet.
# Each entry must say why. Empty today: every declared action is wired.
RESERVED_ACTIONS: Dict[str, str] = {}
# MCP tools that exist but are intentionally not mapped to an action yet (with the reason).
RESERVED_MCP_TOOLS: Dict[str, str] = {}


def _manifests() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(APPS_DIR.glob("*/entitlements.json")):
        out[path.parent.name] = json.loads(path.read_text(encoding="utf-8"))
    return out


def _call_site_literals() -> Set[str]:
    found: Set[str] = set()
    for path in APPS_DIR.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name == "require_action" and node.args and isinstance(node.args[0], ast.Constant):
                found.add(str(node.args[0].value))
            if name == "authorize_action" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                found.add(str(node.args[1].value))
    return found


def test_manifests_exist_and_validate() -> None:
    manifests = _manifests()
    assert {"mail_organizer", "temperature_marker"} <= set(manifests)
    for app_id, raw in manifests.items():
        EntitlementManifest.model_validate(raw)


def test_every_call_site_literal_is_declared() -> None:
    declared = {a["action_id"] for raw in _manifests().values() for a in raw["actions"]}
    undeclared = _call_site_literals() - declared
    assert not undeclared, undeclared


def test_no_dead_actions() -> None:
    mcp_mapped = {a["action_id"] for raw in _manifests().values() for a in raw["actions"] if a.get("mcp_tools")}
    referenced = _call_site_literals() | mcp_mapped | set(RESERVED_ACTIONS)
    declared = {a["action_id"] for raw in _manifests().values() for a in raw["actions"]}
    assert declared - referenced == set(), declared - referenced


def test_entitlements_package_never_imports_apps() -> None:
    for path in ENTITLEMENTS_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.split(".")[0] == "apps", (path, node.module)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] != "apps", (path, alias.name)


def test_no_wildcards_in_action_ids() -> None:
    for raw in _manifests().values():
        for action in raw["actions"]:
            assert "*" not in action["action_id"]


@pytest.mark.parametrize("app_cls", [MailOrganizerApplication, TemperatureMarkerApplication])
def test_every_mcp_tool_is_mapped_exactly_once(app_cls: Any) -> None:
    tools: List[str] = [t["name"] for t in app_cls().get_mcp_tools()]
    assert tools, "cartridge exposes no MCP tools"
    mapped: Dict[str, int] = {}
    for raw in _manifests().values():
        for action in raw["actions"]:
            for tool in action.get("mcp_tools", []):
                mapped[tool] = mapped.get(tool, 0) + 1
    for tool in tools:
        if tool in RESERVED_MCP_TOOLS:
            continue
        assert mapped.get(tool) == 1, f"{tool} mapped {mapped.get(tool)} times"


def test_every_mapped_tool_exists() -> None:
    real: Set[str] = set()
    for cls in (MailOrganizerApplication, TemperatureMarkerApplication):
        real |= {t["name"] for t in cls().get_mcp_tools()}
    for raw in _manifests().values():
        for action in raw["actions"]:
            for tool in action.get("mcp_tools", []):
                assert tool in real, f"manifest maps unknown tool {tool}"
