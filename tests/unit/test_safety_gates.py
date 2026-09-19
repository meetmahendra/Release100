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
Synthetic Unit Tests for 3-Tier Safety Architecture (GEES v1.0 Pillar 1).

Tests Layer 0 (Deterministic Pre-Gate), Layer 1 (Stochastic Clamps),
and Layer 2 (Post-Execution Gate).
"""

import math
import pytest
from pydantic import BaseModel, Field

from core_platform.app.errors import PlatformErrorCode, SafetyGateViolation, PlatformException
from core_platform.app.safety.layer0_pre_gate import Layer0PreExecutionGate
from core_platform.app.safety.layer1_stochastic_clamp import Layer1StochasticClamp
from core_platform.app.safety.layer2_post_gate import (
    Layer2PostExecutionGate,
    PostGateDisposition,
)


class SampleSchema(BaseModel):
    temperature_c: float
    unit: str = "C"
    confidence: float = Field(ge=0.0, le=1.0)


class TestLayer0PreExecutionGate:
    """Test suite for Layer 0 Pre-Execution Safety Gate."""

    def test_valid_physical_temperature(self) -> None:
        """Normal operational temperatures must pass physical bounding."""
        assert Layer0PreExecutionGate.validate_physical_temperature_bounds(3.2) is True
        assert Layer0PreExecutionGate.validate_physical_temperature_bounds(0.0) is True
        assert Layer0PreExecutionGate.validate_physical_temperature_bounds(100.0) is True

    def test_reject_impossible_low_temperature(self) -> None:
        """Temperatures below -20°C on retail ambient lines must raise SafetyGateViolation."""
        with pytest.raises(SafetyGateViolation) as exc_info:
            Layer0PreExecutionGate.validate_physical_temperature_bounds(-25.0)
        assert exc_info.value.code == PlatformErrorCode.SAFETY_PHYSICAL_BOUND_VIOLATION
        assert "violates physical sensor boundaries" in str(exc_info.value)

    def test_reject_impossible_high_temperature(self) -> None:
        """Temperatures exceeding 120°C must raise SafetyGateViolation."""
        with pytest.raises(SafetyGateViolation) as exc_info:
            Layer0PreExecutionGate.validate_physical_temperature_bounds(155.0)
        assert exc_info.value.code == PlatformErrorCode.SAFETY_PHYSICAL_BOUND_VIOLATION

    def test_reject_nan_inf_temperature(self) -> None:
        """NaN and Infinite values must be rejected instantly."""
        with pytest.raises(SafetyGateViolation):
            Layer0PreExecutionGate.validate_physical_temperature_bounds(float("nan"))
        with pytest.raises(SafetyGateViolation):
            Layer0PreExecutionGate.validate_physical_temperature_bounds(float("inf"))

    def test_haversine_distance_calculation(self) -> None:
        """Haversine math must accurately compute distance between two GPS coordinates."""
        # Phoenix Marketcity Pune coordinates
        kiosk_coord = (18.5621, 73.9168)
        # Point ~50 meters away
        user_coord = (18.5623, 73.9171)
        dist = Layer0PreExecutionGate.calculate_haversine_distance_meters(user_coord, kiosk_coord)
        assert 30.0 <= dist <= 60.0

    def test_geofence_within_bounds(self) -> None:
        """User within 100m geofence must pass."""
        kiosk_coord = (18.5621, 73.9168)
        user_coord = (18.5622, 73.9169)
        passed, dist = Layer0PreExecutionGate.validate_geofence(user_coord, kiosk_coord, max_radius_meters=100.0)
        assert passed is True
        assert dist <= 100.0

    def test_geofence_breach_rejection(self) -> None:
        """User outside permissible radius must raise SAFETY_GEOFENCE_VIOLATION."""
        kiosk_coord = (18.5621, 73.9168)
        # ~1 km away
        user_coord = (18.5700, 73.9250)
        with pytest.raises(SafetyGateViolation) as exc_info:
            Layer0PreExecutionGate.validate_geofence(user_coord, kiosk_coord, max_radius_meters=100.0)
        assert exc_info.value.code == PlatformErrorCode.SAFETY_GEOFENCE_VIOLATION
        assert "Geofence breach" in str(exc_info.value)

    def test_sanitize_input_text(self) -> None:
        """Must strip HTML and control characters."""
        raw = "<script>alert('pwn')</script>Hello <b>World</b>"
        clean = Layer0PreExecutionGate.sanitize_input_text(raw)
        assert clean == "Hello World"
        assert "<script>" not in clean


class TestLayer1StochasticClamp:
    """Test suite for Layer 1 Stochastic Reasoning Constraints."""

    def test_temperature_clamping(self) -> None:
        """Deterministic temperature must not exceed 0.2."""
        assert Layer1StochasticClamp.clamp_temperature(0.5, is_deterministic_task=True) == 0.2
        assert Layer1StochasticClamp.clamp_temperature(0.1, is_deterministic_task=True) == 0.1
        assert Layer1StochasticClamp.clamp_temperature(-0.1, is_deterministic_task=True) == 0.0

    def test_conversational_temperature_clamping(self) -> None:
        """Conversational temperature must not exceed 0.7."""
        assert Layer1StochasticClamp.clamp_temperature(0.9, is_deterministic_task=False) == 0.7
        assert Layer1StochasticClamp.clamp_temperature(0.6, is_deterministic_task=False) == 0.6

    def test_schema_validation_success(self) -> None:
        """Valid dictionary must parse into Pydantic schema."""
        payload = {"temperature_c": 3.4, "unit": "C", "confidence": 0.95}
        result = Layer1StochasticClamp.validate_schema(payload, SampleSchema)
        assert result.temperature_c == 3.4
        assert result.confidence == 0.95

    def test_schema_validation_failure(self) -> None:
        """Malformed dictionary must raise PlatformException with LLM_SCHEMA_VALIDATION_FAILED."""
        payload = {"temperature_c": "not_a_number"}
        with pytest.raises(PlatformException) as exc_info:
            Layer1StochasticClamp.validate_schema(payload, SampleSchema)
        assert exc_info.value.code == PlatformErrorCode.LLM_SCHEMA_VALIDATION_FAILED


class TestLayer2PostExecutionGate:
    """Test suite for Layer 2 Post-Execution Quality Gate."""

    def test_confidence_below_threshold_diverts(self) -> None:
        """Confidence < 85% must divert to Admin Review Gate."""
        is_pass, disposition, reason = Layer2PostExecutionGate.evaluate_confidence(0.72)
        assert is_pass is False
        assert disposition == PostGateDisposition.DIVERTED_TO_REVIEW
        assert "below required threshold" in reason

    def test_confidence_above_threshold_shadow_mode(self) -> None:
        """When DRY_RUN=True (default), confidence >= 85% reports SIMULATED_SHADOW."""
        is_pass, disposition, reason = Layer2PostExecutionGate.evaluate_confidence(0.92)
        assert is_pass is True
        assert disposition == PostGateDisposition.SIMULATED_SHADOW
        assert "Shadow Mode" in reason

    def test_intercept_destructive_commands(self) -> None:
        """Destructive keywords like 'DROP' or 'DELETE' must raise DESTRUCTIVE_COMMAND_INTERCEPTED."""
        with pytest.raises(SafetyGateViolation) as exc_info:
            Layer2PostExecutionGate.intercept_destructive_actions("drop_table_records", {})
        assert exc_info.value.code == PlatformErrorCode.DESTRUCTIVE_COMMAND_INTERCEPTED

        with pytest.raises(SafetyGateViolation):
            Layer2PostExecutionGate.intercept_destructive_actions("delete_all_attendance", {})

    def test_permit_safe_actions(self) -> None:
        """Safe non-destructive actions must pass inspection."""
        assert Layer2PostExecutionGate.intercept_destructive_actions("log_temperature", {"temp": 3.2}) is True
        assert Layer2PostExecutionGate.intercept_destructive_actions("record_attendance", {}) is True

    def test_confidence_above_threshold_autonomous(self) -> None:
        """When DRY_RUN=False and execution_mode=autonomous, reports APPROVED_AUTONOMOUS."""
        from core_platform.app.config import settings
        orig_dry = settings.DRY_RUN
        orig_mode = settings.EXECUTION_MODE
        try:
            settings.DRY_RUN = False
            settings.EXECUTION_MODE = "autonomous"
            is_pass, disposition, reason = Layer2PostExecutionGate.evaluate_confidence(0.92)
            assert is_pass is True
            assert disposition == PostGateDisposition.APPROVED_AUTONOMOUS
            assert "Approved for autonomous commit" in reason
        finally:
            settings.DRY_RUN = orig_dry
            settings.EXECUTION_MODE = orig_mode

    def test_sanitize_input_text_empty(self) -> None:
        """Empty or None text must sanitize to empty string."""
        assert Layer0PreExecutionGate.sanitize_input_text(None) == ""
        assert Layer0PreExecutionGate.sanitize_input_text("") == ""

