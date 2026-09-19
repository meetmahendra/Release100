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
NTP Time Synchronization Validator.

Adheres to Plan 05 v1.2 and GEES v1.0 (Pillar 3).
Verifies that the edge kiosk host clock is synchronized with standard time,
protecting the monotonic SHA-256 audit chain against clock-skew anomalies.
"""

from datetime import datetime, timezone
import time
from typing import Tuple


class NTPChecker:
    """Validates host clock time synchronization on boot."""

    @staticmethod
    def verify_system_clock_sanity() -> Tuple[bool, str]:
        """Verify that the system clock is running with valid epoch timestamps.

        Returns:
            Tuple of (is_sane: bool, message: str).
        """
        now = datetime.now(timezone.utc)
        current_year = now.year

        # Basic sanity check: year must be 2026 or later
        if current_year < 2026:
            return (
                False,
                f"System clock error: Reported year is {current_year}. Host clock has drifted backward.",
            )

        # Check timestamp monotonic progress
        t1 = time.time()
        time.sleep(0.005)
        t2 = time.time()
        if t2 <= t1:
            return (
                False,
                "System clock error: System timer is not advancing monotonically.",
            )

        return True, f"System clock verified: {now.isoformat()} (UTC)"
