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

"""Unit tests for plugin integration of entitlement manifests (Plan 10, T05)."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import pytest

from core_platform.app.entitlements.registry import EntitlementRegistry
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.plugin_engine.loader import PluginLoader

_PLUGIN_SOURCE = '''
from typing import Any
from core_platform.app.plugin_engine.base_plugin import BaseApplication


class FakeCartridge(BaseApplication):
    app_id = "{app_id}"

    def get_workflow(self) -> Any:
        return None

    def get_ui_router(self) -> Any:
        return None
'''


@pytest.fixture(autouse=True)
def _cleanup_fake_modules() -> Iterator[None]:
    """Remove fake cartridge modules registered during a test."""
    yield
    for name in [n for n in sys.modules if n.startswith('fake_') and n.endswith('_plugin')]:
        del sys.modules[name]


def _manifest(namespace: str, tool: str) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "namespace": namespace,
        "app_title": "Fake Cartridge",
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


def _make_cartridge(root: Path, app_id: str, manifest_text: Optional[str]) -> BaseApplication:
    """Create a real module file (so inspect.getfile points into tmp) and instantiate it."""
    folder = root / app_id
    folder.mkdir(parents=True)
    plugin_file = folder / "plugin.py"
    plugin_file.write_text(_PLUGIN_SOURCE.format(app_id=app_id), encoding="utf-8")
    if manifest_text is not None:
        (folder / "entitlements.json").write_text(manifest_text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"fake_{app_id}_plugin", plugin_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # inspect.getfile requires the module to be importable
    spec.loader.exec_module(module)
    instance: BaseApplication = module.FakeCartridge()
    return instance


def _loader_with(root: Path, **apps: BaseApplication) -> PluginLoader:
    loader = PluginLoader(apps_root=root)
    loader._loaded.update(apps)
    return loader


def test_base_returns_none_without_manifest_file(tmp_path: Path) -> None:
    cart = _make_cartridge(tmp_path, "no_manifest", None)
    assert cart.get_entitlement_manifest() is None


def test_base_reads_manifest_next_to_plugin_module(tmp_path: Path) -> None:
    cart = _make_cartridge(tmp_path, "with_manifest", json.dumps(_manifest("alpha", "alpha_tool")))
    payload = cart.get_entitlement_manifest()
    assert payload is not None and payload["namespace"] == "alpha"


def test_loader_registers_valid_manifest(tmp_path: Path) -> None:
    cart = _make_cartridge(tmp_path, "good", json.dumps(_manifest("alpha", "alpha_tool")))
    registry = EntitlementRegistry()
    _loader_with(tmp_path, good=cart).register_entitlements(registry)
    assert registry.list_apps() == ["good"]
    assert registry.rejected == {}


def test_loader_skips_cartridge_without_manifest(tmp_path: Path) -> None:
    cart = _make_cartridge(tmp_path, "plain", None)
    registry = EntitlementRegistry()
    _loader_with(tmp_path, plain=cart).register_entitlements(registry)
    assert registry.list_apps() == []
    assert registry.rejected == {}


def test_malformed_json_goes_to_rejected(tmp_path: Path) -> None:
    cart = _make_cartridge(tmp_path, "broken", "{not json")
    registry = EntitlementRegistry()
    _loader_with(tmp_path, broken=cart).register_entitlements(registry)
    assert "broken" in registry.rejected
    assert registry.list_apps() == []


def test_non_object_json_goes_to_rejected(tmp_path: Path) -> None:
    cart = _make_cartridge(tmp_path, "listy", "[1, 2, 3]")
    registry = EntitlementRegistry()
    _loader_with(tmp_path, listy=cart).register_entitlements(registry)
    assert "listy" in registry.rejected


def test_invalid_schema_goes_to_rejected(tmp_path: Path) -> None:
    cart = _make_cartridge(tmp_path, "badschema", json.dumps({"schema_version": 1}))
    registry = EntitlementRegistry()
    _loader_with(tmp_path, badschema=cart).register_entitlements(registry)
    assert "badschema" in registry.rejected


def test_one_bad_cartridge_does_not_block_another(tmp_path: Path) -> None:
    bad = _make_cartridge(tmp_path, "bad_one", "{oops")
    good = _make_cartridge(tmp_path, "good_one", json.dumps(_manifest("beta", "beta_tool")))
    registry = EntitlementRegistry()
    _loader_with(tmp_path, bad_one=bad, good_one=good).register_entitlements(registry)
    assert registry.list_apps() == ["good_one"]
    assert "bad_one" in registry.rejected
