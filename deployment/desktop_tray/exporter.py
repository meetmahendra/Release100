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
Dynamic 1-Click Audit Log Packager for Windows Desktop.

Adheres strictly to Plan 05 v1.2 and GEES v1.0.
Exports SHA-256 chained audit files (.jsonl, .csv, .html) into a single
standard compliance archive on the Windows Desktop.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Optional, Tuple
import zipfile

from core_platform.app.config import settings


class AuditExporter:
    """Exports partitioned audit files to desktop archive."""

    def __init__(self, audit_dir: Optional[Path] = None, destination_dir: Optional[Path] = None) -> None:
        """Initialize exporter with source audit directory and target destination.

        Args:
            audit_dir: Path to audit log storage.
            destination_dir: Path to export target directory (defaults to Desktop).
        """
        self.audit_dir = audit_dir or Path(settings.AUDIT_DIR)
        if destination_dir:
            self.destination_dir = destination_dir
        else:
            desktop = Path.home() / "Desktop"
            self.destination_dir = desktop if desktop.exists() else Path(".")

    def export(self) -> Tuple[bool, str, int]:
        """Export all audit partitions into a compressed ZIP file on Desktop.

        Returns:
            Tuple of (success: bool, zip_path_or_error: str, file_count: int).
        """
        if not self.audit_dir.exists():
            return False, f"Audit directory {self.audit_dir} does not exist", 0

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        zip_name = f"Release100_Audit_Export_{settings.KIOSK_ID}_{timestamp}.zip"
        target_zip = self.destination_dir / zip_name

        file_count = 0
        try:
            with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(self.audit_dir):
                    for file in files:
                        full_path = Path(root) / file
                        rel_path = full_path.relative_to(self.audit_dir)
                        zipf.write(full_path, arcname=str(rel_path))
                        file_count += 1

            if file_count == 0:
                # Still valid empty zip created, or note no records
                return True, str(target_zip.resolve()), 0

            return True, str(target_zip.resolve()), file_count
        except Exception as e:
            return False, f"Failed to package audit archive: {e}", 0
