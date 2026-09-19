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
Mail Poller Lifecycle Supervisor & Process Manager.

Adheres to Plan 07 v1.0 and GEES v1.0.
Guarantees clean, zero-zombie shutdown of the Mail Organizer background worker
using cooperative sentinels and verified process tree termination (resolving ISSUE-005).
"""

import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

from apps.mail_organizer.services.poll_worker import (
    MailPollWorker,
    get_sentinel_path,
)

logger = logging.getLogger("mail_organizer.poller_manager")


class MailPollerManager:
    """Singleton lifecycle manager for the Mail Organizer poller."""

    _instance: Optional["MailPollerManager"] = None
    _lock = threading.Lock()

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        """Initialize poller manager."""
        self.root_dir = root_dir or Path(os.getcwd())
        self.sentinel_path = get_sentinel_path(self.root_dir)
        self._worker: Optional[MailPollWorker] = None
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen[Any]] = None

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "MailPollerManager":
        """Thread-safe singleton accessor."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(root_dir=root_dir)
            return cls._instance

    def is_running(self) -> bool:
        """Verify whether the poller is actively running."""
        # 1. Check in-process thread
        if self._thread and self._thread.is_alive():
            if self._worker and self._worker.stop_event.is_set():
                return False
            return True

        # 2. Check subprocess
        if self._proc is not None:
            if self._proc.poll() is None:
                return True
            self._proc = None

        return False

    def start(self, poll_interval_seconds: int = 30) -> bool:
        """Start the background poller worker in a dedicated daemon thread."""
        with self._lock:
            if self.is_running():
                logger.warning("[PollerManager] Poller is already running.")
                return True

            # Ensure sentinel is cleaned up before start
            if self.sentinel_path.exists():
                try:
                    self.sentinel_path.unlink()
                except Exception:
                    pass

            self._worker = MailPollWorker(
                poll_interval_seconds=poll_interval_seconds,
                root_dir=self.root_dir,
            )
            self._worker._is_running = True
            self._thread = threading.Thread(
                target=self._worker.run,
                name="MailPollWorkerThread",
                daemon=True,
            )
            self._thread.start()
            for _ in range(20):
                if self._thread.is_alive():
                    break
                time.sleep(0.01)

            logger.info("[PollerManager] Mail poller thread started successfully.")
            return True

    def stop(self, timeout: float = 3.0) -> bool:
        """Completely stop the poller with verified termination (Resolving ISSUE-005)."""
        with self._lock:
            logger.info("[PollerManager] Initiating complete poller shutdown...")

            # 1. Trigger in-memory cooperative stop
            if self._worker:
                self._worker.request_stop()

            # 2. Touch atomic sentinel file to alert any sleeping subprocesses
            try:
                self.sentinel_path.touch(exist_ok=True)
            except Exception as err:
                logger.warning("[PollerManager] Could not touch sentinel file: %s", err)

            # 3. Terminate subprocess if active
            if self._proc and self._proc.poll() is None:
                pid = self._proc.pid
                logger.info("[PollerManager] Terminating poller subprocess (PID: %d)...", pid)
                try:
                    if sys.platform == "win32":
                        # Tree kill on Windows
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=0x08000000,
                            check=False,
                        )
                    else:
                        self._proc.terminate()

                    self._proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    logger.warning("[PollerManager] Subprocess PID %d did not terminate in time. Killing forcefully.", pid)
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                except Exception as exc:
                    logger.error("[PollerManager] Error terminating subprocess: %s", exc)
                finally:
                    self._proc = None

            # 4. Await in-process thread termination
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout)
                if self._thread.is_alive():
                    logger.warning("[PollerManager] In-process worker thread did not join within timeout.")

            self._worker = None
            self._thread = None

            # 5. Clean up sentinel
            try:
                if self.sentinel_path.exists():
                    self.sentinel_path.unlink()
            except Exception:
                pass

            # 6. Final verification
            running = self.is_running()
            if not running:
                logger.info("[PollerManager] Mail poller has shut down completely and cleanly (0 zombies).")
                return True
            else:
                logger.error("[PollerManager] CRITICAL: Poller is still reporting running after stop!")
                return False

    def toggle(self) -> bool:
        """Toggle poller state (start if stopped, stop if running)."""
        if self.is_running():
            self.stop()
            return False
        else:
            self.start()
            return True

    def get_status(self) -> Dict[str, Any]:
        """Return real-time status dictionary."""
        running = self.is_running()
        return {
            "is_running": running,
            "status": "RUNNING" if running else "STOPPED",
            "cycles_completed": self._worker.cycles_completed if self._worker else 0,
            "emails_processed": self._worker.emails_processed if self._worker else 0,
            "sentinel_active": self.sentinel_path.exists(),
        }
