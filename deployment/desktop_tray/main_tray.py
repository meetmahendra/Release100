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
Dynamic Windows System Tray Application (`main_tray.py`).

Adheres strictly to Plan 05 v1.2 and GEES v1.0.
Provides:
1. Dynamic context menu bound to runtime settings and kiosk state.
2. 1-Click browser dashboard navigation.
3. 1-Click Desktop audit package exporter.
4. Clean, graceful platform shutdown.
"""

import os
import pathlib
from typing import Any, Callable, Optional
import webbrowser
import threading
import time

from core_platform.app.apps_registry import ApplicationRegistry
from core_platform.app.config import settings
from deployment.desktop_tray.exporter import AuditExporter

try:
    from PIL import Image, ImageDraw
    import pystray  # type: ignore[import-untyped]
    _HAS_TRAY = True
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    pystray = None
    _HAS_TRAY = False

# Resolved path to the packaged tray icon assets directory.
_ASSETS_DIR: pathlib.Path = pathlib.Path(__file__).parent / "assets"


class DesktopTrayApp:
    """Windows Notification Area System Tray Controller."""

    def __init__(self, on_shutdown: Optional[Callable[[], None]] = None) -> None:
        """Initialize DesktopTrayApp with dynamic context menu.

        Args:
            on_shutdown: Callback executed during clean exit.
        """
        self.on_shutdown = on_shutdown
        self.icon: Any = None
        self.exporter = AuditExporter()
        self._watcher_thread: Optional[threading.Thread] = None
        self._running = True
        self._stop_event = threading.Event()

    def _load_icon_image(self, state: str = "green") -> Any:
        """Load tray icon from assets/ directory with in-memory fallback.

        Attempts to open the pre-rendered ICO file from the bundled assets directory.
        If the file is missing or PIL is unavailable, falls back to programmatic
        generation via ``_create_default_icon_image``.

        Args:
            state: Icon colour state — ``"green"`` (healthy), ``"red"`` (error),
                   or ``"orange"`` (warning/pending).

        Returns:
            PIL Image object or ``None`` if tray libraries are unavailable.
        """
        if not _HAS_TRAY or Image is None:
            return None

        icon_filename = f"icon_{state}.ico"
        icon_path = _ASSETS_DIR / icon_filename
        if icon_path.is_file():
            try:
                loaded: Any = Image.open(str(icon_path))
                # Convert to RGBA for pystray compatibility
                return loaded.convert("RGBA")
            except Exception as exc:
                print(f"[TrayApp] Warning: could not load {icon_path}: {exc}. Using generated icon.")

        # Fallback: programmatically generated icon
        color_map = {"green": "#10b981", "red": "#ef4444", "orange": "#f59e0b"}
        return self._create_default_icon_image(color=color_map.get(state, "#10b981"))

    def _create_default_icon_image(self, color: str = "#10b981") -> Any:
        """Generate a clean 64x64 RGBA status icon in-memory without external files."""
        if not _HAS_TRAY or Image is None or ImageDraw is None:
            return None
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        # Outer ring
        draw.ellipse((4, 4, 60, 60), fill=color, outline="#065f46", width=2)
        # Inner white indicator
        draw.ellipse((20, 20, 44, 44), fill="white")
        return image

    def open_settings(self) -> None:
        """Open Live Settings & Diagnostics Console in default web browser."""
        url = f"http://localhost:{settings.ORCHESTRATOR_PORT}/settings"
        webbrowser.open(url)

    def open_dashboard(self) -> None:
        """Open Central Admin Dashboard in default desktop web browser."""
        dashboard_url = f"http://localhost:{settings.ORCHESTRATOR_PORT}/admin/apps/temperature-marker/fleet"
        webbrowser.open(dashboard_url)

    def open_temp_dashboard(self) -> None:
        """Open Temperature Marker Fleet Dashboard in web browser."""
        url = f"http://localhost:{settings.ORCHESTRATOR_PORT}/admin/apps/temperature-marker/fleet"
        webbrowser.open(url)

    def open_mail_dashboard(self) -> None:
        """Open Mail Organizer Dashboard in web browser."""
        url = f"http://localhost:{settings.ORCHESTRATOR_PORT}/admin/apps/mail-organizer/dashboard"
        webbrowser.open(url)

    def open_audit_dashboard(self) -> None:
        """Open Visual HTML Audit Report."""
        url = f"http://localhost:{settings.ORCHESTRATOR_PORT}/health"
        webbrowser.open(url)

    def is_app_active(self, app_name: str) -> bool:
        """Check whether a domain cartridge is currently enabled."""
        return ApplicationRegistry.get_instance().is_app_active(app_name)

    def is_poller_running(self) -> bool:
        """Check whether the Mail Organizer background poller is running."""
        try:
            from apps.mail_organizer.services.poller_manager import MailPollerManager
            return MailPollerManager.get_instance().is_running()
        except Exception:
            return False

    def on_toggle_poller(self, icon: Any, item: Any) -> None:
        """Toggle background email poller with verified clean shutdown."""
        try:
            from apps.mail_organizer.services.poller_manager import MailPollerManager
            mgr = MailPollerManager.get_instance()
            is_now_running = mgr.toggle()
            msg = "Mail Poller is now ACTIVE." if is_now_running else "Mail Poller was STOPPED cleanly (0 zombies)."
            if self.icon:
                try:
                    self.icon.notify(msg, "Release100")
                except Exception:
                    pass
                # Update menu immediately to reflect checkmark (resolving ISSUE-006)
                try:
                    self.icon.update_menu()
                except Exception:
                    pass
        except Exception as err:
            print(f"[TrayApp] Error toggling poller: {err}")

    def trigger_export(self) -> None:
        """Export compliance audit package to desktop."""
        success, msg, count = self.exporter.export()
        if success:
            print(f"[TrayApp] Exported {count} audit files: {msg}")
            if self.icon:
                try:
                    self.icon.notify(f"Audit package exported to Desktop ({count} files).", "Release100 Audit")
                except Exception:
                    pass
        else:
            print(f"[TrayApp] Export error: {msg}")

    def exit_application(self) -> None:
        """Gracefully stop background services and terminate tray loop."""
        print("[TrayApp] Initiating shutdown sequence...")
        self._running = False
        self._stop_event.set()
        try:
            from apps.mail_organizer.services.poller_manager import MailPollerManager
            MailPollerManager.get_instance().stop()
        except Exception:
            pass

        if self.on_shutdown:
            self.on_shutdown()
        if self.icon is not None:
            self.icon.stop()

    def build_menu(self) -> Any:
        """Construct dynamic context menu based on live platform settings and apps."""
        if not _HAS_TRAY or pystray is None:
            return None

        # Build dynamic application menu items
        menu_items = [
            pystray.MenuItem("⚙️ Live Settings & Testing Console", lambda _: self.open_settings(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Station: {settings.STATION_NAME} ({settings.KIOSK_ID})", None, enabled=False),
            pystray.MenuItem("Active Applications:", None, enabled=False),
            pystray.MenuItem(
                "  ● Temperature Marker (Active)",
                lambda _: self.open_temp_dashboard(),
                visible=lambda _: self.is_app_active("temperature_marker"),
            ),
            pystray.MenuItem(
                "  ● Mail Organizer (Active)",
                lambda _: self.open_mail_dashboard(),
                visible=lambda _: self.is_app_active("mail_organizer"),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Mail Poller (Background Ingestion)",
                self.on_toggle_poller,
                checked=lambda item: self.is_poller_running(),
                visible=lambda _: self.is_app_active("mail_organizer"),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📊 Visual Health Telemetry (API)", lambda _: self.open_audit_dashboard()),
            pystray.MenuItem("📦 1-Click Export Audit Package (ZIP)", lambda _: self.trigger_export()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Shutdown Release100 & Exit", lambda _: self.exit_application()),
        ]

        return pystray.Menu(*menu_items)

    def _menu_watchdog_loop(self) -> None:
        """Periodically refresh menu checkmarks and active application state."""
        while not self._stop_event.wait(5.0):
            if self.icon:
                try:
                    self.icon.update_menu()
                except Exception:
                    pass

    def run(self) -> None:
        """Launch the system tray event loop."""
        if not _HAS_TRAY or pystray is None:
            print("[TrayApp] pystray / PIL not installed. Running in headless notification mode.")
            return

        image = self._load_icon_image(state="green")
        menu = self.build_menu()
        self.icon = pystray.Icon(
            name="Release100",
            icon=image,
            title=f"Release100 - {settings.STATION_NAME}",
            menu=menu,
        )

        # Start background watchdog to keep menu checkmarks fresh
        self._watcher_thread = threading.Thread(target=self._menu_watchdog_loop, daemon=True)
        self._watcher_thread.start()

        print("[TrayApp] System tray icon initialized with live diagnostics & application monitoring.")
        self.icon.run()
