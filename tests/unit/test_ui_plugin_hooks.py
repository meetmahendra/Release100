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

"""Unit tests for the cartridge UI hooks and loader registration (Plan 11, T06)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import pytest

from core_platform.app.i18n.catalog import I18nCatalog
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.plugin_engine.loader import PluginLoader
from core_platform.app.ui.contracts import NavItem, StatusInfo

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
    yield
    for name in [n for n in sys.modules if n.startswith("fake_ui_") and n.endswith("_plugin")]:
        del sys.modules[name]


def _make_cartridge(root: Path, app_id: str, catalog: Optional[Dict[str, Any]]) -> BaseApplication:
    folder = root / app_id
    folder.mkdir(parents=True)
    plugin_file = folder / "plugin.py"
    plugin_file.write_text(_PLUGIN_SOURCE.format(app_id=app_id), encoding="utf-8")
    if catalog is not None:
        (folder / "locales").mkdir()
        (folder / "locales" / "en_US.json").write_text(json.dumps(catalog), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"fake_ui_{app_id}_plugin", plugin_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    cls = module.FakeCartridge
    instance: BaseApplication = cls()
    return instance


def test_default_hooks_are_empty(tmp_path: Path) -> None:
    app = _make_cartridge(tmp_path, "demo_a", None)
    assert app.get_locale_dir() is None
    assert app.get_ui_nav() == []
    assert app.get_ui_statuses() == {}


def test_locale_dir_discovered_next_to_plugin(tmp_path: Path) -> None:
    app = _make_cartridge(tmp_path, "demo_b", {"apps": {"demo_b": {"title": "Demo B"}}})
    assert app.get_locale_dir() == tmp_path / "demo_b" / "locales"


def test_loader_registers_cartridge_catalogs(tmp_path: Path) -> None:
    loader = PluginLoader(apps_root=tmp_path)
    loader._loaded["demo_c"] = _make_cartridge(tmp_path, "demo_c", {"apps": {"demo_c": {"title": "Demo C"}}})
    loader._loaded["demo_d"] = _make_cartridge(tmp_path, "demo_d", None)
    catalog = I18nCatalog()
    assert loader.register_ui_text(catalog) == {}
    assert catalog.translate("apps.demo_c.title", "en_US") == "Demo C"


def test_loader_rejects_namespace_violation_without_blocking_others(tmp_path: Path) -> None:
    loader = PluginLoader(apps_root=tmp_path)
    loader._loaded["demo_bad"] = _make_cartridge(tmp_path, "demo_bad", {"core": {"hijack": "x"}})
    loader._loaded["demo_ok"] = _make_cartridge(tmp_path, "demo_ok", {"apps": {"demo_ok": {"title": "Fine"}}})
    catalog = I18nCatalog()
    rejected = loader.register_ui_text(catalog)
    assert set(rejected) == {"demo_bad"}
    assert catalog.translate("apps.demo_ok.title", "en_US") == "Fine"
    assert "core.hijack" not in catalog.keys("en_US")


def test_contract_models_are_frozen() -> None:
    nav = NavItem(label_key="apps.demo.nav.home", path="/admin/apps/demo/home")
    assert nav.required_action is None
    with pytest.raises(Exception):
        nav.path = "/x"  # type: ignore[misc]
    info = StatusInfo(code="ok", tone="success", icon="check", label_key="core.status.success")
    assert info.tone == "success"
