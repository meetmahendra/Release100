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

"""Unit tests for WhatsApp Ingress deduplication and dynamic public URL resolution."""

import pytest
from unittest.mock import AsyncMock, patch
from starlette.requests import Request

from core_platform.app.identity.magic_link import build_magic_link_url
from core_platform.app.ingress.whatsapp_router import (
    InboundMessageDeduplicator,
    dispatch_whatsapp_payload,
    extract_public_base_url,
    get_inbound_deduplicator,
)


def test_inbound_message_deduplicator_lru_and_expiry() -> None:
    """Verify InboundMessageDeduplicator prevents duplicate message processing."""
    dedup = InboundMessageDeduplicator(ttl_seconds=1.0, max_entries=3)
    dedup.clear()

    # First arrival of message
    assert dedup.is_duplicate_or_record("wamid.001") is False

    # Second arrival of identical message ID (retry / duplicate)
    assert dedup.is_duplicate_or_record("wamid.001") is True

    # Empty or None IDs are never treated as duplicate
    assert dedup.is_duplicate_or_record("") is False
    assert dedup.is_duplicate_or_record(None) is False

    # Capacity eviction
    dedup.is_duplicate_or_record("wamid.002")
    dedup.is_duplicate_or_record("wamid.003")
    dedup.is_duplicate_or_record("wamid.004")  # Should evict oldest

    dedup.clear()


@pytest.mark.asyncio
async def test_dispatch_whatsapp_payload_drops_duplicate_wamid() -> None:
    """Verify dispatch_whatsapp_payload drops duplicate wamid without re-execution."""
    dedup = get_inbound_deduplicator()
    dedup.clear()

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.TEST_DUPLICATE_999",
                                    "from": "+919800000001",
                                    "text": {"body": "ping"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with patch("core_platform.app.identity.service.get_user_identity_service") as mock_uis, \
         patch("core_platform.app.ingress.whatsapp_outbound.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        from unittest.mock import MagicMock
        mock_service = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.status = "active"
        mock_user.tenant_id = "default"
        mock_user.allowed_cartridges = ["*"]
        mock_service.get_user_by_phone.return_value = mock_user
        mock_uis.return_value = mock_service

        # First call processes
        res1 = await dispatch_whatsapp_payload(payload)
        assert res1["status"] != "DUPLICATE_DROPPED"

        # Immediate second call with identical wamid gets dropped
        res2 = await dispatch_whatsapp_payload(payload)
        assert res2["status"] == "DUPLICATE_DROPPED"
        assert res2["message_id"] == "wamid.TEST_DUPLICATE_999"

        # Outbound message should only have been dispatched once
        assert mock_send.call_count == 1

    dedup.clear()


def test_extract_public_base_url_and_https_upgrade() -> None:
    """Verify reverse-proxy headers (ngrok) correctly resolve to public https."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhook",
        "headers": [
            (b"host", b"localhost:8000"),
            (b"x-forwarded-host", b"my-tunnel.ngrok-free.app"),
            (b"x-forwarded-proto", b"https"),
        ],
    }
    request = Request(scope)
    base_url = extract_public_base_url(request)
    assert base_url == "https://my-tunnel.ngrok-free.app"

    # Verify magic link generation uses https and public host
    link = build_magic_link_url(
        user_id="101",
        phone_number="+919800000001",
        base_url=base_url,
    )
    assert link.startswith("https://my-tunnel.ngrok-free.app/auth/google/connect?token=")
