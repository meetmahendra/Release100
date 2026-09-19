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
Layer 0: Deterministic Pre-Execution Gate.

Adheres strictly to GEES v1.0 (Pillar 1) and Plan 02 v1.3.
Executes purely deterministic Python code BEFORE any AI model invocation:
1. Physical sensor sanity bounding (rejects physically impossible readings).
2. Hardware & GPS geofencing validation (Haversine distance limits).
3. Input sanitization (script/injection stripping).
4. Per-sender rate limiting.
"""

import math
import re
from typing import Dict, Optional, Tuple

from core_platform.app.errors import PlatformErrorCode, SafetyGateViolation


class Layer0PreExecutionGate:
    """Deterministic Pre-Execution Safety Gate (Layer 0)."""

    @staticmethod
    def validate_physical_temperature_bounds(
        temperature_c: float,
        min_physical: float = -20.0,
        max_physical: float = 120.0,
    ) -> bool:
        """Verify that a temperature value is within physically possible sensor bounds.

        Prevents model hallucination or corrupted sensor OCR from logging impossible
        values (e.g., negative values for an ambient line or readings exceeding 120°C).

        Args:
            temperature_c: Temperature reading in Celsius.
            min_physical: Absolute lower physical boundary.
            max_physical: Absolute upper physical boundary.

        Returns:
            True if reading is within bounds.

        Raises:
            SafetyGateViolation: If temperature violates physical reality.
        """
        if math.isnan(temperature_c) or math.isinf(temperature_c):
            raise SafetyGateViolation(
                message=f"Invalid temperature value: {temperature_c}",
                code=PlatformErrorCode.SAFETY_PHYSICAL_BOUND_VIOLATION,
                context={"temperature_c": str(temperature_c)},
            )

        if not (min_physical <= temperature_c <= max_physical):
            raise SafetyGateViolation(
                message=(
                    f"Temperature {temperature_c}°C violates physical sensor boundaries "
                    f"[{min_physical}°C, {max_physical}°C]"
                ),
                code=PlatformErrorCode.SAFETY_PHYSICAL_BOUND_VIOLATION,
                context={
                    "temperature_c": temperature_c,
                    "min_physical": min_physical,
                    "max_physical": max_physical,
                },
            )
        return True

    @staticmethod
    def calculate_haversine_distance_meters(
        coord_a: Tuple[float, float],
        coord_b: Tuple[float, float],
    ) -> float:
        """Calculate great-circle distance between two GPS coordinates using Haversine formula.

        Args:
            coord_a: (latitude, longitude) of point A.
            coord_b: (latitude, longitude) of point B.

        Returns:
            Distance in meters.
        """
        lat1, lon1 = coord_a
        lat2, lon2 = coord_b
        earth_radius_m = 6371000.0  # WGS-84 mean radius

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return earth_radius_m * c

    @classmethod
    def validate_geofence(
        cls,
        user_coords: Tuple[float, float],
        kiosk_coords: Tuple[float, float],
        max_radius_meters: float = 100.0,
    ) -> Tuple[bool, float]:
        """Verify that user coordinates are within permissible kiosk geofence radius.

        Args:
            user_coords: (lat, lon) reported by user smartphone HTML5 GPS.
            kiosk_coords: (lat, lon) target registered physical kiosk coordinates.
            max_radius_meters: Maximum allowed distance including indoor tolerance.

        Returns:
            Tuple of (is_within_fence: bool, distance_meters: float).

        Raises:
            SafetyGateViolation: If user is outside the permitted geofence.
        """
        distance_meters = cls.calculate_haversine_distance_meters(user_coords, kiosk_coords)
        if distance_meters > max_radius_meters:
            raise SafetyGateViolation(
                message=(
                    f"Geofence breach: User is {distance_meters:.1f}m away from kiosk. "
                    f"Maximum permissible radius is {max_radius_meters:.1f}m."
                ),
                code=PlatformErrorCode.SAFETY_GEOFENCE_VIOLATION,
                context={
                    "distance_meters": round(distance_meters, 2),
                    "max_radius_meters": max_radius_meters,
                    "user_coords": user_coords,
                    "kiosk_coords": kiosk_coords,
                },
            )
        return True, distance_meters

    @staticmethod
    def sanitize_input_text(text: Optional[str]) -> str:
        """Strip dangerous script tags and potential prompt injection wrappers.

        Args:
            text: Raw input text.

        Returns:
            Clean sanitized text.
        """
        if not text:
            return ""
        # Remove complete script and style blocks including contents
        clean = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r"<style.*?>.*?</style>", "", clean, flags=re.DOTALL | re.IGNORECASE)
        # Remove any remaining HTML/XML tags
        clean = re.sub(r"<[^>]*>", "", clean)
        # Strip null bytes and non-printable control chars
        clean = "".join(ch for ch in clean if ord(ch) >= 32 or ch in "\n\r\t")
        return clean.strip()
