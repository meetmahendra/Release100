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

"""Synthetic Unit Tests for ApplicationRegistry."""

from pathlib import Path
import pytest

from core_platform.app.apps_registry import ApplicationRegistry
from core_platform.app.config import settings


def test_apps_registry_discovery() -> None:
    """ApplicationRegistry must discover both temperature_marker and mail_organizer cartridges."""
    registry = ApplicationRegistry.get_instance()
    apps = registry.get_installed_applications()

    app_names = [a.app_name for a in apps]
    assert "temperature_marker" in app_names
    assert "mail_organizer" in app_names

    # Check active status reflects ENABLED_APPLICATIONS
    for a in apps:
        if a.app_name in settings.ENABLED_APPLICATIONS:
            assert a.is_active is True
            assert a.to_dict()["status"] == "ACTIVE"


def test_apps_registry_summary() -> None:
    """ApplicationRegistry summary must report correct counts and arrays."""
    registry = ApplicationRegistry.get_instance()
    summary = registry.get_summary()

    assert "total_installed" in summary
    assert "active_count" in summary
    assert "active_apps" in summary
    assert summary["total_installed"] >= 2
    assert "temperature_marker" in summary["active_apps"]
    assert "mail_organizer" in summary["active_apps"]


def test_apps_registry_dynamic_toggle() -> None:
    """Registry must allow dynamic enable and disable without errors."""
    registry = ApplicationRegistry.get_instance()
    test_app = "temperature_marker"

    orig_status = registry.is_app_active(test_app)
    # Toggle off
    if orig_status:
        disabled = registry.disable_application(test_app)
        assert disabled is True
        assert registry.is_app_active(test_app) is False

        # Toggle back on
        enabled = registry.enable_application(test_app)
        assert enabled is True
        assert registry.is_app_active(test_app) is True
