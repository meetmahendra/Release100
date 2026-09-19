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
Skill Registry and Dependency Injection Dispatcher (`SkillRegistry`).

Adheres strictly to GEES v1.0 (Pillar 5) and Plan 02 v1.3.
Provides:
1. Central catalog of all platform cognitive skills.
2. Singleton skill management with lazy loading.
3. ctx.get_skill("skill_name") resolution for ultra-lean domain cartridges.
"""

from typing import Any, Dict, Optional, Type
import threading

from core_platform.app.errors import PlatformErrorCode, SkillExecutionError
from core_platform.app.skills.base import BaseSkill
from core_platform.app.skills.geofencing import GeofencingSkill
from core_platform.app.skills.image_enhancer import ImageEnhancerSkill
from core_platform.app.skills.display_ocr import DisplayOCRSkill
from core_platform.app.skills.face_recognizer import FaceRecognizerSkill


class SkillRegistry:
    """Thread-safe central registry for platform cognitive skills."""

    _instance: Optional["SkillRegistry"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        """Retrieve singleton instance of SkillRegistry."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        """Initialize registry and register default platform skills."""
        self._skills: Dict[str, BaseSkill] = {}
        self._skill_classes: Dict[str, Type[BaseSkill]] = {
            "geofencing": GeofencingSkill,
            "image_enhancer": ImageEnhancerSkill,
            "display_ocr": DisplayOCRSkill,
            "face_recognizer": FaceRecognizerSkill,
        }

    def register_skill(self, skill_name: str, skill_instance: BaseSkill) -> None:
        """Register a custom or pre-configured skill instance.

        Args:
            skill_name: Unique identifier for the skill.
            skill_instance: BaseSkill implementation instance.
        """
        with self._lock:
            self._skills[skill_name] = skill_instance

    def get_skill(self, skill_name: str) -> BaseSkill:
        """Retrieve a cognitive skill by name, creating the singleton if necessary.

        Args:
            skill_name: Canonical skill identifier (e.g. 'display_ocr', 'geofencing').

        Returns:
            BaseSkill instance.

        Raises:
            SkillExecutionError: If the requested skill name is not registered.
        """
        with self._lock:
            if skill_name in self._skills:
                return self._skills[skill_name]

            if skill_name in self._skill_classes:
                skill_cls = self._skill_classes[skill_name]
                instance = skill_cls()  # type: ignore[call-arg]
                self._skills[skill_name] = instance
                return instance

            raise SkillExecutionError(
                message=f"Cognitive skill '{skill_name}' is not registered in SkillRegistry.",
                code=PlatformErrorCode.UNAUTHORIZED_ACTION_ATTEMPT,
                context={"requested_skill": skill_name, "available_skills": list(self._skill_classes.keys())},
            )

    def get_all_health_statuses(self) -> Dict[str, Any]:
        """Collect operational health statuses across all registered skills.

        Returns:
            Dictionary of skill operational statuses for /health API.
        """
        statuses = {}
        for name, skill_cls in self._skill_classes.items():
            skill = self.get_skill(name)
            statuses[name] = skill.get_health_status()
        return statuses


# Convenience function for cartridges
def get_platform_skill(skill_name: str) -> BaseSkill:
    """Global helper allowing domain cartridges to request skills via ctx.get_skill()."""
    return SkillRegistry.get_instance().get_skill(skill_name)
