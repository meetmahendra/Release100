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
Geofencing Cognitive Skill (`GeofencingSkill`).

Adheres strictly to GEES v1.0 (Pillar 5) and Plan 02 v1.3.
Provides high-precision Haversine mathematical distance validation
and geofence checking against registered retail kiosk coordinates.
"""

import math
from typing import Any, Dict, Optional, Tuple

from core_platform.app.skills.base import BaseSkill


class GeofencingSkill(BaseSkill):
    """High-precision GPS distance and geofence verification skill."""

    EARTH_RADIUS_METERS: float = 6371000.0  # WGS-84 mean radius

    def __init__(self) -> None:
        """Initialize the GeofencingSkill."""
        super().__init__(skill_name="geofencing")

    async def initialize(self) -> None:
        """Initialize mathematical geofence engine."""
        # Pure mathematical engine, immediately ready
        self._initialized = True

    def is_available(self) -> bool:
        """Report availability of the GeofencingSkill."""
        return True

    def calculate_distance_meters(
        self,
        coord_a: Tuple[float, float],
        coord_b: Tuple[float, float],
    ) -> float:
        """Calculate great-circle distance between two GPS coordinates using Haversine formula.

        Args:
            coord_a: (latitude, longitude) of point A.
            coord_b: (latitude, longitude) of point B.

        Returns:
            Distance in meters as float.
        """
        lat1, lon1 = coord_a
        lat2, lon2 = coord_b

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return self.EARTH_RADIUS_METERS * c

    async def verify_geofence(
        self,
        user_coords: Tuple[float, float],
        kiosk_coords: Tuple[float, float],
        allowed_radius_meters: float = 100.0,
        accuracy_meters: float = 0.0,
    ) -> Tuple[bool, float]:
        """Verify whether a user coordinate is within the permitted geofence of a kiosk.

        Args:
            user_coords: (lat, lon) reported by user smartphone HTML5 GPS.
            kiosk_coords: (lat, lon) registered physical kiosk coordinates.
            allowed_radius_meters: Maximum allowed radius (e.g. 50m base or 100m indoor).
            accuracy_meters: Device GPS reported horizontal accuracy tolerance radius.

        Returns:
            Tuple of (is_within_fence: bool, distance_meters: float).
        """
        await self.ensure_initialized()
        raw_distance = self.calculate_distance_meters(user_coords, kiosk_coords)
        # Bounded allowance for device horizontal accuracy error radius
        effective_tolerance = min(max(0.0, accuracy_meters), 150.0)
        effective_distance = max(0.0, raw_distance - effective_tolerance)
        is_within = effective_distance <= allowed_radius_meters
        return is_within, round(raw_distance, 2)

    def verify_proximity(
        self,
        user_lat: float,
        user_lon: float,
        target_lat: float,
        target_lon: float,
        radius_meters: float = 100.0,
    ) -> Tuple[bool, float]:
        """Verify if (user_lat, user_lon) is within radius_meters of target."""
        dist = self.calculate_distance_meters((user_lat, user_lon), (target_lat, target_lon))
        return dist <= radius_meters, dist

    def get_health_status(self) -> Dict[str, Any]:
        """Return operational metadata for health heartbeat."""
        status = super().get_health_status()
        status["engine"] = "haversine_wgs84"
        return status


_geofencer_singleton: Optional[GeofencingSkill] = None


def get_platform_geofencer() -> GeofencingSkill:
    """Return singleton instance of GeofencingSkill."""
    global _geofencer_singleton
    if _geofencer_singleton is None:
        _geofencer_singleton = GeofencingSkill()
    return _geofencer_singleton
