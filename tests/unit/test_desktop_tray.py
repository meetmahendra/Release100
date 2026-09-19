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

"""Synthetic Unit Tests for Dynamic Windows Desktop Tray & Audit Exporter."""

from pathlib import Path
from deployment.desktop_tray.exporter import AuditExporter
from deployment.desktop_tray.main_tray import DesktopTrayApp


def test_audit_exporter_packaging(tmp_path: Path) -> None:
    """AuditExporter must package partitioned audit files into a valid ZIP archive."""
    audit_dir = tmp_path / "audit_logs"
    audit_dir.mkdir(parents=True)
    (audit_dir / "audit_log.jsonl").write_text('{"event": "test"}\n', encoding="utf-8")
    (audit_dir / "audit_log.csv").write_text("seq,hash\n1,abc\n", encoding="utf-8")

    export_dest = tmp_path / "desktop_export"
    export_dest.mkdir(parents=True)

    exporter = AuditExporter(audit_dir=audit_dir, destination_dir=export_dest)
    success, zip_path, count = exporter.export()

    assert success is True
    assert count == 2
    assert Path(zip_path).exists()
    assert Path(zip_path).name.endswith(".zip")


def test_desktop_tray_app_initialization() -> None:
    """DesktopTrayApp must instantiate without error and handle actions gracefully."""
    shutdown_called = False

    def on_shutdown() -> None:
        nonlocal shutdown_called
        shutdown_called = True

    tray_app = DesktopTrayApp(on_shutdown=on_shutdown)
    assert tray_app.on_shutdown is not None

    # Test exit callback
    tray_app.exit_application()
    assert shutdown_called is True
