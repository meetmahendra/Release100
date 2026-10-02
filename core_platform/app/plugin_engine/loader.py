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
Dynamic Application Plugin Loader & Lifecycle Manager (GEES v2.0).

Adheres strictly to Plan 02 v1.3 Section 11 and Plan 01 v1.4 Section 1.
Supports hybrid cartridge discovery:
  1. Python Standard Entry Points (group='release100.cartridges' or 'core_platform.apps')
  2. Local apps/ Directory Filesystem Scanning (Zero-Boilerplate Monorepo Fallback)

Mounts UI routers, configures polyglot persistence paradigms (A/B/C),
and registers MCP tools into the FastAPI host dynamically.
"""

from dataclasses import dataclass
import importlib
from importlib.metadata import EntryPoint, entry_points
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, cast

from fastapi import FastAPI

from core_platform.app.plugin_engine.base_plugin import BaseApplication

logger = logging.getLogger("core_platform.plugin_engine")


@dataclass
class CartridgeDescriptor:
    """Descriptor for a discovered application cartridge."""

    app_id: str
    source: str  # "entry_point" | "filesystem"
    target: str  # Entry point target (e.g. 'apps.foo:Plugin') or directory path
    package_name: Optional[str] = None
    version: Optional[str] = None
    entry_point_obj: Optional[EntryPoint] = None


class PluginLoader:
    """
    Dynamic loader that discovers, validates, and mounts application cartridges.

    Lifecycle:
      1. discover_descriptors() / discover_available() — scans entry points and apps/
      2. load_all()   — imports modules, instantiates BaseApplication, binds DBs
      3. mount_all()  — mounts UI routers + MCP tools into FastAPI host
      4. shutdown_all() — calls on_shutdown() on all loaded cartridges
    """

    ENTRY_POINT_GROUPS: List[str] = ["release100.cartridges", "core_platform.apps"]

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
        self.enabled_apps: Optional[List[str]] = enabled_apps
        self._loaded: Dict[str, BaseApplication] = {}
        self._descriptors: Dict[str, CartridgeDescriptor] = {}

    def discover_descriptors(self) -> Dict[str, CartridgeDescriptor]:
        """Discover all cartridges registered via Python entry points or local filesystem.

        Returns:
            Dict mapping app_id to its CartridgeDescriptor.
        """
        descriptors: Dict[str, CartridgeDescriptor] = {}

        # 1. Discover via Python Standard Entry Points
        for group in self.ENTRY_POINT_GROUPS:
            try:
                eps = entry_points(group=group)
                for ep in eps:
                    app_id = ep.name
                    if app_id not in descriptors:
                        dist = getattr(ep, "dist", None)
                        pkg_name = getattr(dist, "name", None) if dist else None
                        pkg_ver = getattr(dist, "version", None) if dist else None
                        descriptors[app_id] = CartridgeDescriptor(
                            app_id=app_id,
                            source="entry_point",
                            target=ep.value,
                            package_name=pkg_name,
                            version=pkg_ver,
                            entry_point_obj=ep,
                        )
                        logger.debug(
                            "[PluginLoader] Discovered entry-point cartridge: %s (%s)",
                            app_id,
                            ep.value,
                        )
            except Exception as exc:
                logger.debug("[PluginLoader] Entry point group '%s' query notice: %s", group, exc)

        # 2. Discover via Local Filesystem Fallback (apps/ directory)
        if self.apps_root.exists():
            for app_dir in sorted(self.apps_root.iterdir()):
                if app_dir.is_dir() and (app_dir / "plugin.py").exists():
                    app_id = app_dir.name
                    if app_id not in descriptors:
                        descriptors[app_id] = CartridgeDescriptor(
                            app_id=app_id,
                            source="filesystem",
                            target=str(app_dir),
                        )
                        logger.debug(
                            "[PluginLoader] Discovered filesystem cartridge: %s (%s)",
                            app_id,
                            app_dir,
                        )

        self._descriptors = descriptors
        return descriptors

    def discover_available(self) -> List[str]:
        """Scan entry points and apps/ directory to find all available cartridge IDs.

        Returns:
            List of app_id strings for all discovered cartridges.
        """
        descriptors = self.discover_descriptors()
        return list(descriptors.keys())

    def load_all(self) -> Dict[str, BaseApplication]:
        """Load and instantiate all enabled application cartridges.

        Returns:
            Dict mapping app_id to loaded BaseApplication instance.
        """
        descriptors = self.discover_descriptors()

        for app_id, descriptor in descriptors.items():
            if self.enabled_apps is not None and app_id not in self.enabled_apps:
                logger.debug("[PluginLoader] Skipping disabled cartridge: %s", app_id)
                continue

            try:
                instance = self._load_single_descriptor(descriptor)
                if instance is not None:
                    self._loaded[app_id] = instance
                    src_tag = f"ENTRY_POINT ({descriptor.target})" if descriptor.source == "entry_point" else "FILESYSTEM"
                    logger.info("[PluginLoader] Loaded cartridge '%s' v%s via [%s]", app_id, instance.version, src_tag)

                    # ── Pluggable Polyglot Database Management Integration (GEES v2.0) ──
                    try:
                        from core_platform.app.db.manager import get_db_manager
                        db_mgr = get_db_manager()

                        custom_url: Optional[str] = getattr(instance, "custom_database_url", None)
                        meta = instance.get_metadata()
                        if custom_url:
                            # Paradigm C: Dedicated Custom SQL Database via Core Factory
                            custom_factory = db_mgr.create_custom_factory(app_id, custom_url)
                            instance.on_bind_engine(custom_factory.get_engine())
                            logger.info("[PluginLoader] Paradigm C (Dedicated DB): Registered factory for '%s'", app_id)
                        elif meta is not None:
                            # Paradigm A: Core-Facilitated Shared Platform Database
                            db_mgr.register_cartridge_metadata(app_id, meta)
                            instance.on_bind_engine(db_mgr.get_engine())
                            logger.info("[PluginLoader] Paradigm A (Core-Facilitated): Registered metadata for '%s'", app_id)
                        else:
                            # Paradigm B: 100% Cartridge-Autonomous (MongoDB, DuckDB, Flat Files, External CRM)
                            logger.debug("[PluginLoader] Paradigm B (Cartridge-Autonomous): '%s' manages self-persistence", app_id)
                    except Exception as db_exc:
                        logger.warning("[PluginLoader] DB registration notice for '%s': %s", app_id, db_exc)
            except Exception as exc:
                logger.error("[PluginLoader] Failed to load cartridge '%s': %s", app_id, exc)

        # ── Centralized Platform DDL Table Initialization (Core Kernel) ───────────
        try:
            from core_platform.app.db.manager import get_db_manager
            db_mgr = get_db_manager()
            initialized_tables = db_mgr.init_tables()
            if initialized_tables:
                logger.info("[PluginLoader] Centralized Kernel DDL initialized tables: %s", initialized_tables)
        except Exception as ddl_exc:
            logger.warning("[PluginLoader] Centralized Kernel DDL initialization warning: %s", ddl_exc)

        return self._loaded

    def _load_single(self, app_id: str) -> Optional[BaseApplication]:
        """Import and instantiate a single application cartridge by ID.

        Args:
            app_id: Cartridge identifier.

        Returns:
            Instantiated BaseApplication or None on failure.
        """
        descriptors = self.discover_descriptors()
        desc = descriptors.get(app_id)
        if desc is None:
            # Fallback to direct filesystem specification
            desc = CartridgeDescriptor(
                app_id=app_id,
                source="filesystem",
                target=f"apps.{app_id}.plugin",
            )
        return self._load_single_descriptor(desc)

    def _load_single_descriptor(self, descriptor: CartridgeDescriptor) -> Optional[BaseApplication]:
        """Import and instantiate a single cartridge from a descriptor."""
        app_class: Optional[Type[BaseApplication]] = None

        if descriptor.source == "entry_point" and descriptor.entry_point_obj is not None:
            try:
                loaded_obj = descriptor.entry_point_obj.load()
                if isinstance(loaded_obj, type) and issubclass(loaded_obj, BaseApplication):
                    app_class = loaded_obj
                elif isinstance(loaded_obj, BaseApplication):
                    return loaded_obj
            except Exception as ep_exc:
                logger.warning(
                    "[PluginLoader] Entry point load failed for '%s', attempting module fallback: %s",
                    descriptor.app_id,
                    ep_exc,
                )

        if app_class is None:
            # Module import path resolution
            if descriptor.source == "entry_point" and ":" in descriptor.target:
                mod_name, cls_name = descriptor.target.split(":", 1)
            else:
                mod_name = f"apps.{descriptor.app_id}.plugin"
                cls_name = ""

            try:
                module = importlib.import_module(mod_name)
            except ImportError as exc:
                logger.error("[PluginLoader] Cannot import module '%s': %s", mod_name, exc)
                return None

            if cls_name:
                cand = getattr(module, cls_name, None)
                if isinstance(cand, type) and issubclass(cand, BaseApplication) and cand is not BaseApplication:
                    app_class = cand

            if app_class is None:
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
            logger.error("[PluginLoader] No BaseApplication subclass found for '%s'", descriptor.app_id)
            return None

        try:
            sig = inspect.signature(app_class)
            init_kwargs: Dict[str, Any] = {}

            if "engine" in sig.parameters and not getattr(app_class, "custom_database_url", None):
                try:
                    from core_platform.app.db.manager import get_db_manager
                    init_kwargs["engine"] = get_db_manager().get_engine()
                except Exception:
                    pass

            instance: BaseApplication = app_class(**init_kwargs)
            return instance
        except Exception as exc:
            logger.error("[PluginLoader] Error instantiating '%s': %s", app_class.__name__, exc)
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
        """Aggregate health metadata from all loaded cartridges."""
        return {
            app_id: instance.get_health_status()
            for app_id, instance in self._loaded.items()
        }

    def get_all_mcp_tools(self) -> List[Dict[str, Any]]:
        """Collect all MCP tool manifests from loaded cartridges."""
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
        """Return the loaded cartridge instance for a given app_id, or None."""
        return self._loaded.get(app_id)

    def get_all_applications(self) -> Dict[str, BaseApplication]:
        """Return all currently loaded cartridge instances."""
        return dict(self._loaded)
