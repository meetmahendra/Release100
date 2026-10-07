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
Schema Definitions for Multi-Kiosk Fleet Knowledge Graph.

Adheres to Plan 03 v1.3. Models KioskNode kiosk machines, locations,
GPS geofences, and HACCP cold-chain temperature thresholds.
"""

from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class HACCPRule(BaseModel):
    """HACCP temperature safety limits for fresh juice chillers."""

    min_safe_temp: float = Field(default=2.0, description="Minimum safe chiller temp (Celsius)")
    max_safe_temp: float = Field(default=4.0, description="Maximum safe chiller temp (Celsius)")
    critical_alert_temp: float = Field(default=7.0, description="Immediate spoilage alert threshold")
    unit: str = Field(default="C", description="Temperature unit")


class LocationProfile(BaseModel):
    """Physical retail site profile where KioskNode machines operate."""

    site_id: str = Field(description="Unique location identifier, e.g. 'SITE-PUNE-PHOENIX'")
    site_name: str = Field(description="Display site name, e.g. 'Phoenix Marketcity Food Court'")
    city: str = Field(description="City of operation")
    latitude: float = Field(description="WGS-84 latitude coordinate")
    longitude: float = Field(description="WGS-84 longitude coordinate")
    geofence_radius_meters: float = Field(default=100.0, description="Permissible distance including indoor drift")


class KioskNodeMachineProfile(BaseModel):
    """Profile of a physical KioskNode machine unit deployed in the field."""

    kiosk_id: str = Field(description="Unique kiosk identifier, e.g. 'NODE-PUNE-04'")
    tenant_id: str = Field(default="public", description="Tenant workspace identifier")
    machine_model: str = Field(default="ChillerNode-Pro-Chilled", description="Machine model")
    display_type: str = Field(default="7_segment_led", description="Hardware display type")
    site_id: str = Field(description="Site reference identifier")
    primary_operator_phones: List[str] = Field(default_factory=list, description="Authorized operator phone numbers")
    is_active: bool = Field(default=True, description="Operational status flag")


class KioskFleetRoster(BaseModel):
    """Master fleet roster registry containing all organization kiosks and rules."""

    organization_name: str = Field(default="Apex Cold-Chain Logistics Ltd")
    default_haccp_rule: HACCPRule = Field(default_factory=HACCPRule)
    locations: Dict[str, LocationProfile] = Field(default_factory=dict)
    kiosks: Dict[str, KioskNodeMachineProfile] = Field(default_factory=dict)
