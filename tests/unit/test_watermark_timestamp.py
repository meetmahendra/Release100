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

"""Synthetic Unit Tests for Visual Watermark Timestamp Extraction (Phase 3)."""

from datetime import datetime, timezone
import pytest

from apps.temperature_marker.graph.nodes.layer1_ocr_node import layer1_ocr_node
from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.errors import PlatformErrorCode
from core_platform.app.skills.display_ocr import (
    DisplayOCRSkill,
    extract_visual_timestamp_from_text,
    parse_watermark_date,
    validate_watermark_timestamp,
)


def test_extract_visual_timestamp_patterns() -> None:
    """Regex extracts valid camera watermark timestamps and ignores GPS/branding/logos."""
    # 1. Standard ISO format surrounded by device branding and GPS strings
    raw_text = "Shot on OnePlus 2026-09-20 10:15:30 Lat: 18.5204 Lon: 73.8567 KioskNode-Pune-05"
    ts = extract_visual_timestamp_from_text(raw_text)
    assert ts == "2026-09-20 10:15:30"

    # 2. DD/MM/YYYY European/Indian date format
    raw_text_2 = "20/09/2026 14:30 KioskNode Chiller Display"
    ts2 = extract_visual_timestamp_from_text(raw_text_2)
    assert ts2 == "20/09/2026 14:30"

    # 3. Textual month format
    raw_text_3 = "Sep 20, 2026 10:15 AM AI Camera Watermark"
    ts3 = extract_visual_timestamp_from_text(raw_text_3)
    assert ts3 == "Sep 20, 2026 10:15 AM"

    # 4. Hyphenated month format with Sept (e.g. 16-Sept-2026 10:14:29 am)
    raw_text_4 = "GPS MAP CAMERA 16-Sept-2026 10:14:29 am Pune Maharashtra"
    ts4 = extract_visual_timestamp_from_text(raw_text_4)
    assert ts4 == "16-Sept-2026 10:14:29 am"

    # 5. Hyphenated month format with Sep (e.g. 13-Sep-2026 10:30:20)
    raw_text_5 = "Chiller Display 13-Sep-2026 10:30:20 KioskNode-Pune-04"
    ts5 = extract_visual_timestamp_from_text(raw_text_5)
    assert ts5 == "13-Sep-2026 10:30:20"

    # 6. Non-timestamp text (only GPS, branding, kiosk name) -> Returns None
    raw_text_none = "Shot on Redmi Note 12 AI Camera Lat 18.5620 Lon 73.9168 Kiosk 5"
    assert extract_visual_timestamp_from_text(raw_text_none) is None


def test_parse_watermark_date() -> None:
    """Date normalizer parses diverse camera timestamp strings into YYYY-MM-DD."""
    assert parse_watermark_date("2026-09-20 10:15:30") == "2026-09-20"
    assert parse_watermark_date("20/09/2026 14:30") == "2026-09-20"
    assert parse_watermark_date("Sep 20, 2026 10:15 AM") == "2026-09-20"
    assert parse_watermark_date("16-Sept-2026 10:14:29 am") == "2026-09-16"
    assert parse_watermark_date("13-Sept-2026 10:30:20 am") == "2026-09-13"
    assert parse_watermark_date("16-Sep-2026") == "2026-09-16"
    assert parse_watermark_date("2026:09:16 10:14:29") == "2026-09-16"
    assert parse_watermark_date("invalid-text") is None


