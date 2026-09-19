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

"""Synthetic Unit Tests for Meta WhatsApp Webhook Ingress Gateway."""

import pytest
from starlette.testclient import TestClient

from apps.temperature_marker.database.db_service import DatabaseService
from core_platform.app.config import settings
from core_platform.main import app

client = TestClient(app)


def test_whatsapp_webhook_verification_success() -> None:
    """GET /webhook must echo hub.challenge when token matches."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
        "hub.challenge": "11582012",
    }
    resp = client.get("/webhook", params=params)
    assert resp.status_code == 200
    assert resp.text == "11582012"


def test_whatsapp_webhook_verification_forbidden() -> None:
    """GET /webhook must return 403 when token does not match."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong_token",
        "hub.challenge": "11582012",
    }
    resp = client.get("/webhook", params=params)
    assert resp.status_code == 403


def test_whatsapp_webhook_message_processing() -> None:
    """POST /webhook must parse message and trigger workflow."""
    # Ensure active operator exists
    db = DatabaseService()
    db.register_employee(
        emp_code="EMP-1042",
        full_name="Rajesh Pawar",
        phone_number="+919800011122",
        assigned_kiosk_id="CANEBOT-PUNE-04",
        status="ACTIVE",
    )

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
                            "contacts": [{"profile": {"name": "Rajesh"}, "wa_id": "919800011122"}],
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.test123",
                                    "timestamp": "1710400000",
                                    "text": {"body": "Check-in duty"},
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
    assert "reply_message" in data
    assert data["kiosk_id"] == "CANEBOT-PUNE-04"


def test_whatsapp_webhook_status_receipt_ignored() -> None:
    """POST /webhook must ignore status receipts cleanly."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [{"id": "wamid.123", "status": "delivered"}],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "NO_MESSAGES"


def test_whatsapp_webhook_empty_entry() -> None:
    """Empty entry must return NO_ENTRY."""
    resp = client.post("/webhook", json={"entry": []})
    assert resp.status_code == 200
    assert resp.json()["status"] == "NO_ENTRY"


def test_whatsapp_webhook_location_message() -> None:
    """Location message must be processed."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.loc123",
                                    "timestamp": "1710400000",
                                    "type": "location",
                                    "location": {
                                        "latitude": 18.5204,
                                        "longitude": 73.8567,
                                        "name": "Pune Kiosk",
                                    },
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


def test_whatsapp_webhook_image_message() -> None:
    """Image message must trigger media download and workflow."""
    from unittest.mock import patch

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.img123",
                                    "timestamp": "1710400000",
                                    "type": "image",
                                    "image": {"id": "meta_img_999"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    with patch("core_platform.app.ingress.whatsapp_router.fetch_whatsapp_media_bytes", return_value=b"\xff\xd8fake_jpeg"):
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "EVENT_RECEIVED"


def test_whatsapp_webhook_registration_commands() -> None:
    """Test operator self-registration commands via WhatsApp."""
    # 1. Valid registration
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.reg1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "register EMP-2099 Suresh Patil"},
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
    assert "Registration Submitted for Suresh Patil (EMP-2099)" in data["reply_message"]


def test_whatsapp_webhook_mail_commands() -> None:
    """Test mail organizer digest and task approval/rejection commands."""
    # 1. Mail digest summary
    digest_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.mail1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "mail digest"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp = client.post("/webhook", json=digest_payload)
    assert resp.status_code == 200
    assert "AI Mail & Calendar Summary" in resp.json()["reply_message"]

    # 2. Approve task
    approve_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.app1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "approve TASK-NONEXISTENT"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp2 = client.post("/webhook", json=approve_payload)
    assert resp2.status_code == 200
    assert "not found" in resp2.json()["reply_message"]

    # 3. Reject task
    reject_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919800011122",
                                    "id": "wamid.rej1",
                                    "timestamp": "1710400000",
                                    "type": "text",
                                    "text": {"body": "reject TASK-NONEXISTENT"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    resp3 = client.post("/webhook", json=reject_payload)
    assert resp3.status_code == 200
    assert "not found" in resp3.json()["reply_message"]


@pytest.mark.anyio
async def test_cloud_relay_client_message_handling() -> None:
    """Test CloudRelayClient raw message parsing and error resilience."""
    import json
    from core_platform.app.ingress.relay_client import CloudRelayClient

    client = CloudRelayClient(relay_url="wss://mock-relay.example.com")
    assert client.is_running is False

    handled: list[dict] = []

    async def custom_handler(p: dict) -> None:
        handled.append(p)

    client.message_handler = custom_handler

    # Test bytes message
    raw_bytes = json.dumps({"test_key": "val_bytes"}).encode("utf-8")
    await client._handle_raw_message(raw_bytes)
    assert len(handled) == 1
    assert handled[0]["test_key"] == "val_bytes"

    # Test text message
    raw_str = json.dumps({"test_key": "val_str"})
    await client._handle_raw_message(raw_str)
    assert len(handled) == 2
    assert handled[1]["test_key"] == "val_str"

    # Test invalid json resilience
    await client._handle_raw_message("not valid json at all")
    assert len(handled) == 2  # No new payload added, handled gracefully


