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

"""Synthetic Unit Tests for SkillRegistry (Plan 02 v1.3)."""

import pytest

from core_platform.app.errors import SkillExecutionError
from core_platform.app.skills.registry import SkillRegistry, get_platform_skill


def test_skill_registry_singleton() -> None:
    """SkillRegistry must return same instance on multiple calls."""
    reg1 = SkillRegistry.get_instance()
    reg2 = SkillRegistry.get_instance()
    assert reg1 is reg2


def test_skill_registry_get_default_skills() -> None:
    """All 4 standard skills must resolve cleanly."""
    registry = SkillRegistry.get_instance()
    for skill_name in ["geofencing", "image_enhancer", "display_ocr", "face_recognizer"]:
        skill = registry.get_skill(skill_name)
        assert skill is not None
        assert skill.skill_name == skill_name


def test_skill_registry_convenience_helper() -> None:
    """Global get_platform_skill helper must resolve registered skill."""
    ocr_skill = get_platform_skill("display_ocr")
    assert ocr_skill.skill_name == "display_ocr"


def test_skill_registry_unregistered_skill_raises() -> None:
    """Requesting an unregistered skill must raise SkillExecutionError."""
    registry = SkillRegistry.get_instance()
    with pytest.raises(SkillExecutionError) as exc_info:
        registry.get_skill("non_existent_skill_xyz")
    assert "not registered" in str(exc_info.value)


def test_skill_registry_get_all_health_statuses() -> None:
    """Health statuses must be collected for all registered skills."""
    registry = SkillRegistry.get_instance()
    statuses = registry.get_all_health_statuses()
    assert "display_ocr" in statuses
    assert "face_recognizer" in statuses
    assert "geofencing" in statuses
    assert "image_enhancer" in statuses