def test_validate_watermark_timestamp() -> None:
    """Timestamp validator approves current shift date and flags stale photos."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Current date watermark -> Valid
    valid_ts = f"{today} 09:30:00"
    is_valid, msg = validate_watermark_timestamp(valid_ts, target_date=today)
    assert is_valid is True
    assert "matches active shift date" in msg

    # Stale/Yesterday watermark -> Invalid
    stale_ts = "2026-01-01 10:00:00"
    is_valid_stale, msg_stale = validate_watermark_timestamp(stale_ts, target_date=today)
    assert is_valid_stale is False
    assert "does not match active shift date" in msg_stale


@pytest.mark.asyncio
async def test_display_ocr_skill_combined_photo_watermark() -> None:
    """DisplayOCRSkill.analyze_combined_kiosk_photo captures watermark timestamp."""
    skill = DisplayOCRSkill()
    await skill.initialize()

    # Simulated combined payload with watermark
    sim_data = {
        "face_detected": True,
        "face_confidence": 0.95,
        "temperature_c": 3.4,
        "confidence": 0.95,
        "watermark_timestamp": "2026-09-20 11:00:00",
    }
    result = await skill.analyze_combined_kiosk_photo(sim_data)
    assert result["watermark_timestamp"] == "2026-09-20 11:00:00"
    assert result["temperature_c"] == 3.4

    # Simulated combined payload with overlay text containing timestamp
    sim_overlay = {
        "face_detected": True,
        "face_confidence": 0.92,
        "temperature_c": 2.8,
        "confidence": 0.90,
        "overlay_text": "Shot on Samsung 2026-09-20 11:15:00 Lat 18.52",
    }
    result_overlay = await skill.analyze_combined_kiosk_photo(sim_overlay)
    assert result_overlay["watermark_timestamp"] == "2026-09-20 11:15:00"


@pytest.mark.asyncio
async def test_layer1_ocr_node_valid_watermark() -> None:
    """layer1_ocr_node approves photo with valid watermark matching today's shift."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state: TemperatureMarkerState = {
        "correlation_id": "test-wm-valid",
        "kiosk_id": "NODE-PUNE-05",
        "sender_phone": "+919800011122",
        "watermark_timestamp": f"{today} 10:15:00",
        "ocr_confidence": 0.92,
        "chiller_temp_c": 3.1,
    }

    final_state = await layer1_ocr_node(state)
    assert final_state.get("layer_0_passed", True) is not False
    assert final_state.get("watermark_timestamp") == f"{today} 10:15:00"
    assert final_state.get("chiller_temp_c") == 3.1


@pytest.mark.asyncio
async def test_layer1_ocr_node_stale_watermark_rejected() -> None:
    """layer1_ocr_node diverts to review when watermark is from a stale/recycled date."""
    stale_date = "2025-12-31 10:15:00"
    state: TemperatureMarkerState = {
        "correlation_id": "test-wm-stale",
        "kiosk_id": "NODE-PUNE-05",
        "sender_phone": "+919800011122",
        "watermark_timestamp": stale_date,
        "ocr_confidence": 0.92,
        "chiller_temp_c": 3.1,
    }

    final_state = await layer1_ocr_node(state)
    assert final_state["layer_0_passed"] is False
    assert final_state["layer_2_disposition"] == "diverted_to_review"
    assert final_state["error_code"] == PlatformErrorCode.SAFETY_TAMPER_DETECTED.value
    assert "Stale Photo Detected" in final_state["reply_message"]
    assert final_state.get("chiller_temp_c") is None


@pytest.mark.asyncio
async def test_layer1_ocr_node_september_watermark_stale_rejection() -> None:
    """layer1_ocr_node specifically catches '16-Sept-2026 10:14:29 am' and clears chiller_temp_c."""
    state: TemperatureMarkerState = {
        "correlation_id": "test-wm-sept-stale",
        "kiosk_id": "NODE-PUNE-05",
        "sender_phone": "+919800011122",
        "watermark_timestamp": "16-Sept-2026 10:14:29 am",
        "ocr_confidence": 0.95,
        "chiller_temp_c": 6.2,
    }

    # If target shift is 2026-09-20 (today), 16-Sept must be rejected
    final_state = await layer1_ocr_node(state)
    assert final_state["layer_0_passed"] is False
    assert final_state["layer_2_disposition"] == "diverted_to_review"
    assert final_state["error_code"] == PlatformErrorCode.SAFETY_TAMPER_DETECTED.value
    assert "Stale Photo Detected" in final_state["reply_message"]
    assert final_state.get("chiller_temp_c") is None  # Stale temp cleared

