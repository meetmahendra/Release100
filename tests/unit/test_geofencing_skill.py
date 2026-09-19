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

"""Synthetic Unit Tests for GeofencingSkill."""

import pytest
from core_platform.app.skills.geofencing import GeofencingSkill


@pytest.mark.asyncio
async def test_geofencing_skill_initialization() -> None:
    """GeofencingSkill must initialize cleanly and report available."""
    skill = GeofencingSkill()
    await skill.ensure_initialized()
    assert skill.is_available() is True
    health = skill.get_health_status()
    assert health["engine"] == "haversine_wgs84"


@pytest.mark.asyncio
async def test_geofencing_skill_distance_and_verification() -> None:
    """GeofencingSkill must accurately compute distance and verify within radius."""
    skill = GeofencingSkill()
    kiosk_coords = (18.5621, 73.9168)  # Phoenix Marketcity Pune
    near_coords = (18.5622, 73.9169)   # ~15 meters away
    far_coords = (18.5700, 73.9300)    # ~1.6 km away

    # Near verification
    is_within, dist = await skill.verify_geofence(near_coords, kiosk_coords, allowed_radius_meters=100.0)
    assert is_within is True
    assert dist <= 50.0

    # Far verification
    is_within_far, dist_far = await skill.verify_geofence(far_coords, kiosk_coords, allowed_radius_meters=100.0)
    assert is_within_far is False
    assert dist_far > 1000.0
