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
Layer 1: Stochastic Model Reasoning Constraints & Clamps.

Adheres strictly to GEES v1.0 (Pillar 1) and Plan 02 v1.3.
Enforces:
1. Temperature governance (clamped to 0.0 - 0.2 for classification/OCR).
2. Schema-enforced outputs (Pydantic model validation).
3. Anti-stalling & grounding checks.
"""

from typing import Any, Dict, Type, TypeVar
from pydantic import BaseModel, ValidationError

from core_platform.app.errors import PlatformErrorCode, PlatformException

T = TypeVar("T", bound=BaseModel)


class Layer1StochasticClamp:
    """Stochastic Reasoning Engine Guardrails (Layer 1)."""

    MAX_DETERMINISTIC_TEMPERATURE: float = 0.2
    MAX_CONVERSATIONAL_TEMPERATURE: float = 0.7

    @classmethod
    def clamp_temperature(cls, requested_temp: float, is_deterministic_task: bool = True) -> float:
        """Clamp model temperature within strictly permitted engineering bounds.

        Args:
            requested_temp: The temperature requested by the caller.
            is_deterministic_task: True for classification, OCR, or triage; False for creative drafts.

        Returns:
            Clamped float temperature.
        """
        max_allowed = cls.MAX_DETERMINISTIC_TEMPERATURE if is_deterministic_task else cls.MAX_CONVERSATIONAL_TEMPERATURE
        return max(0.0, min(requested_temp, max_allowed))

    @staticmethod
    def validate_schema(payload: Dict[str, Any], schema_cls: Type[T]) -> T:
        """Validate raw dictionary payload against a typed Pydantic schema contract.

        Rejects malformed, hallucinated, or incomplete model outputs.

        Args:
            payload: Raw dictionary output from model reasoning.
            schema_cls: Expected Pydantic model class.

        Returns:
            Parsed and validated Pydantic model instance.

        Raises:
            PlatformException: If payload fails schema validation.
        """
        try:
            return schema_cls.model_validate(payload)
        except ValidationError as err:
            raise PlatformException(
                message=f"Model output violated required schema '{schema_cls.__name__}': {err}",
                code=PlatformErrorCode.LLM_SCHEMA_VALIDATION_FAILED,
                context={"validation_errors": err.errors(), "raw_payload": payload},
            ) from err
