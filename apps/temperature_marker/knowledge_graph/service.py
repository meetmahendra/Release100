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
Knowledge Graph Fleet Lookup Service.

Adheres strictly to Plan 03 v1.3. Provides query resolution for CaneBot
kiosk profiles, locations, geofences, HACCP rules, and operator phone mappings.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from apps.temperature_marker.knowledge_graph.schema import (
    CaneBotMachineProfile,
    HACCPRule,
    KioskFleetRoster,
    LocationProfile,
)


class KnowledgeGraphService:
    """Service managing multi-kiosk fleet topologies, rosters, and safety rules."""

    def __init__(self, roster_path: Optional[Path] = None) -> None:
        """Initialize KnowledgeGraphService.

        Args:
            roster_path: Optional path to JSON fleet roster file.
        """
        if roster_path is None:
            base = Path(os.path.dirname(os.path.abspath(__file__)))
            roster_path = base / "canebot_fleet_roster.json"

        self.roster_path = Path(roster_path)
        self.roster: KioskFleetRoster = self._load_roster()

    def _load_roster(self) -> KioskFleetRoster:
        """Load and parse fleet roster JSON file."""
        sample_path = self.roster_path.parent / "canebot_fleet_roster.sample.json"
        if not self.roster_path.exists():
            if sample_path.exists():
                with open(sample_path, "r", encoding="utf-8") as f:
                    return KioskFleetRoster.model_validate(json.load(f))
            return KioskFleetRoster()

        with open(self.roster_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            roster = KioskFleetRoster.model_validate(data)

        # Fail-safe: If roster file is empty (e.g. fresh retail checkout), fallback to sample
        if not roster.kiosks and sample_path.exists():
            with open(sample_path, "r", encoding="utf-8") as f:
                sample_data = json.load(f)
                return KioskFleetRoster.model_validate(sample_data)

        return roster

    def _save_roster(self) -> None:
        """Persist current fleet roster back to canebot_fleet_roster.json."""
        self.roster_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.roster_path, "w", encoding="utf-8") as f:
            f.write(self.roster.model_dump_json(indent=2))

    def get_kiosk_profile(self, kiosk_id: str) -> Optional[CaneBotMachineProfile]:
        """Retrieve hardware and operational profile for a given kiosk ID.

        Args:
            kiosk_id: Unique kiosk identifier (e.g. 'CANEBOT-PUNE-04').

        Returns:
            CaneBotMachineProfile if found, else None.
        """
        return self.roster.kiosks.get(kiosk_id)

    def get_location_for_kiosk(self, kiosk_id: str) -> Optional[LocationProfile]:
        """Retrieve registered location and GPS coordinates for a kiosk.

        Args:
            kiosk_id: Unique kiosk identifier.

        Returns:
            LocationProfile if found, else None.
        """
        kiosk = self.get_kiosk_profile(kiosk_id)
        if not kiosk:
            return None
        return self.roster.locations.get(kiosk.site_id)

    def get_kiosk_coordinates(self, kiosk_id: str) -> Optional[Tuple[float, float, float]]:
        """Retrieve (latitude, longitude, geofence_radius_meters) for a kiosk.

        Args:
            kiosk_id: Unique kiosk identifier.

        Returns:
            Tuple of (lat, lon, radius) if found, else None.
        """
        loc = self.get_location_for_kiosk(kiosk_id)
        if not loc:
            return None
        return (loc.latitude, loc.longitude, loc.geofence_radius_meters)

    def get_kiosk_by_id(self, kiosk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve resolved dictionary of kiosk profile and location coordinates.

        Args:
            kiosk_id: Unique kiosk identifier.

        Returns:
            Dictionary with kiosk metadata, latitude, and longitude, or None if not found.
        """
        profile = self.get_kiosk_profile(kiosk_id)
        if not profile:
            return None
        loc = self.roster.locations.get(profile.site_id)
        if not loc:
            return None
        return {
            "kiosk_id": profile.kiosk_id,
            "machine_model": profile.machine_model,
            "display_type": profile.display_type,
            "site_id": profile.site_id,
            "site_name": loc.site_name,
            "city": loc.city,
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "geofence_radius_meters": loc.geofence_radius_meters,
            "radius_meters": loc.geofence_radius_meters,
            "primary_operator_phones": profile.primary_operator_phones,
            "is_active": profile.is_active,
        }

    def get_haccp_limits(self, kiosk_id: Optional[str] = None) -> HACCPRule:
        """Retrieve HACCP chiller temperature thresholds governing a kiosk.

        Args:
            kiosk_id: Optional kiosk ID for machine-specific overrides.

        Returns:
            HACCPRule defining safe range (default 2°C to 4°C).
        """
        return self.roster.default_haccp_rule

    def resolve_kiosk_by_phone(self, phone_number: str) -> Optional[str]:
        """Resolve originating kiosk ID from operator WhatsApp phone number.

        Used by multi-kiosk Cloudflare relay and ingress router.

        Args:
            phone_number: Normalized E.164 phone number.

        Returns:
            Matched kiosk_id string, or None if unknown phone.
        """
        for kiosk_id, profile in self.roster.kiosks.items():
            if phone_number in profile.primary_operator_phones:
                return kiosk_id
        return None

    def assign_operator_to_kiosk(self, phone_number: str, kiosk_id: str) -> bool:
        """Assign or reassign an operator phone number to a specific kiosk in the roster.

        Args:
            phone_number: Normalized phone number.
            kiosk_id: Destination kiosk ID.

        Returns:
            True if assigned successfully, False if kiosk not found.
        """
        if kiosk_id not in self.roster.kiosks:
            return False

        # Remove from any existing kiosk
        for k_id, profile in self.roster.kiosks.items():
            if phone_number in profile.primary_operator_phones:
                profile.primary_operator_phones.remove(phone_number)

        # Add to target kiosk
        self.roster.kiosks[kiosk_id].primary_operator_phones.append(phone_number)
        self._save_roster()
        return True

    def update_kiosk_coordinates(
        self,
        kiosk_id: str,
        latitude: float,
        longitude: float,
        radius_meters: Optional[float] = None,
    ) -> bool:
        """Update live calibrated GPS coordinates for a kiosk's physical site."""
        kiosk = self.roster.kiosks.get(kiosk_id)
        if not kiosk:
            return False
        loc = self.roster.locations.get(kiosk.site_id)
        if not loc:
            return False
        loc.latitude = float(latitude)
        loc.longitude = float(longitude)
        if radius_meters is not None and radius_meters > 0:
            loc.geofence_radius_meters = float(radius_meters)
        self._save_roster()
        return True

    def add_kiosk(
        self,
        kiosk_id: str,
        site_name: str,
        city: str,
        latitude: float,
        longitude: float,
        radius_meters: float = 100.0,
        machine_model: str = "CaneBot-Pro-X1",
        display_type: str = "7-segment-led",
        primary_operator_phones: Optional[List[str]] = None,
    ) -> CaneBotMachineProfile:
        """Register a new CaneBot kiosk and its site location in the knowledge graph.

        Args:
            kiosk_id: Unique kiosk code (e.g. 'CANEBOT-HYD-01').
            site_name: Venue or mall name.
            city: City location.
            latitude: GPS latitude.
            longitude: GPS longitude.
            radius_meters: Geofence radius.
            machine_model: Hardware machine model.
            display_type: Display type.
            primary_operator_phones: Optional list of operator phones.

        Returns:
            The created CaneBotMachineProfile.
        """
        site_id = f"SITE-{city.upper()[:3]}-{kiosk_id[-2:]}"
        loc_profile = LocationProfile(
            site_id=site_id,
            site_name=site_name,
            city=city,
            latitude=latitude,
            longitude=longitude,
            geofence_radius_meters=radius_meters,
        )
        self.roster.locations[site_id] = loc_profile

        kiosk_profile = CaneBotMachineProfile(
            kiosk_id=kiosk_id,
            machine_model=machine_model,
            site_id=site_id,
            display_type=display_type,
            primary_operator_phones=primary_operator_phones or [],
            is_active=True,
        )
        self.roster.kiosks[kiosk_id] = kiosk_profile
        self._save_roster()
        return kiosk_profile

    def list_all_kiosks(self) -> List[Dict[str, Any]]:
        """List all kiosks in fleet with resolved location and profile metadata.

        Returns:
            List of dictionaries containing kiosk metadata and coordinates.
        """
        result: List[Dict[str, Any]] = []
        for kiosk_id, profile in self.roster.kiosks.items():
            loc = self.roster.locations.get(profile.site_id)
            result.append({
                "kiosk_id": kiosk_id,
                "name": loc.site_name if loc else kiosk_id,
                "city": loc.city if loc else "Unknown",
                "latitude": loc.latitude if loc else 0.0,
                "longitude": loc.longitude if loc else 0.0,
                "radius_meters": loc.geofence_radius_meters if loc else 100.0,
                "machine_model": profile.machine_model,
                "display_type": profile.display_type,
                "primary_operator_phones": profile.primary_operator_phones,
                "is_active": profile.is_active,
            })
        return result

    def get_kiosk_details(self, kiosk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a kiosk summary by ID.

        Args:
            kiosk_id: Unique kiosk identifier.

        Returns:
            Dictionary with kiosk details or None.
        """
        profile = self.get_kiosk_profile(kiosk_id)
        if not profile:
            return None
        loc = self.roster.locations.get(profile.site_id)
        return {
            "kiosk_id": kiosk_id,
            "name": loc.site_name if loc else kiosk_id,
            "city": loc.city if loc else "Unknown",
            "latitude": loc.latitude if loc else 0.0,
            "longitude": loc.longitude if loc else 0.0,
            "radius_meters": loc.geofence_radius_meters if loc else 100.0,
            "machine_model": profile.machine_model,
            "display_type": profile.display_type,
            "is_active": profile.is_active,
        }

    def find_kiosk(self, query: str) -> Optional[str]:
        """Fuzzy find a kiosk identifier by code, partial name, site name, or kiosk number.

        Args:
            query: User search string (e.g. '5', 'dassault', 'CANEBOT-PUNE-05', 'eka').

        Returns:
            Resolved kiosk_id string if found, else None.
        """
        q = query.strip()
        if not q:
            return None
        q_upper = q.upper()
        # 1. Exact ID match
        for k_id in self.roster.kiosks:
            if k_id.upper() == q_upper:
                return k_id

        # 2. Match trailing number (e.g. "5" -> "CANEBOT-PUNE-05")
        digits = "".join(c for c in q if c.isdigit())
        if digits:
            num = int(digits)
            for k_id in self.roster.kiosks:
                k_digits = "".join(c for c in k_id if c.isdigit())
                if k_digits and int(k_digits) == num:
                    return k_id

        # 3. Partial site name, city or ID match
        q_lower = q.lower()
        for kiosk_id, profile in self.roster.kiosks.items():
            if q_lower in kiosk_id.lower():
                return kiosk_id
            loc = self.roster.locations.get(profile.site_id)
            if loc:
                if q_lower in loc.site_name.lower() or q_lower in loc.city.lower():
                    return kiosk_id
        return None

    def find_nearest_kiosk(self, coords: Tuple[float, float]) -> Optional[Tuple[str, float]]:
        """Find the nearest kiosk to given GPS coordinates.

        Args:
            coords: (latitude, longitude) tuple.

        Returns:
            Tuple of (kiosk_id, distance_in_meters) or None if no kiosks registered.
        """
        import math
        lat, lon = coords
        best_id: Optional[str] = None
        min_dist = float("inf")
        r = 6371000.0

        for kiosk_id, profile in self.roster.kiosks.items():
            loc = self.roster.locations.get(profile.site_id)
            if not loc:
                continue
            phi1 = math.radians(lat)
            phi2 = math.radians(loc.latitude)
            delta_phi = math.radians(loc.latitude - lat)
            delta_lambda = math.radians(loc.longitude - lon)
            a = (
                math.sin(delta_phi / 2.0) ** 2
                + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
            )
            c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
            dist = r * c
            if dist < min_dist:
                min_dist = dist
                best_id = kiosk_id

        if best_id is not None:
            return (best_id, min_dist)
        return None

