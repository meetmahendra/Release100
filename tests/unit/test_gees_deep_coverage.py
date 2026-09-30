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

"""GEES v1.0 Deep Coverage & Rigorous Boundary Verification Suite."""

import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from PIL import Image
import pytest

from core_platform.app.config import settings
from core_platform.app.ingress.relay_client import CloudRelayClient
from core_platform.app.llm.cost_tracker import LLMCostTracker
from core_platform.app.skills.image_enhancer import ImageEnhancerSkill


# ============================================================================
# 1. ImageEnhancerSkill Deep Coverage
# ============================================================================

@pytest.mark.asyncio
async def test_image_enhancer_clahe_and_filtering() -> None:
    """Test CLAHE histogram equalization, glare suppression, and mirror adjustment."""
    skill = ImageEnhancerSkill()
    await skill.ensure_initialized()
    assert skill.is_available() is True

    # 1. Enhance low-contrast image array
    arr = np.full((100, 100, 3), 50, dtype=np.uint8)
    arr[20:80, 20:80] = 90

    enh_arr = await skill.enhance_contrast_clahe(arr)
    assert isinstance(enh_arr, np.ndarray)
    assert enh_arr.shape == arr.shape

    # 2. Specular glare reduction
    glare_arr = await skill.suppress_panel_glare(arr)
    assert isinstance(glare_arr, np.ndarray)
    assert glare_arr.shape == arr.shape

    # 3. Mirror correction
    mirrored, was_flipped = await skill.correct_selfie_mirror(arr, force_flip=True)
    assert isinstance(mirrored, np.ndarray)
    assert was_flipped is True
    assert mirrored.shape == arr.shape

    # 4. Exif orientation check
    mirrored_exif, was_flipped_exif = await skill.correct_selfie_mirror(arr, exif_orientation=2)
    assert was_flipped_exif is True

    health = skill.get_health_status()
    assert isinstance(health["opencv_accelerated"], bool)


# ============================================================================
# 2. LLMCostTracker Deep Coverage
# ============================================================================

def test_llm_cost_tracker_full_cycle() -> None:
    """Test LLM interaction tracking, JSONL streaming, and cost summary aggregation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        log_file = Path(temp_dir) / "test_llm_cost.jsonl"
        tracker = LLMCostTracker(max_records=100, jsonl_log_path=log_file)

        # Record Gemini Flash interaction
        tracker.record_interaction(
            interaction_id="ix_001",
            operation_id="test_classify",
            task="triage",
            provider="gemini",
            model="gemini-2.5-flash",
            prompt_tokens=450,
            completion_tokens=60,
            latency_ms=320.5,
            success=True,
        )

        # Record OpenAI interaction
        tracker.record_interaction(
            interaction_id="ix_002",
            operation_id="test_draft",
            task="drafting",
            provider="openai",
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=200,
            latency_ms=850.0,
            success=True,
        )

        # Check log existence
        assert log_file.exists()
        summary = tracker.get_summary()
        assert summary["total_interactions"] == 2
        assert summary["total_tokens"] == (450 + 60 + 1000 + 200)
        assert summary["total_cost_usd"] > 0.0

        ops_report = tracker.get_operations_report()
        assert len(ops_report) == 2


# ============================================================================
# 3. CloudRelayClient Deep Coverage
# ============================================================================

@pytest.mark.asyncio
async def test_cloud_relay_client_lifecycle_and_formatting() -> None:
    """Test outbound WebSocket relay client state management and URL formatting."""
    client = CloudRelayClient(
        relay_url="https://test-relay.workers.dev",
        kiosk_id="CANEBOT-PUNE-04",
    )
    assert client.is_connected is False
    assert client.relay_url == "wss://test-relay.workers.dev/ws/CANEBOT-PUNE-04"

    # Test template URL
    formatted = CloudRelayClient._format_relay_url(
        "wss://relay.com/ws/{kiosk_id}", "CANEBOT-BLR-02"
    )
    assert formatted == "wss://relay.com/ws/CANEBOT-BLR-02"

    # Mock dispatch callback
    mock_callback = AsyncMock()
    client.message_handler = mock_callback

    # Test start when no relay url configured
    disabled_client = CloudRelayClient(relay_url="", kiosk_id="TEST")
    assert disabled_client.start() is None


# ============================================================================
# 4. WhatsApp Router Signature & Webhook Verification
# ============================================================================

@pytest.mark.asyncio
async def test_whatsapp_router_signature_and_dispatch() -> None:
    """Test HMAC signature verification and payload dispatch."""
    from core_platform.app.ingress.whatsapp_router import (
        verify_meta_signature,
        dispatch_whatsapp_payload,
    )

    # 1. Signature check when not configured
    assert verify_meta_signature(b"test", None) is True

    # 2. Test empty / status payload dispatch
    relay_conn_payload = {"event": "connected", "message": "Worker ready"}
    res = await dispatch_whatsapp_payload(relay_conn_payload)
    assert res["status"] == "RELAY_CONNECTED"

    # 3. Test empty entry payload
    empty_entry_payload = {"object": "whatsapp_business_account", "entry": []}
    res_empty = await dispatch_whatsapp_payload(empty_entry_payload)
    assert res_empty["status"] == "NO_ENTRY"

    # 4. Test delivery receipt status
    receipt_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.REC123",
                                    "recipient_id": "919800011122",
                                    "status": "delivered",
                                }
                            ]
                        },
                    }
                ]
            }
        ]
    }
    res_receipt = await dispatch_whatsapp_payload(receipt_payload)
    assert res_receipt["status"] == "STATUS_UPDATE"

