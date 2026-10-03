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
Platform Structured Error Taxonomy & Domain Exception Hierarchy.

Adheres to GEES v1.0 (Pillar 1 & 5) and Plan 02 v1.3.
Provides explicit machine-readable error codes across safety gates,
cognitive skills, and telemetry audit streams.
"""

from enum import Enum
from typing import Any, Dict, Optional


class PlatformErrorCode(str, Enum):
    """Machine-readable error codes for logging, auditing, and UI triage."""

    # Layer 0: Pre-Execution Safety & Sanity Violations
    SAFETY_PHYSICAL_BOUND_VIOLATION = "E-SAFE-001"  # Sensor reading physically impossible
    SAFETY_GEOFENCE_VIOLATION = "E-SAFE-002"  # GPS distance exceeds permitted radius
    SAFETY_TAMPER_DETECTED = "E-SAFE-003"  # Hash chain or timestamp manipulation
    SAFETY_RATE_LIMIT_EXCEEDED = "E-SAFE-004"  # Per-sender token bucket limit exceeded
    SAFETY_UNAUTHORIZED_OPERATOR = "E-SAFE-005"  # Operator not registered or pending approval

    # Layer 1: Stochastic Model & AI Reasoning Failures
    LLM_PROVIDER_UNREACHABLE = "E-LLM-001"  # Network timeout or quota exhaustion
    LLM_SCHEMA_VALIDATION_FAILED = "E-LLM-002"  # Output failed Pydantic schema validation
    OCR_READING_UNREADABLE = "E-OCR-001"  # Both local and cloud OCR failed to resolve digits
    BIOMETRIC_NO_FACE_DETECTED = "E-BIO-001"  # Zero faces detected in frame
    BIOMETRIC_MULTIPLE_FACES = "E-BIO-002"  # More than one face in reference frame

    # Layer 2: Post-Execution Boundary & Quality Gate
    CONFIDENCE_BELOW_THRESHOLD = "E-CONF-001"  # Confidence < 85%, diverted to Admin Approval
    UNAUTHORIZED_ACTION_ATTEMPT = "E-AUTH-001"  # Role or app permission denied by RBAC
    DESTRUCTIVE_COMMAND_INTERCEPTED = "E-DEST-001"  # Intercepted unauthorized deletion or drop

    # Downstream Persistence & Edge Sync
    DOWNSTREAM_SYNC_FAILURE = "E-DOWN-001"  # External REST/DB/Sheets offline (queued in Outbox)
    DATABASE_MIGRATION_ERROR = "E-DB-001"  # Alembic schema upgrade failed


class PlatformException(Exception):
    """
    Base domain exception for the Release100 platform.

    Carries a structured error code, contextual metadata, and supports causal chaining.
    """

    def __init__(
        self,
        message: str,
        code: PlatformErrorCode,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize the PlatformException.

        Args:
            message: Human-readable explanation of the error.
            code: Standardized PlatformErrorCode.
            context: Optional dictionary containing debugging metadata.
        """
        super().__init__(f"[{code.value}] {message}")
        self.message = message
        self.code = code
        self.context = context or {}


class SafetyGateViolation(PlatformException):
    """Raised when a hard safety rule (Layer 0 or Layer 2) is violated."""

    pass


class SkillExecutionError(PlatformException):
    """Raised when a cognitive skill encounters an unrecoverable failure."""

    pass


class LLMProviderError(PlatformException):
    """Raised when an LLM or decision provider encounters an unrecoverable failure."""

    def __init__(
        self,
        message: str,
        code: PlatformErrorCode = PlatformErrorCode.LLM_PROVIDER_UNREACHABLE,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message=message, code=code, context=context)


class DownstreamSyncError(PlatformException):
    """Raised when a downstream gateway fails to transmit data."""

    pass
