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
TCP Port Scanner and Socket Availability Checker.

Adheres to Plan 05 v1.2. Validates port availability before launching services.
"""

import socket
from typing import Tuple


class PortChecker:
    """Utility for probing TCP socket states and port collisions."""

    @staticmethod
    def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
        """Check whether a TCP port is open and available for binding.

        Args:
            port: Port number to probe.
            host: Host IP address.

        Returns:
            True if available for binding, False if already occupied.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.bind((host, port))
                return True
            except (socket.error, OSError):
                return False

    @classmethod
    def verify_platform_ports(cls) -> Tuple[bool, str]:
        """Verify that Core Orchestrator (:8002) and MCP (:8001) ports are available.

        Returns:
            Tuple of (all_available: bool, status_message: str).
        """
        ports = [8002, 8001]
        busy = [p for p in ports if not cls.is_port_available(p)]
        if busy:
            return False, f"Port collision detected: Port(s) {busy} are already in use."
        return True, "Platform ports :8002 and :8001 are clear for binding."
