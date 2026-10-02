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
Dynamic Applications Registry & Monitoring Engine (`apps_registry.py`).

Adheres strictly to Plan 07 v1.0 and GEES v2.0.
Provides:
1. Dynamic discovery of installed domain cartridges (entry points and apps/).
2. Live comparison against `settings.ENABLED_APPLICATIONS`.
3. Health and poller status monitoring.
4. Clean application metadata introspection for Windows Tray UI and Web Console.
"""

import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from core_platform.app.config import settings

logger = logging.getLogger("core_platform.apps_registry")


class ApplicationInfo:
    """Metadata container for an installed domain cartridge."""

    def __init__(
        self,
        app_name: str,
        title: str,
        description: str,
        dashboard_url: str,
        is_active: bool,
        has_poller: bool = False,
        poller_status: Optional[str] = None,
    ) -> None:
        """Initialize application info."""
        self.app_name = app_name
        self.title = title
        self.description = description
        self.dashboard_url = dashboard_url
        self.is_active = is_active
        self.has_poller = has_poller
        self.poller_status = poller_status

    def to_dict(self) -> Dict[str, Any]:
        """Serialize metadata to dictionary."""
        return {
            "app_name": self.app_name,
            "title": self.title,
            "description": self.description,
            "dashboard_url": self.dashboard_url,
            "is_active": self.is_active,
            "status": "ACTIVE" if self.is_active else "INACTIVE",
            "has_poller": self.has_poller,
            "poller_status": self.poller_status,
        }


class ApplicationRegistry:
    """Dynamic catalog and runtime manager for platform domain cartridges."""

    _instance: Optional["ApplicationRegistry"] = None
    _lock = threading.Lock()

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        """Initialize ApplicationRegistry."""
        self.root_dir = root_dir or Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.apps_dir = self.root_dir / "apps"

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "ApplicationRegistry":
        """Thread-safe singleton accessor."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(root_dir=root_dir)
            return cls._instance

    def get_installed_applications(self) -> List[ApplicationInfo]:
        """Discover installed cartridges dynamically via PluginLoader and apps/ directory."""
        apps: List[ApplicationInfo] = []
        discovered_names: set[str] = set()

        # Deferred lookup from platform plugin_loader
        loaded_apps: Dict[str, Any] = {}
        descriptors: Dict[str, Any] = {}
        try:
            from core_platform.main import plugin_loader
            loaded_apps = plugin_loader.get_all_applications()
            descriptors = plugin_loader.discover_descriptors()
        except Exception:
            pass

        enabled_set = set(settings.ENABLED_APPLICATIONS) if settings.ENABLED_APPLICATIONS is not None else None

        # 1. From discovered descriptors (entry points & apps)
        for name, desc in descriptors.items():
            discovered_names.add(name)
            is_active = (name in enabled_set) if enabled_set is not None else True
            app_inst = loaded_apps.get(name)

            if app_inst is not None:
                title = getattr(app_inst, "name", name.replace("_", " ").title())
                description = getattr(app_inst, "description", f"Domain cartridge: {name}") or f"Domain cartridge: {name}"
                dashboard_url = getattr(app_inst, "dashboard_url", "") or f"/admin/apps/{name.replace('_', '-')}"
                has_poller = getattr(app_inst, "has_poller", False)
                poller_status = app_inst.get_poller_status() if has_poller else None
            else:
                title = name.replace("_", " ").title()
                description = f"Domain cartridge: {name}"
                dashboard_url = f"/admin/apps/{name.replace('_', '-')}"
                has_poller = False
                poller_status = None

            apps.append(
                ApplicationInfo(
                    app_name=name,
                    title=title,
                    description=description,
                    dashboard_url=dashboard_url,
                    is_active=is_active,
                    has_poller=has_poller,
                    poller_status=poller_status,
                )
            )

        # 2. From filesystem apps_dir (if any directories not captured in descriptors)
        if self.apps_dir.exists():
            for child in sorted(self.apps_dir.iterdir()):
                if child.is_dir() and not child.name.startswith(("_", ".")):
                    name = child.name
                    if name in discovered_names:
                        continue
                    discovered_names.add(name)
                    is_active = (name in enabled_set) if enabled_set is not None else True
                    app_inst = loaded_apps.get(name)

                    if app_inst is not None:
                        title = getattr(app_inst, "name", name.replace("_", " ").title())
                        description = getattr(app_inst, "description", f"Domain cartridge: {name}") or f"Domain cartridge: {name}"
                        dashboard_url = getattr(app_inst, "dashboard_url", "") or f"/admin/apps/{name.replace('_', '-')}"
                        has_poller = getattr(app_inst, "has_poller", False)
                        poller_status = app_inst.get_poller_status() if has_poller else None
                    else:
                        title = name.replace("_", " ").title()
                        description = f"Domain cartridge: {name}"
                        dashboard_url = f"/admin/apps/{name.replace('_', '-')}"
                        has_poller = False
                        poller_status = None

                    apps.append(
                        ApplicationInfo(
                            app_name=name,
                            title=title,
                            description=description,
                            dashboard_url=dashboard_url,
                            is_active=is_active,
                            has_poller=has_poller,
                            poller_status=poller_status,
                        )
                    )

        return apps

    def is_app_active(self, app_name: str) -> bool:
        """Check if a specific domain application is currently enabled."""
        if settings.ENABLED_APPLICATIONS is None:
            return True
        return app_name in settings.ENABLED_APPLICATIONS

    def enable_application(self, app_name: str) -> bool:
        """Dynamically enable an application."""
        with self._lock:
            if settings.ENABLED_APPLICATIONS is None:
                settings.ENABLED_APPLICATIONS = [a.app_name for a in self.get_installed_applications()]
            if app_name not in settings.ENABLED_APPLICATIONS:
                settings.ENABLED_APPLICATIONS.append(app_name)
                logger.info("[AppRegistry] Enabled application: %s", app_name)
                return True
            return False

    def disable_application(self, app_name: str) -> bool:
        """Dynamically disable an application."""
        with self._lock:
            if settings.ENABLED_APPLICATIONS is None:
                settings.ENABLED_APPLICATIONS = [a.app_name for a in self.get_installed_applications()]
            if app_name in settings.ENABLED_APPLICATIONS:
                settings.ENABLED_APPLICATIONS.remove(app_name)
                logger.info("[AppRegistry] Disabled application: %s", app_name)
                return True
            return False

    def get_summary(self) -> Dict[str, Any]:
        """Return structured summary for telemetry and UI status APIs."""
        installed = self.get_installed_applications()
        active = [a.app_name for a in installed if a.is_active]
        inactive = [a.app_name for a in installed if not a.is_active]
        return {
            "total_installed": len(installed),
            "active_count": len(active),
            "inactive_count": len(inactive),
            "active_apps": active,
            "inactive_apps": inactive,
            "applications": [a.to_dict() for a in installed],
        }
