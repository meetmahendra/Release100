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
Dynamic Application Plugin Loader & Lifecycle Manager.

Adheres strictly to Plan 02 v1.3 Section 11 and Plan 01 v1.4 Section 1.
Scans the apps/ directory, imports domain cartridges, validates the BaseApplication
interface, and mounts their UI routers and MCP tools into the FastAPI host.

Replaces the hardcoded 'if temperature_marker in settings.ENABLED_APPLICATIONS'
blocks in main.py with a fully dynamic, zero-boilerplate mounting lifecycle.
"""

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI

from core_platform.app.plugin_engine.base_plugin import BaseApplication

logger = logging.getLogger("core_platform.plugin_engine")


class PluginLoader:
    """
    Dynamic loader that discovers, validates, and mounts application cartridges.

    Lifecycle:
      1. discover()  — scans apps/ for plugin.py files
      2. load(app)   — imports the plugin module and instantiates BaseApplication
      3. mount(app)  — mounts UI router + MCP tools into FastAPI host
      4. shutdown()  — calls on_shutdown() on all loaded cartridges
    """

    def __init__(
        self,
        apps_root: Optional[Path] = None,
        enabled_apps: Optional[List[str]] = None,
    ) -> None:
        """Initialize PluginLoader.

        Args:
            apps_root: Absolute path to the apps/ directory. Auto-detected if None.
            enabled_apps: List of enabled app IDs from settings.ENABLED_APPLICATIONS.
        """
        if apps_root is None:
            # Resolve relative to this file: core_platform/app/plugin_engine/loader.py → ../../../.. → apps/
            apps_root = Path(__file__).resolve().parent.parent.parent.parent / "apps"
        self.apps_root = apps_root
        self.enabled_apps: List[str] = enabled_apps or []
        self._loaded: Dict[str, BaseApplication] = {}

    def discover_available(self) -> List[str]:
        """Scan the apps/ directory to find all installed cartridges.

        Returns:
            List of app_id strings for all apps that have a plugin.py.
        """
        discovered: List[str] = []
        if not self.apps_root.exists():
            logger.warning("[PluginLoader] apps/ directory not found at %s", self.apps_root)
            return discovered

        for app_dir in sorted(self.apps_root.iterdir()):
            if app_dir.is_dir() and (app_dir / "plugin.py").exists():
                discovered.append(app_dir.name)

        return discovered

    def load_all(self) -> Dict[str, BaseApplication]:
        """Load and instantiate all enabled application cartridges.

        Returns:
            Dict mapping app_id to loaded BaseApplication instance.
        """
        available = self.discover_available()

        for app_id in available:
            if self.enabled_apps and app_id not in self.enabled_apps:
                logger.debug("[PluginLoader] Skipping disabled cartridge: %s", app_id)
                continue

            try:
                instance = self._load_single(app_id)
                if instance is not None:
                    self._loaded[app_id] = instance
                    logger.info("[PluginLoader] Loaded cartridge: %s v%s", app_id, instance.version)
            except Exception as exc:
                logger.error("[PluginLoader] Failed to load cartridge '%s': %s", app_id, exc)

        return self._loaded

    def _load_single(self, app_id: str) -> Optional[BaseApplication]:
        """Import and instantiate a single application cartridge.

        Args:
            app_id: Directory name under apps/ (e.g. 'temperature_marker').

        Returns:
            Instantiated BaseApplication or None on failure.
        """
        module_path = f"apps.{app_id}.plugin"
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            logger.error("[PluginLoader] Cannot import '%s': %s", module_path, exc)
            return None

        # Find the BaseApplication subclass in the module
        app_class: Optional[type] = None
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseApplication)
                and obj is not BaseApplication
            ):
                app_class = obj
                break

        if app_class is None:
            logger.error(
                "[PluginLoader] No BaseApplication subclass found in '%s'", module_path
            )
            return None

        try:
            instance: BaseApplication = app_class()
            return instance
        except Exception as exc:
            logger.error(
                "[PluginLoader] Error instantiating '%s': %s", app_class.__name__, exc
            )
            return None

    def mount_all(self, fastapi_app: FastAPI) -> None:
        """Mount UI routers and register MCP tools for all loaded cartridges.

        Args:
            fastapi_app: The FastAPI application instance to mount routers onto.
        """
        for app_id, instance in self._loaded.items():
            self._mount_single(fastapi_app, app_id, instance)

    def _mount_single(
        self,
        fastapi_app: FastAPI,
        app_id: str,
        instance: BaseApplication,
    ) -> None:
        """Mount a single cartridge's router and trigger on_startup lifecycle."""
        try:
            router = instance.get_ui_router()
            if router is not None:
                fastapi_app.include_router(router)
                logger.info("[PluginLoader] Mounted UI router for: %s", app_id)
        except Exception as exc:
            logger.warning("[PluginLoader] UI router mount failed for '%s': %s", app_id, exc)

        try:
            instance.on_startup()
        except Exception as exc:
            logger.warning("[PluginLoader] on_startup() error for '%s': %s", app_id, exc)

    def shutdown_all(self) -> None:
        """Call on_shutdown() on all loaded cartridges for graceful cleanup."""
        for app_id, instance in self._loaded.items():
            try:
                instance.on_shutdown()
                logger.info("[PluginLoader] Cartridge '%s' shut down cleanly.", app_id)
            except Exception as exc:
                logger.warning("[PluginLoader] on_shutdown() error for '%s': %s", app_id, exc)

    def get_all_health_statuses(self) -> Dict[str, Any]:
        """Aggregate health metadata from all loaded cartridges.

        Returns:
            Dict mapping app_id to its health status dict.
        """
        return {
            app_id: instance.get_health_status()
            for app_id, instance in self._loaded.items()
        }

    def get_all_mcp_tools(self) -> List[Dict[str, Any]]:
        """Collect all MCP tool manifests from loaded cartridges.

        Returns:
            Flat list of tool descriptor dicts ready for MCP server registration.
        """
        all_tools: List[Dict[str, Any]] = []
        for instance in self._loaded.values():
            try:
                tools = instance.get_mcp_tools()
                all_tools.extend(tools)
            except Exception as exc:
                logger.warning("[PluginLoader] get_mcp_tools() error: %s", exc)
        return all_tools

    @property
    def loaded_app_ids(self) -> List[str]:
        """List of currently loaded app IDs."""
        return list(self._loaded.keys())

    def get_application(self, app_id: str) -> Optional[BaseApplication]:
        """Return the loaded cartridge instance for a given app_id, or None.

        Args:
            app_id: Application cartridge identifier (e.g. 'temperature_marker').

        Returns:
            Loaded BaseApplication instance, or None if not loaded.
        """
        return self._loaded.get(app_id)

    def get_all_applications(self) -> Dict[str, BaseApplication]:
        """Return all currently loaded cartridge instances.

        Returns:
            Dict mapping app_id to BaseApplication instance.
        """
        return dict(self._loaded)
