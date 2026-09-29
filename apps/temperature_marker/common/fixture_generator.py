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

"""Fixture generator providing valid synthetic and real CaneBot photos for live testing."""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

logger = logging.getLogger("apps.temperature_marker.fixtures")


def generate_synthetic_gauge_jpeg(
    temperature: float,
    timestamp: Optional[str] = None,
    kiosk_id: str = "CANEBOT-PUNE-04",
) -> bytes:
    """Generate a realistic, lightweight CaneBot digital chiller gauge JPEG.

    Renders an industrial digital readout with the target temperature in Celsius
    and an imprinted camera watermark timestamp.

    Args:
        temperature: Chiller temperature value in Celsius.
        timestamp: Optional timestamp string. Defaults to current local date/time.
        kiosk_id: Kiosk station identifier for camera watermark branding.

    Returns:
        Valid JPEG byte stream (>0 bytes, starting with 0xFF 0xD8 0xFF).
    """
    width, height = 400, 200
    # Background chassis
    img = Image.new("RGB", (width, height), color=(20, 24, 28))
    draw = ImageDraw.Draw(img)

    # Outer metallic bezel
    draw.rectangle([(15, 15), (width - 15, height - 15)], fill=(12, 14, 16), outline=(80, 92, 105), width=3)
    # Inner digital LED display window
    draw.rectangle([(40, 40), (width - 40, height - 55)], fill=(0, 15, 5), outline=(0, 230, 60), width=2)

    # Top brand / monitor header
    draw.text((45, 20), f"CaneBot Industrial HACCP Monitor [{kiosk_id}]", fill=(170, 185, 200))

    # Center digital reading
    temp_text = f"{temperature:+.1f} °C" if temperature < 0 else f"{temperature:.1f} °C"
    draw.text((70, 65), temp_text, fill=(0, 255, 65))

    # Bottom camera watermark
    ts_val = timestamp or datetime.now().strftime("%d-%b-%Y %I:%M:%S %p")
    watermark_text = f"Shot on {kiosk_id} | {ts_val}"
    draw.text((20, height - 40), watermark_text, fill=(160, 165, 175))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def get_real_kiosk_fixture(name: str = "checkin") -> bytes:
    """Load a curated CaneBot kiosk photo fixture from disk.

    Args:
        name: Name of fixture ('checkin', 'enrollment', 'checkin2', etc.).

    Returns:
        JPEG bytes of the real photo fixture, or dynamically generated synthetic gauge.
    """
    candidate_paths = [
        Path("logs") / "0226_checkin1.jpg",
        Path("logs") / "0225_enrollment.jpg",
        Path("logs") / "0231_checkin2.jpg",
        Path("logs") / "0232_checkin3.jpg",
        Path("logs") / "0233_checkin4.jpg",
    ]

    for p in candidate_paths:
        if p.exists() and p.stat().st_size > 0:
            try:
                with open(p, "rb") as f:
                    data = f.read()
                if data.startswith(b"\xff\xd8\xff"):
                    return data
            except Exception as exc:
                logger.warning("Failed to load real photo fixture from %s: %s", p, exc)

    # Fallback to generated synthetic gauge if no fixture image is available
    return generate_synthetic_gauge_jpeg(3.5)
