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

"""Synthetic Unit Tests for Multi-Kiosk Fleet Knowledge Graph."""

from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService


def test_knowledge_graph_service_loading() -> None:
    """KnowledgeGraphService must load default KioskNode fleet roster."""
    service = KnowledgeGraphService()
    assert len(service.roster.kiosks) >= 3
    assert "NODE-PUNE-04" in service.roster.kiosks
    assert "NODE-MUMBAI-08" in service.roster.kiosks


def test_knowledge_graph_coordinates_lookup() -> None:
    """Coordinates lookup must return latitude, longitude, and geofence radius."""
    service = KnowledgeGraphService()
    geo = service.get_kiosk_coordinates("NODE-PUNE-04")
    assert geo is not None
    lat, lon, radius = geo
    assert lat == 18.5621
    assert lon == 73.9168
    assert radius == 300.0


def test_knowledge_graph_haccp_limits() -> None:
    """HACCP rules must define KioskNode safe range 2.0C - 4.0C with critical 7.0C."""
    service = KnowledgeGraphService()
    haccp = service.get_haccp_limits("NODE-PUNE-04")
    assert haccp.min_safe_temp == 2.0
    assert haccp.max_safe_temp == 4.0
    assert haccp.critical_alert_temp == 7.0


def test_knowledge_graph_resolve_phone_to_kiosk() -> None:
    """Phone number mapping must resolve to correct physical kiosk."""
    service = KnowledgeGraphService()
    kiosk_id = service.resolve_kiosk_by_phone("+919800011122")
    assert kiosk_id == "NODE-PUNE-04"

    unknown = service.resolve_kiosk_by_phone("+910000000000")
    assert unknown is None
