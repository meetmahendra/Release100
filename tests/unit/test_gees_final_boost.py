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

"""GEES v1.0 Final Boost Test Suite for Complete Excellence Certification."""

import io
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
from PIL import Image
import pytest

from core_platform.app.config import settings
from core_platform.app.ingress.location_session import LocationSessionCache
from core_platform.app.ingress.whatsapp_outbound import send_whatsapp_message
from core_platform.app.skills.face_recognizer import FaceRecognizerSkill
from apps.mail_organizer.plugin import MailOrganizerApplication


# ============================================================================
# 1. LocationSessionCache Deep Coverage
# ============================================================================

def test_location_session_cache_lifecycle() -> None:
    """Test session cache metadata binding, TTL expiration, and daily prompt tracking."""
    cache = LocationSessionCache()

    # 1. Empty session lookup
    assert cache.get_metadata("") is None
    assert cache.get_phone("non-existent") is None

    # 2. Bind metadata with short TTL
    cache.bind_metadata("sess-test-1", {"phone": "+919800011122", "kiosk": "CANEBOT-PUNE-04"}, ttl_seconds=1)
    meta = cache.get_metadata("sess-test-1")
    assert meta is not None
    assert meta["phone"] == "+919800011122"
    assert cache.get_phone("sess-test-1") == "+919800011122"

    # 3. Store and retrieve coordinates
    cache.set_coordinates("sess-test-1", (18.5621, 73.9168), ttl_seconds=10)
    coords = cache.get_coordinates("sess-test-1")
    assert coords == (18.5621, 73.9168)

    # 4. Daily prompt date tracking
    phone = "+919800011122"
    cache.reset_prompt_dates()
    assert cache.should_prompt_location(phone) is True
    cache.record_location_prompt(phone)
    assert cache.should_prompt_location(phone) is False
    assert cache.should_prompt_location(phone, explicit_request=True) is True

    # 5. Clear session
    cache.clear("sess-test-1")
    assert cache.get_coordinates("sess-test-1") is None


# ============================================================================
# 2. WhatsApp Outbound Dispatcher Tests
# ============================================================================

@pytest.mark.asyncio
async def test_send_whatsapp_message_cases() -> None:
    """Test phone normalization, credentials check, and mocked API responses."""
    # 1. Invalid phone number
    res_inv = await send_whatsapp_message("invalid-phone", "Hello")
    assert res_inv is None

    # 2. Successful dispatch with mocked httpx
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"messages": [{"id": "wamid.OUT_123"}]}

    with patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "mock_whatsapp_access_token_12345"), \
         patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "1234567890"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        msg_id = await send_whatsapp_message("+919800011122", "Test Outbound")
        assert msg_id == "wamid.OUT_123"


# ============================================================================
# 3. Mail Organizer Outbox Transmitter Tests
# ============================================================================

@pytest.mark.asyncio
async def test_mail_organizer_outbox_transmitter() -> None:
    """Test outbox transmitter for draft creation, labeling, and PM task exports."""
    app_mo = MailOrganizerApplication(db_url="sqlite:///:memory:")
    transmitter = app_mo.get_outbox_transmitter()
    assert callable(transmitter)

    # Mock connectors
    app_mo.gmail_connector = MagicMock()
    app_mo.gmail_connector.create_draft = AsyncMock(return_value={"draft_id": "draft_999"})
    app_mo.gmail_connector.apply_labels = AsyncMock(return_value=True)

    app_mo.pm_manager = MagicMock()
    app_mo.pm_manager.approve_and_export = AsyncMock(return_value={"success": True})

    # 1. Test create draft transmission
    ok_draft, msg_draft = await transmitter("gmail_api", {
        "action": "create_draft",
        "thread_id": "th_1",
        "recipient": "test@canectar.com",
        "subject": "Hi",
        "body": "Body",
    })
    assert ok_draft is True
    assert "draft_999" in msg_draft

    # 2. Test apply labels transmission
    ok_label, _ = await transmitter("gmail_api", {
        "action": "apply_labels",
        "gmail_id": "gm_1",
        "add_labels": ["@Processed"],
    })
    assert ok_label is True

    # 3. Test PM task export
    ok_pm, _ = await transmitter("jira", {"task_id": "task_123", "destination": "jira"})
    assert ok_pm is True


# ============================================================================
# 4. FaceRecognizerSkill Cloud Fallback Verification
# ============================================================================

@pytest.mark.asyncio
async def test_face_recognizer_cloud_vision_verification_flow() -> None:
    """Test FaceRecognizerSkill verify_face_match cloud Gemini vision branch."""
    skill = FaceRecognizerSkill()
    await skill.ensure_initialized()

    # Create two valid test images
    img1 = Image.new("RGB", (112, 112), color=(200, 200, 200))
    buf1 = io.BytesIO()
    img1.save(buf1, format="JPEG")
    b1 = buf1.getvalue()

    # Mock urllib response
    fake_gemini_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "face_detected": True,
                                "same_person": True,
                                "match_confidence": 0.96,
                                "reasoning": "Gemini Multimodal Vision: Matching operator facial features",
                            })
                        }
                    ]
                }
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 500,
            "candidatesTokenCount": 45,
        }
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(fake_gemini_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch.object(settings, "GEMINI_API_KEY", "mock_gemini_test_key_12345"), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        matched, sim, reason = await skill.verify_face_match(b1, b1)
        assert matched is True
        assert sim == 0.96
        assert "Gemini Multimodal Vision" in reason
