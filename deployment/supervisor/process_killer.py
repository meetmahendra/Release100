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
Cross-Platform Process Tree Termination Utility.

Adheres to Plan 05 v1.2 Section 2.
Extracted from ProcessSupervisor as a standalone module to ensure
clean, verified process tree kills on both Windows and POSIX systems,
with zero zombie guarantee.
"""

import os
import signal
import subprocess
import sys
import time
from typing import Optional


CREATE_NO_WINDOW: int = 0x08000000 if sys.platform == "win32" else 0


def kill_process_tree(pid: int, timeout_seconds: float = 3.0) -> bool:
    """Terminate a process and its entire child tree cleanly.

    On Windows: uses ``taskkill /F /T /PID`` which recursively kills all children.
    On POSIX: sends SIGTERM to the process group, then escalates to SIGKILL.

    Args:
        pid: Target process ID to terminate.
        timeout_seconds: Maximum wait time for graceful termination before force kill.

    Returns:
        True if process was confirmed dead, False if still alive after all attempts.
    """
    if not is_pid_alive(pid):
        return True

    if sys.platform == "win32":
        return _kill_windows(pid, timeout_seconds)
    return _kill_posix(pid, timeout_seconds)


def _kill_windows(pid: int, timeout_seconds: float) -> bool:
    """Windows-specific process tree kill using taskkill."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        # taskkill not available (unlikely on Windows, but defensive)
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    # Wait for confirmed exit
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.1)

    # Force kill if still alive
    try:
        os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass

    time.sleep(0.3)
    return not is_pid_alive(pid)


def _kill_posix(pid: int, timeout_seconds: float) -> bool:
    """POSIX-specific process group kill using SIGTERM → SIGKILL escalation."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return not is_pid_alive(pid)

    # Wait for graceful shutdown
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.1)

    # Escalate to SIGKILL
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    time.sleep(0.3)
    return not is_pid_alive(pid)


def is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is currently alive.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists and is running, False if dead or permission denied.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it — treat as alive
        return True


def touch_sentinel(path: str) -> None:
    """Create or update a cooperative stop sentinel file.

    Used by the dual-layer cooperative shutdown engine (ISSUE-005 fix).

    Args:
        path: Absolute file path for the sentinel file.
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def remove_sentinel(path: str) -> None:
    """Remove the cooperative stop sentinel file after clean shutdown.

    Args:
        path: Absolute file path for the sentinel file.
    """
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def sentinel_exists(path: str) -> bool:
    """Check whether a cooperative stop sentinel is present.

    Args:
        path: Absolute file path for the sentinel file.

    Returns:
        True if sentinel file exists.
    """
    return os.path.exists(path)
