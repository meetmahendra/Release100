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

"""Synthetic Unit Tests for Geolocation Prompt Rate Limiter (Phase 2)."""

import pytest
from starlette.testclient import TestClient

from apps.temperature_marker.graph.nodes.layer0_location_node import layer0_location_node
from apps.temperature_marker.graph.state import TemperatureMarkerState
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService
from core_platform.app.ingress.location_session import (
    record_location_prompt,
    reset_prompt_dates,
    should_prompt_location,
)
from core_platform.main import app

client = TestClient(app)


def test_location_rate_limiter_logic() -> None:
    """Rate limiter allows 1 prompt per day unless explicitly requested."""
    reset_prompt_dates()
    phone = "+919876543210"

    # 1. First check of the day -> Allowed
    assert should_prompt_location(phone, explicit_request=False) is True

    # Record that prompt was sent
    record_location_prompt(phone)

    # 2. Second check of the day without explicit request -> Suppressed
    assert should_prompt_location(phone, explicit_request=False) is False

    # 3. Explicit request on same day -> Allowed
    assert should_prompt_location(phone, explicit_request=True) is True

    # 4. Different phone on same day -> Allowed
    assert should_prompt_location("+919999988888", explicit_request=False) is True

    # 5. After reset -> Allowed again
    reset_prompt_dates()
    assert should_prompt_location(phone, explicit_request=False) is True


@pytest.mark.asyncio
async def test_layer0_location_node_rate_limiting() -> None:
    """layer0_location_node must send 1-click link first time and suppress on second."""
    reset_prompt_dates()
    kg_service = KnowledgeGraphService()
    phone = "+919123456780"
    kiosk_id = "NODE-PUNE-05"

    state1: TemperatureMarkerState = {
        "correlation_id": "test-corr-1",
        "sender_phone": phone,
        "kiosk_id": kiosk_id,
        "user_coords": None,
        "explicit_location_request": False,
    }

    # First attempt: link must be included
    res1 = await layer0_location_node(state1, kg_service)
    assert res1["geofence_verified"] is False
    assert "/loc?session=test-corr-1" in res1["reply_message"]

    # Second attempt on same day: link must be suppressed
    state2: TemperatureMarkerState = {
        "correlation_id": "test-corr-2",
        "sender_phone": phone,
        "kiosk_id": kiosk_id,
        "user_coords": None,
        "explicit_location_request": False,
    }
    res2 = await layer0_location_node(state2, kg_service)
    assert res2["geofence_verified"] is False
    assert "/loc?session=" not in res2["reply_message"]
    assert "already shared earlier today" in res2["reply_message"]

    # Third attempt with explicit request: link must be sent again
    state3: TemperatureMarkerState = {
        "correlation_id": "test-corr-3",
        "sender_phone": phone,
        "kiosk_id": kiosk_id,
        "user_coords": None,
        "explicit_location_request": True,
    }
    res3 = await layer0_location_node(state3, kg_service)
    assert res3["geofence_verified"] is False
    assert "/loc?session=test-corr-3" in res3["reply_message"]


def test_whatsapp_webhook_explicit_location_command() -> None:
    """Inbound WhatsApp message 'location' returns 1-click link."""
    reset_prompt_dates()
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "10001"},
                            "contacts": [{"profile": {"name": "Test User"}, "wa_id": "919811223344"}],
                            "messages": [
                                {
                                    "from": "919811223344",
                                    "id": "wamid.loc_req_1",
                                    "timestamp": "1710400000",
                                    "text": {"body": "location"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "EVENT_RECEIVED"
    assert "/loc?session=" in data["reply_message"]
