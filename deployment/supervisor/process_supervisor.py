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
Pluggable Process Supervisor & Health Watchdog.

Adheres to Plan 05 v1.2 and elevated from AI-ProjectManager.
Manages the lifecycle of background services (Orchestrator Host, MCP Server,
Cloud Relay Client), enforcing clean tree terminations and /health polling.
"""

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from deployment.supervisor.ntp_checker import NTPChecker
from deployment.supervisor.port_checker import PortChecker


class ProcessSupervisor:
    """Watchdog and lifecycle manager for all Release100 background services."""

    CREATE_NO_WINDOW: int = 0x08000000 if sys.platform == "win32" else 0

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        """Initialize ProcessSupervisor.

        Args:
            root_dir: Root directory of Release100 repository.
        """
        self.root_dir = Path(root_dir or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.services: Dict[str, subprocess.Popen[Any]] = {}
        self.is_frozen: bool = getattr(sys, "frozen", False)
        self.python_exe: str = self._resolve_python_executable()

    def _resolve_python_executable(self) -> str:
        """Resolve python executable path for dev vs frozen installer mode."""
        if self.is_frozen:
            return sys.executable

        # Check local virtualenv
        venv_scripts = self.root_dir / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
        venv_py = venv_scripts / ("python.exe" if sys.platform == "win32" else "python")
        if venv_py.exists():
            return str(venv_py)

        return sys.executable

    def start_service(self, name: str, cmd: List[str], cwd: Optional[Path] = None) -> subprocess.Popen[Any]:
        """Spawn a managed background child service with window suppression on Windows.

        Args:
            name: Friendly service name identifier.
            cmd: Command line argument list.
            cwd: Optional working directory.

        Returns:
            Popen child process instance.
        """
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        target_cwd = str(cwd or self.root_dir)

        creationflags = self.CREATE_NO_WINDOW

        proc = subprocess.Popen(
            cmd,
            cwd=target_cwd,
            env=env,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.services[name] = proc
        return proc

    def stop_service(self, name: str) -> None:
        """Terminate a specific service and its child process tree cleanly.

        Args:
            name: Service identifier.
        """
        proc = self.services.get(name)
        if not proc or proc.poll() is not None:
            return

        try:
            if sys.platform == "win32":
                # Windows taskkill /F /T kills the whole process tree cleanly
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    creationflags=self.CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                proc.terminate()
                proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            self.services.pop(name, None)

    def start_poll_worker(self) -> bool:
        """Start the Mail Organizer background poller with supervised lifecycle."""
        try:
            from apps.mail_organizer.services.poller_manager import MailPollerManager
            return MailPollerManager.get_instance(root_dir=self.root_dir).start()
        except Exception as exc:
            return False

    def stop_poll_worker(self) -> bool:
        """Completely stop the Mail Organizer poller with guaranteed zero zombies (ISSUE-005)."""
        try:
            from apps.mail_organizer.services.poller_manager import MailPollerManager
            return MailPollerManager.get_instance(root_dir=self.root_dir).stop()
        except Exception as exc:
            return False

    def is_poll_worker_running(self) -> bool:
        """Check if the Mail Organizer poller is actively running."""
        try:
            from apps.mail_organizer.services.poller_manager import MailPollerManager
            return MailPollerManager.get_instance(root_dir=self.root_dir).is_running()
        except Exception:
            return False

    def stop_all(self) -> None:
        """Stop all running child services and poller cleanly."""
        self.stop_poll_worker()
        for name in list(self.services.keys()):
            self.stop_service(name)

    def verify_preflight_checks(self) -> Tuple[bool, str]:
        """Execute boot-time preflight checks (NTP clock sync & TCP port availability).

        Returns:
            Tuple of (passed: bool, message: str).
        """
        # 1. Verify NTP clock sanity
        clock_ok, clock_msg = NTPChecker.verify_system_clock_sanity()
        if not clock_ok:
            return False, f"Preflight check failed: {clock_msg}"

        # 2. Verify Port availability
        ports_ok, ports_msg = PortChecker.verify_platform_ports()
        if not ports_ok:
            return False, f"Preflight check failed: {ports_msg}"

        return True, "All preflight checks passed (Clock synchronized & ports available)."

    def get_service_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Return process health and PID information for all managed services.

        Returns:
            Dictionary mapping service name to status dict.
        """
        statuses = {}
        for name, proc in self.services.items():
            is_running = proc.poll() is None
            statuses[name] = {
                "pid": proc.pid if is_running else None,
                "running": is_running,
                "exit_code": proc.poll() if not is_running else None,
            }
        return statuses
