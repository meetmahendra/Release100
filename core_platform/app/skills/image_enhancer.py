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
Image Preprocessing and Enhancement Cognitive Skill (`ImageEnhancerSkill`).

Adheres strictly to GEES v1.0 (Pillar 5) and Plan 02 v1.3.
Provides:
1. CLAHE (Contrast Limited Adaptive Histogram Equalization) for reflection & shadow correction.
2. Front-camera selfie mirror detection and horizontal flip correction.
3. Specular glare reduction on machine acrylic and glass panels.
"""

from typing import Any, Dict, Optional, Tuple, cast
import numpy as np

from core_platform.app.skills.base import BaseSkill

try:
    import cv2
    _HAS_OPENCV = True
except ImportError:
    cv2 = None
    _HAS_OPENCV = False


class ImageEnhancerSkill(BaseSkill):
    """Computer vision enhancement skill for lighting, reflection, and mirror normalization."""

    def __init__(self) -> None:
        """Initialize ImageEnhancerSkill."""
        super().__init__(skill_name="image_enhancer")
        self._clahe_clip_limit: float = 2.0
        self._clahe_grid_size: Tuple[int, int] = (8, 8)

    async def initialize(self) -> None:
        """Initialize OpenCV or fallback image processing pipeline."""
        self._initialized = True

    def is_available(self) -> bool:
        """Report availability of the image enhancement engine."""
        return True

    async def enhance_contrast_clahe(self, image_bgr: np.ndarray) -> np.ndarray:
        """Apply CLAHE lighting and contrast normalization to an image.

        Args:
            image_bgr: Input BGR image as numpy array.

        Returns:
            Enhanced BGR image array with balanced dynamic range.
        """
        await self.ensure_initialized()

        if _HAS_OPENCV and cv2 is not None:
            # Convert BGR to LAB color space
            lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
            l_channel, a_channel, b_channel = cv2.split(lab)

            # Apply CLAHE to L (Lightness) channel
            clahe = cv2.createCLAHE(
                clipLimit=self._clahe_clip_limit,
                tileGridSize=self._clahe_grid_size,
            )
            cl = clahe.apply(l_channel)

            # Merge channels back and convert to BGR
            enhanced_lab = cv2.merge((cl, a_channel, b_channel))
            return cast(np.ndarray, cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR))

        # Pure numpy histogram normalization fallback if OpenCV is unavailable
        img_float = image_bgr.astype(np.float32)
        min_val = np.min(img_float)
        max_val = np.max(img_float)
        if max_val > min_val:
            normalized = ((img_float - min_val) / (max_val - min_val)) * 255.0
            return normalized.astype(np.uint8)
        return image_bgr

    async def correct_selfie_mirror(
        self,
        image_bgr: np.ndarray,
        force_flip: bool = False,
        exif_orientation: Optional[int] = None,
    ) -> Tuple[np.ndarray, bool]:
        """Detect and correct front-camera selfie horizontal mirroring.

        Args:
            image_bgr: Input BGR image array.
            force_flip: If True, forces horizontal flip regardless of heuristic.
            exif_orientation: Optional EXIF orientation tag (2, 4, 5, 7 indicate mirrored).

        Returns:
            Tuple of (corrected_image: np.ndarray, was_flipped: bool).
        """
        await self.ensure_initialized()

        should_flip = force_flip
        # Check standard EXIF mirrored orientation flags (2=Flip LR, 4=Flip TB, 5=Transpose, 7=Transverse)
        if exif_orientation in (2, 4, 5, 7):
            should_flip = True

        if should_flip:
            if _HAS_OPENCV and cv2 is not None:
                flipped = cv2.flip(image_bgr, 1)
            else:
                flipped = np.fliplr(image_bgr)
            return flipped, True

        return image_bgr, False

    async def suppress_panel_glare(self, image_bgr: np.ndarray) -> np.ndarray:
        """Attenuate bright specular glare from machine acrylic or LED glass panels.

        Args:
            image_bgr: Input BGR image array.

        Returns:
            Image array with attenuated bright glare spots.
        """
        await self.ensure_initialized()

        if _HAS_OPENCV and cv2 is not None:
            gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
            # Find extreme highlight mask (> 240 brightness)
            _, glare_mask = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
            # Dilate mask slightly to cover glare halo
            kernel = np.ones((3, 3), np.uint8)
            dilated_mask = cv2.dilate(glare_mask, kernel, iterations=1)
            # Inpaint bright glare spots
            inpainted = cv2.inpaint(image_bgr, dilated_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
            return cast(np.ndarray, inpainted)

        # Fast fallback: clamp highlights
        return cast(np.ndarray, np.clip(image_bgr, 0, 240).astype(np.uint8))

    def get_health_status(self) -> Dict[str, Any]:
        """Return operational metadata for health heartbeat."""
        status = super().get_health_status()
        status["opencv_accelerated"] = _HAS_OPENCV
        status["clahe_clip_limit"] = self._clahe_clip_limit
        return status
