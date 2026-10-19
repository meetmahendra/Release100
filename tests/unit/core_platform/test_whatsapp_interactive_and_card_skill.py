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

"""Unit tests for Phase 1 [CODE-MARKER: CP-WA-01..02 & CP-SKILL-01]: WhatsApp Interactive API & CardImageRendererSkill."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core_platform.app.ingress.whatsapp_outbound import (
    send_whatsapp_interactive_buttons,
    send_whatsapp_interactive_list,
    send_whatsapp_template,
    upload_whatsapp_media,
)
from core_platform.app.skills.card_image_renderer import CardImageRendererSkill, CardRenderSpec
from core_platform.app.skills.registry import get_platform_skill


@pytest.mark.asyncio
async def test_card_image_renderer_skill_generates_valid_png() -> None:
    """Verify CardImageRendererSkill is registered in SkillRegistry and produces valid PNG bytes."""
    skill = get_platform_skill("card_image_renderer")
    await skill.ensure_initialized()
    assert isinstance(skill, CardImageRendererSkill)
    assert skill.is_available() is True

    spec = CardRenderSpec(
        badge_text="URGENT • P1",
        badge_tone="danger",
        title="Approve PO-8841 ($42,500)",
        subtitle="From: Rajesh Pawar (VP Eng)",
        rows=[
            ("THE ASK", "Sign off Q4 compute cluster PO"),
            ("DEADLINE", "Today 17:00 IST (2h remaining)"),
            ("VERIFIED FACT", "PO-8841 matches budget cap ($45k)"),
            ("AI ACTION", "Staged approval draft ready"),
        ],
        footer_note="Verified via Hybrid Entity-Fact Graph",
    )
    png_bytes = skill.render_card_png(spec)
    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png_bytes) > 50


@pytest.mark.asyncio
async def test_whatsapp_outbound_interactive_buttons_list_and_template() -> None:
    """Verify upload_whatsapp_media, send_whatsapp_interactive_buttons, list, and template payloads."""
    mock_upload_resp = MagicMock()
    mock_upload_resp.is_success = True
    mock_upload_resp.json.return_value = {"id": "media_998877"}

    mock_msg_resp = MagicMock()
    mock_msg_resp.is_success = True
    mock_msg_resp.json.return_value = {"messages": [{"id": "wamid.test123"}]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_upload_resp, mock_msg_resp, mock_msg_resp, mock_msg_resp]

        media_id = await upload_whatsapp_media(
            image_bytes=b"\x89PNG\r\n\x1a\n",
            access_token="mock_whatsapp_access_token_abcdef",
            phone_number_id="1234567890",
        )
        assert media_id == "media_998877"

        btn_msg_id = await send_whatsapp_interactive_buttons(
            to_phone="+919876543210",
            body_text="Executive Decision Brief",
            buttons=[
                {"id": "approve_send:1", "title": "✅ Approve & Send"},
                {"id": "deep_inspect:1", "title": "🔍 Full Context"},
            ],
            header_media_id=media_id,
            access_token="mock_whatsapp_access_token_abcdef",
            phone_number_id="1234567890",
        )
        assert btn_msg_id == "wamid.test123"

        list_msg_id = await send_whatsapp_interactive_list(
            to_phone="+919876543210",
            body_text="3 Actionable Items",
            button_label="Select Item",
            sections=[{"title": "Urgent", "rows": [{"id": "inspect_mail:1", "title": "PO-8841 Approval"}]}],
            access_token="mock_whatsapp_access_token_abcdef",
            phone_number_id="1234567890",
        )
        assert list_msg_id == "wamid.test123"

        tpl_msg_id = await send_whatsapp_template(
            to_phone="+919876543210",
            template_name="executive_urgent_mail_alert_v1",
            access_token="mock_whatsapp_access_token_abcdef",
            phone_number_id="1234567890",
        )
        assert tpl_msg_id == "wamid.test123"
        assert mock_post.call_count == 4
