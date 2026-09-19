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

"""Layer 1 Dual-Engine Display OCR Node."""

import logging
from typing import Any
from apps.temperature_marker.graph.state import TemperatureMarkerState
from core_platform.app.errors import PlatformErrorCode
from core_platform.app.skills.display_ocr import DisplayOCRSkill
from core_platform.app.skills.registry import get_platform_skill

logger = logging.getLogger("apps.temperature_marker.ocr")


async def layer1_ocr_node(state: TemperatureMarkerState) -> TemperatureMarkerState:
    """Extract CaneBot chiller temperature readout using Dual-Engine OCR.

    Adheres strictly to GEES v1.0. If no image is provided, fails cleanly and diverts
    to review (Zero synthetic fallback injections).
    """
    # If temperature was already successfully extracted (e.g. by unified multimodal analysis)
    if state.get("ocr_confidence", 0.0) >= 0.85 and "chiller_temp_c" in state and state["chiller_temp_c"] is not None:
        return state

    raw_image = state.get("raw_image_bytes")
    ocr_skill: DisplayOCRSkill = get_platform_skill("display_ocr")  # type: ignore

    input_data: Any
    if not raw_image:
        # Check if caller explicitly provided a simulated reading payload for testing
        sim_reading = state.get("simulated_reading")
        if sim_reading and isinstance(sim_reading, dict):
            input_data = sim_reading
        else:
            state["ocr_confidence"] = 0.0
            state["chiller_temp_c"] = None
            state["layer_2_disposition"] = "diverted_to_review"
            state["error_code"] = PlatformErrorCode.OCR_READING_UNREADABLE.value
            state["error_message"] = (
                "No chiller display image provided. Please submit a clear photo of the CaneBot temperature display."
            )
            state["reply_message"] = (
                "⚠️ Missing Chiller Photo: Please submit a clear photo showing the chiller temperature display."
            )
            return state
    else:
        input_data = raw_image

    try:
        result = await ocr_skill.extract_display_reading(input_data)
        state["ocr_confidence"] = result.confidence
        state["ocr_engine_used"] = result.engine_used
        logger.info(
            "[OCR] Engine=%s, extracted_temp=%.2f°C, confidence=%.2f",
            result.engine_used,
            result.value,
            result.confidence,
        )

        if result.confidence < 0.85:
            state["chiller_temp_c"] = None
            state["layer_2_disposition"] = "diverted_to_review"
            state["error_code"] = PlatformErrorCode.CONFIDENCE_BELOW_THRESHOLD.value
            state["error_message"] = f"OCR confidence {result.confidence:.2f} is below 0.85 threshold."
        else:
            state["chiller_temp_c"] = result.value
    except Exception as err:
        state["ocr_confidence"] = 0.0
        state["chiller_temp_c"] = None
        state["layer_2_disposition"] = "diverted_to_review"
        state["error_code"] = PlatformErrorCode.OCR_READING_UNREADABLE.value
        state["error_message"] = f"Failed to extract chiller temperature: {err}"
        state["reply_message"] = (
            "⚠️ Temperature Unreadable: The digital display reading could not be detected. Please ensure the LED display is clearly visible without glare and re-send."
        )

    return state
