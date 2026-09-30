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
Unit Tests: Paradigm A (Core-Facilitated Multi-Cartridge Matrix).

Verifies that both Temperature Marker and Mail Organizer share the central platform
database engine across different real SQL engines (SQLite, PostgreSQL, MariaDB/MySQL) with zero schema collision.
"""

from pathlib import Path
import time
from typing import Any
import pytest
import uuid

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.temperature_marker.database.db_service import DatabaseService as TMDatabaseService
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.plugin_engine.loader import PluginLoader
from tests.fixtures.polyglot_reporter import PolyglotTelemetryCollector
from tests.fixtures.portable_db_manager import PortableDatabaseManager


@pytest.mark.parametrize("engine_type,db_getter", [
    ("sqlite_wal", lambda mgr, tmp: mgr.get_sqlite_url(f"paradigm_a_{tmp.name}.db")),
    ("sqlite_in_memory", lambda mgr, tmp: "sqlite:///:memory:"),
    ("postgresql", lambda mgr, tmp: mgr.get_postgresql_url()),
    ("mysql", lambda mgr, tmp: mgr.get_mysql_url()),
])
def test_paradigm_a_multi_cartridge_coexistence(
    engine_type: str,
    db_getter: Any,
    tmp_path: Path,
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Test Temperature Marker and Mail Organizer executing real operations on shared platform DB."""
    t_start = time.perf_counter()
    db_url = db_getter(portable_db_manager, tmp_path)

    # 1. Initialize Core DatabaseManager with target engine
    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(db_url)
    core_engine = db_mgr.get_engine()

    # 2. PluginLoader loads enabled cartridges & performs Centralized Kernel DDL
    loader = PluginLoader(enabled_apps=["temperature_marker", "mail_organizer"])
    loaded_apps = loader.load_all()

    tm_app: Any = loaded_apps["temperature_marker"]
    mail_app: Any = loaded_apps["mail_organizer"]

    # Verify both cartridges received the shared core engine
    assert tm_app.db_service.engine is core_engine
    assert mail_app.db_service.engine is core_engine

    polyglot_reporter.log_action(
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        dialect=engine_type,
        action_name="centralized_kernel_ddl_init_tables",
        status="PASS",
        duration_ms=(time.perf_counter() - t_start) * 1000.0,
        query_sql="DatabaseManager.init_tables() -> MetaData.create_all()",
    )

    unique_suffix = uuid.uuid4().hex[:6]
    emp_code = f"EMP-POLY-{unique_suffix}"
    phone_num = f"+9198{unique_suffix}12"
    gmail_msg_id = f"msg_poly_{unique_suffix}"

    # 3. Temperature Marker Real CRUD Operations
    t0 = time.perf_counter()
    emp = tm_app.db_service.register_employee(
        emp_code=emp_code,
        full_name=f"Rajesh Polyglot {unique_suffix}",
        phone_number=phone_num,
        assigned_kiosk_id="CANEBOT-PUNE-01",
        role="OPERATOR",
    )
    assert emp is not None
    assert emp.emp_code == emp_code

    polyglot_reporter.log_action(
        cartridge_id="temperature_marker",
        paradigm="PARADIGM_A",
        dialect=engine_type,
        action_name="register_employee",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=1,
        query_sql="INSERT INTO employees (emp_code, full_name, phone_number) VALUES (...)",
    )

    t0 = time.perf_counter()
    att_rec = tm_app.db_service.record_attendance(
        correlation_id=f"corr-poly-{unique_suffix}",
        emp_code=emp_code,
        kiosk_id="CANEBOT-PUNE-01",
        face_confidence=0.95,
        gps_distance_meters=12.5,
        geofence_verified=True,
        chiller_temp_c=3.4,
        haccp_compliant=True,
        haccp_status="SAFE_RANGE",
    )
    assert att_rec is not None
    assert att_rec.chiller_temp_c == 3.4

    polyglot_reporter.log_action(
        cartridge_id="temperature_marker",
        paradigm="PARADIGM_A",
        dialect=engine_type,
        action_name="record_attendance_and_haccp",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=1,
        query_sql="INSERT INTO attendance_records (correlation_id, chiller_temp_c, ...) VALUES (...)",
    )

    # 4. Mail Organizer Real CRUD Operations on SAME engine
    t0 = time.perf_counter()
    email = mail_app.db_service.store_email(
        gmail_id=gmail_msg_id,
        thread_id=f"th_poly_{unique_suffix}",
        subject=f"Polyglot Multi-DB Incident Alert {unique_suffix}",
        sender="field.supervisor@canectar.com",
        to_recipients="manager@canectar.com",
        snippet="Chiller temp is 3.4C nominal.",
    )
    assert email is not None
    assert email.gmail_id == gmail_msg_id

    polyglot_reporter.log_action(
        cartridge_id="mail_organizer",
        paradigm="PARADIGM_A",
        dialect=engine_type,
        action_name="store_email",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=1,
        query_sql="INSERT INTO mail_emails (gmail_id, subject, sender) VALUES (...)",
    )

    t0 = time.perf_counter()
    classification = mail_app.db_service.store_classification(
        gmail_id=gmail_msg_id,
        category="StatusUpdate",
        urgency_score=3,
        confidence_score=0.92,
        reasoning="Routine operational check-in confirmation.",
    )
    assert classification is not None
    assert classification.category == "StatusUpdate"

    polyglot_reporter.log_action(
        cartridge_id="mail_organizer",
        paradigm="PARADIGM_A",
        dialect=engine_type,
        action_name="store_classification",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=1,
        query_sql="INSERT INTO mail_classifications (gmail_id, category, urgency_score) VALUES (...)",
    )

    # 5. Verify Cross-Cartridge Querying & Consistency
    recent_emails = mail_app.db_service.get_recent_emails(limit=5)
    assert any(r["gmail_id"] == gmail_msg_id for r in recent_emails)

    found_emp = tm_app.db_service.get_employee_by_code(emp_code)
    assert found_emp is not None
    assert found_emp.full_name == f"Rajesh Polyglot {unique_suffix}"

    polyglot_reporter.record_topology_result(
        scenario_id=f"SCENARIO_PARADIGM_A_{engine_type.upper()}",
        name=f"Paradigm A Multi-Cartridge Coexistence ({engine_type})",
        cartridge_id="temperature_marker + mail_organizer",
        paradigm="PARADIGM_A",
        primary_dialect=engine_type,
        status="PASS",
        duration_ms=(time.perf_counter() - t_start) * 1000.0,
    )

    db_mgr.shutdown()
    DatabaseManager.reset_instance()
