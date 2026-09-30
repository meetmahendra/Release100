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
Unit Tests for Cartridge DB Persistence Binding & Migration Utilities.

Adheres strictly to GEES v2.0 Dual-Engine Verification Regime (Engine A).
"""

from pathlib import Path
import pytest

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.temperature_marker.database.db_service import DatabaseService as TMDatabaseService
from core_platform.app.db.connection_factory import DatabaseConnectionFactory
from core_platform.app.db.migrations import DatabaseMigrationHelper


def test_database_migration_helper(tmp_path: Path) -> None:
    """Verify DatabaseMigrationHelper creates tables and inspects schema correctly."""
    db_file = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{db_file}"
    factory = DatabaseConnectionFactory(db_url)
    engine = factory.get_engine()

    from apps.temperature_marker.database.models import Base as TMBase
    from apps.mail_organizer.database.models import Base as MailBase

    created = DatabaseMigrationHelper.initialize_metadata_tables(
        engine=engine,
        metadata_list=[TMBase.metadata, MailBase.metadata],
        enable_sqlite_wal=True,
    )

    assert len(created) > 0
    assert "employees" in created
    assert "attendance_records" in created
    assert "mail_emails" in created

    existing = DatabaseMigrationHelper.get_existing_table_names(engine)
    assert "employees" in existing
    assert "mail_emails" in existing

    factory.dispose()


def test_temperature_marker_shared_engine_binding(tmp_path: Path) -> None:
    """Verify TemperatureMarker DatabaseService binds to a shared SQLAlchemy engine."""
    db_file = tmp_path / "tm_shared.db"
    db_url = f"sqlite:///{db_file}"
    factory = DatabaseConnectionFactory(db_url)
    engine = factory.get_engine()

    tm_service = TMDatabaseService(engine=engine)
    assert tm_service.engine is engine

    # Add an employee
    emp = tm_service.register_employee(
        emp_code="EMP_TEST_001",
        full_name="Test Operator",
        phone_number="+919876543210",
        assigned_kiosk_id="KIOSK-01",
    )
    assert emp is not None

    found = tm_service.get_employee_by_code("EMP_TEST_001")
    assert found is not None
    assert found.full_name == "Test Operator"

    tm_service.close()
    factory.dispose()


def test_mail_organizer_shared_engine_binding(tmp_path: Path) -> None:
    """Verify MailDatabaseService binds to a shared SQLAlchemy engine."""
    db_file = tmp_path / "mail_shared.db"
    db_url = f"sqlite:///{db_file}"
    factory = DatabaseConnectionFactory(db_url)
    engine = factory.get_engine()

    mail_service = MailDatabaseService(engine=engine)
    assert mail_service.engine is engine

    stored = mail_service.store_email(
        gmail_id="msg_test_001",
        thread_id="th_test_001",
        subject="Test Incident",
        sender="operator@example.com",
        to_recipients="manager@example.com",
        snippet="Chiller is running high",
    )
    assert stored is not None
    assert stored.gmail_id == "msg_test_001"

    fetched_list = mail_service.get_recent_emails(limit=10)
    assert len(fetched_list) > 0
    assert fetched_list[0]["gmail_id"] == "msg_test_001"
    assert fetched_list[0]["subject"] == "Test Incident"

    factory.dispose()

