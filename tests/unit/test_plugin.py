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

"""Synthetic Unit Tests for TemperatureMarkerApplication Plugin."""

from pathlib import Path
from apps.temperature_marker.plugin import TemperatureMarkerApplication, TemperatureMarkerConfig


def test_plugin_initialization(tmp_path: Path) -> None:
    """Plugin must instantiate cleanly with all wired dependencies."""
    db_file = tmp_path / "plugin_test.db"
    app = TemperatureMarkerApplication(db_url=f"sqlite:///{db_file}")

    assert app.app_id == "temperature_marker"
    assert app.name == "Apex Industrial Temperature & Attendance Marker"
    assert app.version == "1.3.0"
    assert app.config_schema == TemperatureMarkerConfig
    assert "operator" in app.required_roles
    assert "whatsapp" in app.supported_channels

    workflow = app.get_workflow()
    assert workflow is not None
