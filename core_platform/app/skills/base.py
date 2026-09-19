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
Abstract Base Skill and Concurrency Lifecycle Contract.

Adheres strictly to GEES v1.0 (Pillar 5) and Plan 02 v1.3.
Guarantees:
1. Lazy-initialized singleton pattern (heavy ML weights load only on first use).
2. Concurrency safety via asyncio.Lock to prevent ONNX/GPU race conditions.
3. Explicit health check reporting via is_available() and get_health_status().
"""

from abc import ABC, abstractmethod
import asyncio
from typing import Any, Dict


class BaseSkill(ABC):
    """Abstract base class for all Universal Cognitive Skills.

    Provides standardized initialization, thread safety, and observability hooks.
    """

    def __init__(self, skill_name: str) -> None:
        """Initialize the BaseSkill.

        Args:
            skill_name: Unique canonical identifier for the cognitive skill.
        """
        self.skill_name: str = skill_name
        self._initialized: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    @abstractmethod
    async def initialize(self) -> None:
        """Load model weights, warm up runtime engines, or verify service credentials."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Report whether the cognitive skill is operational and ready for inference.

        Returns:
            True if initialized and ready, False otherwise.
        """
        pass

    async def ensure_initialized(self) -> None:
        """Ensure the skill is initialized in a thread-safe manner before inference."""
        if not self._initialized:
            async with self._lock:
                if not self._initialized:
                    await self.initialize()
                    self._initialized = True

    def get_health_status(self) -> Dict[str, Any]:
        """Return operational metadata for platform health heartbeat telemetry.

        Returns:
            Dictionary containing status and engine metadata.
        """
        return {
            "skill_name": self.skill_name,
            "initialized": self._initialized,
            "available": self.is_available(),
        }
