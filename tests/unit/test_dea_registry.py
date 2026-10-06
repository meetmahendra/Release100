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

"""Unit tests for the entitlement registry (Plan 10, T04)."""

import copy
import threading
from typing import Any, Dict

import pytest

from core_platform.app.entitlements.models import EntitlementManifest
from core_platform.app.entitlements.registry import EntitlementRegistry


def _payload(namespace: str = "demo", tool: str = "demo_view_items") -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "namespace": namespace,
        "app_title": "Demo Widget Tracker",
        "actions": [
            {
                "action_id": f"{namespace}:item:view",
                "plain_title": "View the item list",
                "plain_description": "Lets the person look at the list of items.",
                "effect": "READ",
                "risk": "LOW",
                "mcp_tools": [tool],
            }
        ],
        "bundles": [
            {
                "bundle_id": "viewer",
                "title": "Viewer",
                "summary": "Can look at items but not change anything at all.",
                "who_its_for": "Anyone who only needs to look",
                "allowed_scopes": ["SELF"],
                "default_scope": "SELF",
                "actions": [f"{namespace}:item:view"],
            }
        ],
    }


def test_register_and_lookup() -> None:
    reg = EntitlementRegistry()
    assert reg.register_raw("app_a", _payload()) is True
    assert reg.list_apps() == ["app_a"]
    assert reg.get_action("demo:item:view") is not None
    assert reg.bundle_contains("app_a", "viewer", "demo:item:view") is True
    assert reg.action_for_mcp_tool("demo_view_items") == "demo:item:view"


def test_namespace_collision_rejected() -> None:
    reg = EntitlementRegistry()
    assert reg.register_raw("app_a", _payload("demo", "tool_a"))
    assert reg.register_raw("app_b", _payload("demo", "tool_b")) is False
    assert "app_b" in reg.rejected
    assert reg.list_apps() == ["app_a"]


def test_bad_payload_recorded_and_registry_unchanged() -> None:
    reg = EntitlementRegistry()
    assert reg.register_raw("app_a", {"schema_version": 1}) is False
    assert reg.rejected["app_a"]
    assert reg.list_apps() == []


def test_bundle_contains_false_for_unknowns() -> None:
    reg = EntitlementRegistry()
    reg.register_raw("app_a", _payload())
    assert reg.bundle_contains("nope", "viewer", "demo:item:view") is False
    assert reg.bundle_contains("app_a", "nope", "demo:item:view") is False
    assert reg.bundle_contains("app_a", "viewer", "demo:item:ghost") is False
    assert reg.get_action("demo:item:ghost") is None
    assert reg.action_for_mcp_tool("unknown_tool") is None


def test_reregister_same_app_replaces() -> None:
    reg = EntitlementRegistry()
    reg.register_raw("app_a", _payload("demo", "tool_one"))
    reg.register_raw("app_a", _payload("demo", "tool_two"))
    assert reg.action_for_mcp_tool("tool_one") is None
    assert reg.action_for_mcp_tool("tool_two") == "demo:item:view"


def test_successful_reregister_clears_previous_rejection() -> None:
    reg = EntitlementRegistry()
    reg.register_raw("app_a", {"bad": True})
    assert "app_a" in reg.rejected
    reg.register_raw("app_a", _payload())
    assert "app_a" not in reg.rejected


def test_duplicate_mcp_tool_within_manifest_rejected() -> None:
    payload = _payload()
    second = copy.deepcopy(payload["actions"][0])
    second["action_id"] = "demo:item:list"
    second["plain_title"] = "List all the items"
    payload["actions"].append(second)
    payload["bundles"][0]["actions"].append("demo:item:list")
    reg = EntitlementRegistry()
    assert reg.register_raw("app_a", payload) is False
    assert "mcp tool" in reg.rejected["app_a"][0]


def test_mcp_tool_owned_by_other_app_rejected() -> None:
    reg = EntitlementRegistry()
    assert reg.register_raw("app_a", _payload("demo", "shared_tool"))
    assert reg.register_raw("app_b", _payload("other", "shared_tool")) is False
    assert "already owned" in reg.rejected["app_b"][0]


def test_direct_register_raises_value_error_on_namespace_clash() -> None:
    reg = EntitlementRegistry()
    reg.register("app_a", EntitlementManifest.model_validate(_payload("demo", "t1")))
    with pytest.raises(ValueError):
        reg.register("app_b", EntitlementManifest.model_validate(_payload("demo", "t2")))


def test_concurrent_registers_do_not_raise() -> None:
    reg = EntitlementRegistry()
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            reg.register_raw(f"app_{i}", _payload(f"ns{i}", f"tool_{i}"))
        except BaseException as exc:  # noqa: BLE001 - test must capture anything
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(reg.list_apps()) == 20
