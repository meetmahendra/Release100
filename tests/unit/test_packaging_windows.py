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

"""Synthetic Unit Tests for Windows Packaging & Installer Builder."""

from pathlib import Path
from deployment.packaging_windows.build_installer import WindowsInstallerBuilder


def test_windows_builder_prerequisites() -> None:
    """Builder must validate presence of spec, iss, and entrypoints."""
    builder = WindowsInstallerBuilder()
    valid, missing = builder.validate_prerequisites()
    assert valid is True
    assert len(missing) == 0


def test_windows_builder_dry_run() -> None:
    """Builder dry-run must return 0 without invoking compilers."""
    builder = WindowsInstallerBuilder()
    ret = builder.build(dry_run=True)
    assert ret == 0


def test_spec_and_iss_integrity() -> None:
    """Spec and Inno Setup files must contain required metadata and targets."""
    builder = WindowsInstallerBuilder()
    spec_content = builder.spec_file.read_text(encoding="utf-8")
    assert "canebot_fleet_roster.json" in spec_content
    assert "Release100" in spec_content
    assert "hiddenimports" in spec_content

    iss_content = builder.iss_file.read_text(encoding="utf-8")
    assert "Release100 Industrial Automation Platform" in iss_content
    assert "Release100_Setup_v1.3.0" in iss_content
    assert "Mahendra GURAV" in iss_content
