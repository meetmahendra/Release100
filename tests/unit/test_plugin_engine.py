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

"""
Unit tests for Plugin Engine (BaseApplication & PluginLoader).
Adheres strictly to GEES v1.0.
"""

from pathlib import Path
from typing import Any, Dict, List
import pytest
from fastapi import APIRouter, FastAPI

from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.plugin_engine.loader import PluginLoader


class SampleCartridge(BaseApplication):
    """Sample concrete application cartridge for testing."""

    app_id = "sample_cartridge"
    name = "Sample Cartridge"
    version = "1.0.0"
    description = "Test cartridge"
    required_roles = ["operator"]
    supported_channels = ["whatsapp", "web_kiosk"]

    def __init__(self) -> None:
        self.started = False
        self.shutdown_called = False

    def on_startup(self) -> None:
        self.started = True

    def on_shutdown(self) -> None:
        self.shutdown_called = True

    def get_workflow(self) -> Any:
        return {"workflow": "mock_graph"}

    def get_ui_router(self) -> APIRouter:
        router = APIRouter(prefix="/admin/apps/sample")

        @router.get("/ping")
        def ping() -> Dict[str, str]:
            return {"status": "pong"}

        return router

    def get_mcp_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "sample_tool",
                "description": "A sample MCP tool",
                "handler": lambda: "sample_result",
            }
        ]


@pytest.mark.anyio
async def test_base_application_interface() -> None:
    """Test BaseApplication lifecycle, metadata, and default hooks."""
    app = SampleCartridge()
    assert app.app_id == "sample_cartridge"
    assert app.name == "Sample Cartridge"
    assert app.version == "1.0.0"
    assert app.required_roles == ["operator"]
    assert "whatsapp" in app.supported_channels

    health = app.get_health_status()
    assert health["app_id"] == "sample_cartridge"
    assert health["status"] == "operational"

    app.on_startup()
    assert app.started is True

    tools = app.get_mcp_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "sample_tool"

    workflow = app.get_workflow()
    assert workflow["workflow"] == "mock_graph"

    router = app.get_ui_router()
    assert isinstance(router, APIRouter)

    app.on_shutdown()
    assert app.shutdown_called is True


@pytest.mark.anyio
async def test_base_skill_lifecycle() -> None:
    """Test BaseSkill initialization lock, availability, and health status reporting."""
    from core_platform.app.skills.base import BaseSkill

    class ConcreteTestSkill(BaseSkill):
        def __init__(self) -> None:
            super().__init__(skill_name="test_concrete_skill")
            self.init_count = 0

        async def initialize(self) -> None:
            self.init_count += 1

        def is_available(self) -> bool:
            return self._initialized

    skill = ConcreteTestSkill()
    assert skill.is_available() is False
    assert skill.get_health_status()["skill_name"] == "test_concrete_skill"

    # First initialization (also invoking super base method)
    await super(ConcreteTestSkill, skill).initialize()
    assert super(ConcreteTestSkill, skill).is_available() is None
    await skill.ensure_initialized()
    assert skill.is_available() is True
    assert skill.init_count == 1

    # Second initialization (must be no-op)
    await skill.ensure_initialized()
    assert skill.init_count == 1


def test_base_application_defaults() -> None:
    """Test BaseApplication default on_startup, on_shutdown, and get_mcp_tools hooks."""
    class MinimalCartridge(BaseApplication):
        app_id = "minimal"
        name = "Minimal Cartridge"
        def get_workflow(self) -> Any: return None
        def get_ui_router(self) -> Any: return None

    cartridge = MinimalCartridge()
    # Default hooks must execute cleanly without error
    cartridge.on_startup()
    cartridge.on_shutdown()
    assert cartridge.get_mcp_tools() == []




def test_plugin_loader_lifecycle(tmp_path: Path) -> None:
    """Test PluginLoader discovery, loading, and mounting."""
    # Create fake apps directory structure
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()

    app1_dir = apps_dir / "app_one"
    app1_dir.mkdir()
    plugin_code = '''
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from fastapi import APIRouter

class AppOne(BaseApplication):
    app_id = "app_one"
    name = "App One"
    version = "0.1.0"
    def get_workflow(self): return None
    def get_ui_router(self): return APIRouter()
'''
    (app1_dir / "plugin.py").write_text(plugin_code, encoding="utf-8")

    # Non-app dir (no plugin.py)
    (apps_dir / "ignored_dir").mkdir()

    loader = PluginLoader(apps_root=apps_dir, enabled_apps=["app_one"])
    available = loader.discover_available()
    assert "app_one" in available
    assert "ignored_dir" not in available

    # Test load with nonexistent app directory
    nonexistent_loader = PluginLoader(apps_root=tmp_path / "does_not_exist")
    assert nonexistent_loader.discover_available() == []

    # Test loaded_app_ids
    loader._loaded["mock"] = SampleCartridge()
    assert "mock" in loader.loaded_app_ids
    assert len(loader.loaded_app_ids) == 1

    # Test mount_all with FastAPI app
    fastapi_app = FastAPI()
    loader.mount_all(fastapi_app)

    # Test get_all_health_statuses and get_all_mcp_tools
    health_map = loader.get_all_health_statuses()
    assert "mock" in health_map
    assert health_map["mock"]["status"] == "operational"

    tools = loader.get_all_mcp_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "sample_tool"

    # Test shutdown_all
    loader.shutdown_all()
    assert loader._loaded["mock"].shutdown_called is True

    # Test _mount_single error handling
    bad_cartridge = SampleCartridge()
    bad_cartridge.get_ui_router = lambda: None  # type: ignore[assignment]
    loader._mount_single(fastapi_app, "bad_mount", bad_cartridge)


def test_plugin_loader_load_real_cartridges() -> None:
    """Test loading real cartridges from repository apps/ directory."""
    # Test with filter enabling only temperature_marker
    loader = PluginLoader(enabled_apps=["temperature_marker"])
    loaded = loader.load_all()
    assert "temperature_marker" in loaded
    assert "mail_organizer" not in loaded
    tm = loaded["temperature_marker"]
    assert tm.app_id == "temperature_marker"

    # Test loading nonexistent module via _load_single
    assert loader._load_single("nonexistent_app_xyz") is None

