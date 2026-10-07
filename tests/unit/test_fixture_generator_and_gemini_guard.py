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

"""Unit tests for fixture generator, image magic-byte guard, and LLM cost tracker."""

import io
import pytest
from PIL import Image
from apps.temperature_marker.common.fixture_generator import (
    generate_synthetic_gauge_jpeg,
    get_real_kiosk_fixture,
)
from core_platform.app.skills.display_ocr import is_valid_image_bytes
from core_platform.app.llm.cost_tracker import LLMCostTracker


def test_is_valid_image_bytes():
    """Verify magic bytes classification for images vs dummy text."""
    # Invalid payloads
    assert not is_valid_image_bytes(b"")
    assert not is_valid_image_bytes(b"DIGIT:36.5")
    assert not is_valid_image_bytes("not bytes")
    assert not is_valid_image_bytes(None)
    assert not is_valid_image_bytes(b"TEXT:invalid")

    # Valid JPEG
    jpeg_bytes = generate_synthetic_gauge_jpeg(3.5)
    assert is_valid_image_bytes(jpeg_bytes)

    # Valid PNG header
    png_dummy = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert is_valid_image_bytes(png_dummy)

    # Valid WebP header
    webp_dummy = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 10
    assert is_valid_image_bytes(webp_dummy)


def test_generate_synthetic_gauge_jpeg():
    """Verify synthetic gauge image is a valid, readable JPEG."""
    jpeg_bytes = generate_synthetic_gauge_jpeg(temperature=3.8, kiosk_id="NODE-PUNE-04")
    assert len(jpeg_bytes) > 2000
    assert jpeg_bytes.startswith(b"\xff\xd8\xff")

    # Verify PIL can open and parse image dimensions
    img = Image.open(io.BytesIO(jpeg_bytes))
    assert img.format == "JPEG"
    assert img.size == (400, 200)


def test_get_real_kiosk_fixture():
    """Verify real kiosk fixture loader returns valid JPEG data."""
    data = get_real_kiosk_fixture()
    assert len(data) > 1000
    assert is_valid_image_bytes(data)


def test_cost_tracker_zeros_4xx_rejections(tmp_path):
    """Verify HTTP 4xx rejections record $0.00 cost in the tracker."""
    tracker = LLMCostTracker(jsonl_log_path=tmp_path / "test_audit.jsonl")
    record = tracker.record_interaction(
        interaction_id="ix_test_001",
        operation_id="test_op",
        task="vision_processing",
        provider="gemini",
        model="gemini-3.6-flash",
        prompt_tokens=538,
        completion_tokens=0,
        latency_ms=620.0,
        success=False,
        error_message="HTTP 400: Unable to process input image",
    )
    assert record.estimated_cost_usd == 0.0
    assert record.prompt_tokens == 0
    assert record.total_tokens == 0
    assert record.success is False
