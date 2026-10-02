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
Unit Tests for Entry Point Plugin Discovery & Cartridge Scaffolding (GEES v2.0).

Verifies Option 1 decoupled cartridge architecture:
  - Python standard entry points discovery ('release100.cartridges')
  - Local apps/ directory fallback
  - Descriptor resolution and deduplication
  - Standalone cartridge generator / scaffolding
  - Lifecycle hooks and router mounting
"""

from importlib.metadata import EntryPoint
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from fastapi import APIRouter, FastAPI
import pytest

from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.plugin_engine.loader import CartridgeDescriptor, PluginLoader
from core_platform.app.plugin_engine.scaffolder import (
    generate_cartridge_project,
    sanitize_cartridge_name,
    to_pascal_case,
)


class DummyMockPlugin(BaseApplication):
    """Synthetic test plugin for entry point testing."""

    app_id: str = "mock_analytics"
    name: str = "Mock Analytics"
    version: str = "1.0.0"

    def get_workflow(self) -> Any:
        return None

    def get_ui_router(self) -> Optional[APIRouter]:
        router = APIRouter(prefix="/admin/apps/mock-analytics")
        @router.get("/status")
        def status() -> str:
            return "OK"
        return router

    def get_health_status(self) -> Dict[str, Any]:
        return {"status": "HEALTHY"}


def test_sanitize_cartridge_name() -> None:
    """Verify cartridge name sanitization rules."""
    assert sanitize_cartridge_name("smart_billing") == "smart_billing"
    assert sanitize_cartridge_name("Smart-Billing-100") == "smart_billing_100"
    assert sanitize_cartridge_name("  haccp@sensor!  ") == "haccp_sensor"

    with pytest.raises(ValueError):
        sanitize_cartridge_name("   !@#$%   ")


def test_to_pascal_case() -> None:
    """Verify snake_case to PascalCase plugin naming."""
    assert to_pascal_case("smart_billing") == "SmartBillingPlugin"
    assert to_pascal_case("temperature_marker") == "TemperatureMarkerPlugin"


def test_scaffolder_project_generation(tmp_path: Path) -> None:
    """Verify that generate_cartridge_project builds a complete valid python package."""
    created = generate_cartridge_project(
        cartridge_name="smart_meter",
        output_dir=tmp_path,
        author="Energy Team",
        description="Smart Energy Meter Cartridge",
        version="0.2.0",
    )

    assert "pyproject" in created
    assert "readme" in created
    assert "plugin" in created
    assert "routes" in created
    assert "test" in created

    pyproject_text = created["pyproject"].read_text(encoding="utf-8")
    assert 'smart_meter = "smart_meter.plugin:SmartMeterPlugin"' in pyproject_text
    assert 'name = "release100-cartridge-smart-meter"' in pyproject_text

    plugin_text = created["plugin"].read_text(encoding="utf-8")
    assert 'class SmartMeterPlugin(BaseApplication):' in plugin_text
    assert 'app_id: str = "smart_meter"' in plugin_text


def test_entry_point_discovery() -> None:
    """Verify that PluginLoader discovers cartridges registered via importlib.metadata.entry_points."""
    mock_ep = MagicMock(spec=EntryPoint)
    mock_ep.name = "mock_analytics"
    mock_ep.value = "dummy.module:DummyMockPlugin"
    mock_ep.load.return_value = DummyMockPlugin
    mock_ep.dist = MagicMock()
    mock_ep.dist.name = "release100-cartridge-mock-analytics"
    mock_ep.dist.version = "1.0.0"

    with patch("core_platform.app.plugin_engine.loader.entry_points") as mock_eps:
        mock_eps.return_value = [mock_ep]

        loader = PluginLoader(apps_root=Path("/non_existent_path"))
        descriptors = loader.discover_descriptors()

        assert "mock_analytics" in descriptors
        desc = descriptors["mock_analytics"]
        assert desc.source == "entry_point"
        assert desc.package_name == "release100-cartridge-mock-analytics"
        assert desc.version == "1.0.0"

        loaded = loader.load_all()
        assert "mock_analytics" in loaded
        assert isinstance(loaded["mock_analytics"], DummyMockPlugin)


def test_hybrid_discovery_with_filesystem(tmp_path: Path) -> None:
    """Verify that loader merges entry points and local filesystem cartridges."""
    # Create a local test app on disk
    app_dir = tmp_path / "local_scanner"
    app_dir.mkdir(parents=True)
    plugin_py = app_dir / "plugin.py"
    plugin_py.write_text(
        """
from core_platform.app.plugin_engine.base_plugin import BaseApplication

class LocalScannerPlugin(BaseApplication):
    app_id = "local_scanner"
    name = "Local Scanner"
    version = "0.5.0"
    def get_workflow(self): return None
    def get_ui_router(self): return None
""",
        encoding="utf-8",
    )

    with patch("core_platform.app.plugin_engine.loader.entry_points", return_value=[]):
        loader = PluginLoader(apps_root=tmp_path)
        descriptors = loader.discover_descriptors()

        assert "local_scanner" in descriptors
        assert descriptors["local_scanner"].source == "filesystem"


def test_loader_mount_and_lifecycle() -> None:
    """Verify loader mounts routers and handles startup/shutdown cleanly."""
    from starlette.testclient import TestClient

    mock_plugin = DummyMockPlugin()
    loader = PluginLoader(apps_root=Path("/non_existent_path"))
    loader._loaded = {"mock_analytics": mock_plugin}

    fastapi_app = FastAPI()
    loader.mount_all(fastapi_app)

    client = TestClient(fastapi_app)
    response = client.get("/admin/apps/mock-analytics/status")
    assert response.status_code == 200
    assert response.text == '"OK"'

    # Verify health status
    health = loader.get_all_health_statuses()
    assert health["mock_analytics"] == {"status": "HEALTHY"}

    # Verify shutdown
    loader.shutdown_all()
