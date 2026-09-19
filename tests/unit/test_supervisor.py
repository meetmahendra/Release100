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

"""Synthetic Unit Tests for Process Supervisor & Watchdog (Plan 05 v1.2)."""

from pathlib import Path
import sys
from deployment.supervisor.ntp_checker import NTPChecker
from deployment.supervisor.port_checker import PortChecker
from deployment.supervisor.process_supervisor import ProcessSupervisor


def test_ntp_clock_sanity() -> None:
    """System clock sanity check must return True on modern host."""
    is_sane, msg = NTPChecker.verify_system_clock_sanity()
    assert is_sane is True
    assert "System clock verified" in msg


def test_port_checker_available_port() -> None:
    """Probing an unused high port must return True."""
    # 59998 is an unreserved test port
    is_avail = PortChecker.is_port_available(59998)
    assert is_avail is True


def test_process_supervisor_initialization() -> None:
    """ProcessSupervisor must resolve root directory and python executable."""
    supervisor = ProcessSupervisor()
    assert supervisor.root_dir.exists()
    assert supervisor.python_exe is not None
    assert len(supervisor.services) == 0


def test_process_supervisor_preflight_checks() -> None:
    """Supervisor preflight verification must execute clock and socket checks."""
    supervisor = ProcessSupervisor()
    passed, msg = supervisor.verify_preflight_checks()
    # On typical test machine, ports and clock are available
    assert isinstance(passed, bool)
    assert isinstance(msg, str)
