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

"""
Ingest & Image Pre-Processing Node (`ingest_node`).

Adheres strictly to Plan 03 v1.3 and GEES v1.0 (Pillar 5 Universal Skills Library).
First node in the Temperature & Attendance Marker LangGraph pipeline.

Responsibilities:
1. Validates that the inbound envelope contains expected fields.
2. If a raw image payload is present, applies the ImageEnhancerSkill pipeline:
   - CLAHE contrast normalisation (reflections, shadows, glare).
   - Front-camera selfie mirror detection & horizontal flip correction.
   - Specular glare suppression on machine acrylic panels.
3. Stores enhanced bytes back into state["raw_image_bytes"] for downstream nodes.
4. Graceful passthrough for text-only messages (no image present).
"""

import io
import logging
from typing import Any, Optional

import numpy as np

from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.skills.image_enhancer import ImageEnhancerSkill
from core_platform.app.skills.registry import get_platform_skill

logger = logging.getLogger("temperature_marker.ingest_node")


async def ingest_node(state: TemperatureMarkerState) -> TemperatureMarkerState:
    """Pre-process the inbound image payload using the ImageEnhancerSkill pipeline.

    Args:
        state: Inbound interaction state carrying raw_image_bytes.

    Returns:
        Updated state with enhanced raw_image_bytes (or unchanged if no image).
    """
    raw_bytes: Optional[bytes] = state.get("raw_image_bytes")

    if not raw_bytes:
        # Text-only message — no image to enhance; passthrough cleanly.
        logger.debug(
            "[IngestNode] No image payload present for correlation_id=%s — passthrough.",
            state.get("correlation_id", "unknown"),
        )
        return state

    try:
        # Acquire the ImageEnhancerSkill singleton from the platform Skills Registry.
        enhancer: ImageEnhancerSkill = get_platform_skill("image_enhancer")  # type: ignore[assignment]
        await enhancer.ensure_initialized()

        # Decode raw bytes → numpy array for OpenCV / numpy processing.
        image_bgr = _decode_image_bytes(raw_bytes)
        if image_bgr is None:
            logger.warning(
                "[IngestNode] Could not decode image bytes for correlation_id=%s — using raw bytes.",
                state.get("correlation_id", "unknown"),
            )
            return state

        # Step A: CLAHE contrast normalisation (handles factory floor lighting variability).
        image_bgr = await enhancer.enhance_contrast_clahe(image_bgr)

        # Step B: Selfie mirror correction (most phone front-cameras are mirrored).
        image_bgr, was_flipped = await enhancer.correct_selfie_mirror(image_bgr)
        if was_flipped:
            logger.debug("[IngestNode] Applied selfie horizontal flip correction.")

        # Step C: Specular glare suppression (CaneBot acrylic panel reflections).
        image_bgr = await enhancer.suppress_panel_glare(image_bgr)

        # Re-encode enhanced image to JPEG bytes and store back in state.
        enhanced_bytes = _encode_image_bytes(image_bgr)
        if enhanced_bytes:
            state["raw_image_bytes"] = enhanced_bytes
            logger.info(
                "[IngestNode] Image enhanced successfully for correlation_id=%s "
                "(opencv_clahe → mirror_correction → glare_suppression).",
                state.get("correlation_id", "unknown"),
            )
        else:
            logger.warning(
                "[IngestNode] Re-encoding failed for correlation_id=%s — keeping original bytes.",
                state.get("correlation_id", "unknown"),
            )

    except Exception as exc:
        # Never block the pipeline — log the error and pass raw bytes downstream.
        logger.error(
            "[IngestNode] Enhancement pipeline raised %s for correlation_id=%s — using raw bytes. Error: %s",
            type(exc).__name__,
            state.get("correlation_id", "unknown"),
            exc,
        )

    return state


# ── Helpers ──────────────────────────────────────────────────────────────────

def _decode_image_bytes(raw_bytes: bytes) -> Optional[Any]:
    """Decode raw JPEG/PNG bytes to a BGR numpy array.

    Tries OpenCV first for full format support; falls back to a pure-numpy path.

    Args:
        raw_bytes: Raw image bytes (JPEG or PNG).

    Returns:
        BGR numpy array, or None if decoding fails.
    """
    try:
        import cv2  # type: ignore[import-not-found]
        nparr = np.frombuffer(raw_bytes, dtype=np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img if img is not None else None
    except Exception:
        pass

    # Pure-Python PIL fallback (slower but dependency-free if OpenCV absent).
    try:
        from PIL import Image
        pil_img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        rgb_array = np.array(pil_img, dtype=np.uint8)
        # PIL gives RGB, OpenCV convention is BGR.
        return rgb_array[:, :, ::-1]
    except Exception:
        return None


def _encode_image_bytes(image_bgr: Any) -> Optional[bytes]:
    """Encode a BGR numpy array back to JPEG bytes.

    Args:
        image_bgr: BGR numpy array.

    Returns:
        JPEG bytes, or None if encoding fails.
    """
    try:
        import cv2
        success, buf = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if success:
            return bytes(buf.tobytes())
    except Exception:
        pass

    try:
        from PIL import Image
        rgb_array = image_bgr[:, :, ::-1]  # BGR → RGB
        pil_img = Image.fromarray(rgb_array.astype(np.uint8))
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception:
        return None
