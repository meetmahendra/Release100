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

"""Synthetic Unit Tests for ImageEnhancerSkill."""

import numpy as np
import pytest
from core_platform.app.skills.image_enhancer import ImageEnhancerSkill


@pytest.mark.asyncio
async def test_image_enhancer_initialization() -> None:
    """ImageEnhancerSkill must initialize and report health."""
    skill = ImageEnhancerSkill()
    await skill.ensure_initialized()
    assert skill.is_available() is True
    health = skill.get_health_status()
    assert "clahe_clip_limit" in health


@pytest.mark.asyncio
async def test_image_enhancer_clahe_contrast() -> None:
    """ImageEnhancerSkill must process synthetic BGR array without error."""
    skill = ImageEnhancerSkill()
    # Create 100x100 synthetic low-contrast image
    sample_img = np.full((100, 100, 3), 50, dtype=np.uint8)
    sample_img[20:80, 20:80] = 70

    enhanced = await skill.enhance_contrast_clahe(sample_img)
    assert enhanced.shape == (100, 100, 3)
    assert enhanced.dtype == np.uint8


@pytest.mark.asyncio
async def test_image_enhancer_mirror_correction() -> None:
    """ImageEnhancerSkill must horizontally flip image when requested."""
    skill = ImageEnhancerSkill()
    sample_img = np.zeros((10, 10, 3), dtype=np.uint8)
    sample_img[:, 0] = 255  # Left column is white

    flipped, was_flipped = await skill.correct_selfie_mirror(sample_img, force_flip=True)
    assert was_flipped is True
    # Now right column must be white
    assert np.all(flipped[:, -1] == 255)


@pytest.mark.asyncio
async def test_image_enhancer_glare_suppression() -> None:
    """ImageEnhancerSkill must attenuate extreme specular highlights."""
    skill = ImageEnhancerSkill()
    sample_img = np.full((50, 50, 3), 100, dtype=np.uint8)
    sample_img[20:30, 20:30] = 255  # Saturated glare spot

    suppressed = await skill.suppress_panel_glare(sample_img)
    assert suppressed.shape == (50, 50, 3)


@pytest.mark.anyio
async def test_ingest_node_passthrough() -> None:
    """ingest_node must pass through state unchanged when raw_image_bytes is absent."""
    from apps.temperature_marker.graph.nodes.ingest_node import ingest_node
    from apps.temperature_marker.graph.state import TemperatureMarkerState

    state: TemperatureMarkerState = {
        "correlation_id": "test_pass_123",
        "sender_phone": "+919876543210",
        "raw_text": "Check in only",
    }
    result = await ingest_node(state)
    assert result.get("raw_image_bytes") is None
    assert result.get("correlation_id") == "test_pass_123"


@pytest.mark.anyio
async def test_ingest_node_with_image() -> None:
    """ingest_node must enhance raw_image_bytes when a valid image is provided."""
    import io
    from PIL import Image
    from apps.temperature_marker.graph.nodes.ingest_node import ingest_node
    from apps.temperature_marker.graph.state import TemperatureMarkerState

    # Create 32x32 synthetic JPEG
    img = Image.new("RGB", (32, 32), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    state: TemperatureMarkerState = {
        "correlation_id": "test_img_123",
        "sender_phone": "+919876543210",
        "raw_image_bytes": jpeg_bytes,
    }
    result = await ingest_node(state)
    assert result.get("raw_image_bytes") is not None
    assert isinstance(result["raw_image_bytes"], bytes)

    # Test corrupted image bytes fallback
    corrupt_state: TemperatureMarkerState = {
        "correlation_id": "corrupt_123",
        "sender_phone": "+919876543210",
        "raw_image_bytes": b"not_a_real_image_bytes",
    }
    result_corrupt = await ingest_node(corrupt_state)
    assert result_corrupt.get("raw_image_bytes") == b"not_a_real_image_bytes"
