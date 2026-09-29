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

"""Universal Timezone & DateTime Formatting Utility for Release100 Platform.

Ensures strict GEES v1.0 and regulatory compliance (FDA 21 CFR Part 11).
Stores all timestamps internally in ISO UTC while formatting user-facing strings
in local Indian Standard Time (IST, UTC+05:30).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

IST_TZ = timezone(timedelta(hours=5, minutes=30), name="IST")


def to_local_ist(dt: Optional[datetime], fmt: str = "%I:%M %p IST") -> str:
    """Format UTC datetime into readable Indian Standard Time (IST).

    Args:
        dt: Naive or timezone-aware datetime (assumed UTC if naive).
        fmt: strftime format string (defaults to '%I:%M %p IST', e.g. '06:30 PM IST').

    Returns:
        Formatted IST timestamp string, or 'Today' if dt is None.
    """
    if not dt:
        return "Today"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST_TZ).strftime(fmt)


def to_local_ist_full(dt: Optional[datetime]) -> str:
    """Format UTC datetime into full date and time string in IST."""
    return to_local_ist(dt, fmt="%Y-%m-%d %I:%M:%S %p IST")
