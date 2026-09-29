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

"""Unit tests for universal timezone utility."""

from datetime import datetime, timezone
from core_platform.app.common.timezone import to_local_ist, to_local_ist_full


def test_to_local_ist_none() -> None:
    """None datetime should return 'Today'."""
    assert to_local_ist(None) == "Today"


def test_to_local_ist_conversion() -> None:
    """UTC datetime should be converted to IST (+05:30)."""
    # 2026-09-20 07:00:00 UTC is 2026-09-20 12:30:00 PM IST
    dt_utc = datetime(2026, 9, 20, 7, 0, 0, tzinfo=timezone.utc)
    res = to_local_ist(dt_utc)
    assert res == "12:30 PM IST"


def test_to_local_ist_naive() -> None:
    """Naive datetime should be treated as UTC and converted to IST."""
    dt_naive = datetime(2026, 9, 20, 7, 0, 0)
    res = to_local_ist(dt_naive)
    assert res == "12:30 PM IST"


def test_to_local_ist_full() -> None:
    """Full IST date string check."""
    dt_utc = datetime(2026, 9, 20, 7, 0, 0, tzinfo=timezone.utc)
    res = to_local_ist_full(dt_utc)
    assert res == "2026-09-20 12:30:00 PM IST"
