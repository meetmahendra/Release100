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
Unit Tests: High Concurrency Stress & ACID Transaction Rollbacks (GEES v2.0).

Tests:
1. 20-Thread Multi-Cartridge Concurrent Read/Write stress under SQLite WAL.
2. ACID Unit-of-Work Rollback verification on fault injection.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, select

from typing import Any, cast

from apps.mail_organizer.database.db_service import MailDatabaseService
from apps.temperature_marker.database.db_service import DatabaseService as TMDatabaseService
from core_platform.app.db.manager import DatabaseManager
from core_platform.app.plugin_engine.loader import PluginLoader
from tests.fixtures.polyglot_reporter import PolyglotTelemetryCollector
from tests.fixtures.portable_db_manager import PortableDatabaseManager


def test_20_thread_multi_cartridge_concurrency_stress(
    tmp_path: Path,
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Stress test 20 concurrent threads writing check-ins and emails simultaneously without lock errors."""
    t_start = time.perf_counter()
    db_url = portable_db_manager.get_sqlite_url(f"stress_wal_{tmp_path.name}.db")

    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(db_url)
    loader = PluginLoader(enabled_apps=["temperature_marker", "mail_organizer"])
    loaded_apps = loader.load_all()

    tm_app: Any = loaded_apps["temperature_marker"]
    mail_app: Any = loaded_apps["mail_organizer"]

    # Pre-register test employee
    tm_app.db_service.register_employee(
        emp_code="EMP-STRESS-01",
        full_name="Stress Operator",
        phone_number="+919800998877",
        assigned_kiosk_id="KIOSK-STRESS",
    )

    num_workers = 20
    results = []

    def execute_worker_transaction(worker_idx: int) -> bool:
        t0 = time.perf_counter()
        try:
            # 1. Record Attendance
            att = tm_app.db_service.record_attendance(
                correlation_id=f"corr-stress-{worker_idx}",
                emp_code="EMP-STRESS-01",
                kiosk_id="KIOSK-STRESS",
                face_confidence=0.92,
                gps_distance_meters=15.0,
                geofence_verified=True,
                chiller_temp_c=3.5,
                haccp_compliant=True,
                haccp_status="SAFE_RANGE",
            )
            # 2. Store Email
            em = mail_app.db_service.store_email(
                gmail_id=f"msg_stress_{worker_idx}",
                thread_id=f"th_stress_{worker_idx}",
                subject=f"Stress Test Email {worker_idx}",
                sender="stress@canectar.com",
            )
            ok = bool(att and em)
            polyglot_reporter.log_action(
                cartridge_id="temperature_marker + mail_organizer",
                paradigm="PARADIGM_A",
                dialect="sqlite_wal",
                action_name=f"concurrency_worker_{worker_idx}_tx",
                status="PASS" if ok else "FAIL",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                records_affected=2,
            )
            return ok
        except Exception as exc:
            polyglot_reporter.log_action(
                cartridge_id="temperature_marker + mail_organizer",
                paradigm="PARADIGM_A",
                dialect="sqlite_wal",
                action_name=f"concurrency_worker_{worker_idx}_tx",
                status="FAIL",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                error_message=str(exc),
            )
            return False

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(execute_worker_transaction, i) for i in range(num_workers)]
        for f in as_completed(futures):
            results.append(f.result())

    # All 20 threads must complete successfully with 0 deadlocks
    assert all(results) is True
    assert len(results) == num_workers

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_CONCURRENCY_20_THREADS",
        name="20-Thread Multi-Cartridge Concurrency Stress (Zero Deadlocks)",
        cartridge_id="temperature_marker + mail_organizer",
        paradigm="PARADIGM_A",
        primary_dialect="sqlite_wal",
        status="PASS",
        duration_ms=(time.perf_counter() - t_start) * 1000.0,
    )

    db_mgr.shutdown()
    DatabaseManager.reset_instance()


def test_acid_unit_of_work_rollback_on_fault(
    tmp_path: Path,
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify that simulated mid-flight exceptions roll back 100% of transaction (zero orphaned rows)."""
    t_start = time.perf_counter()
    db_url = portable_db_manager.get_sqlite_url(f"acid_rollback_{tmp_path.name}.db")

    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(db_url)
    factory = db_mgr.get_primary_factory()

    meta = MetaData()
    tbl_accounts = Table("accounts", meta, Column("id", Integer, primary_key=True), Column("balance", Integer))
    tbl_audit = Table("transfers", meta, Column("id", Integer, primary_key=True), Column("amount", Integer))
    meta.create_all(bind=factory.get_engine())

    # Initial deposit
    with factory.session_scope() as session:
        session.execute(tbl_accounts.insert().values(id=1, balance=500))

    # Multi-step transactional operation with injected fault
    t0 = time.perf_counter()
    tx_failed_cleanly = False
    try:
        with factory.session_scope() as session:
            # Step 1: Deduct balance
            session.execute(tbl_accounts.update().where(tbl_accounts.c.id == 1).values(balance=400))
            # Step 2: Log audit transfer
            session.execute(tbl_audit.insert().values(id=101, amount=100))
            # Step 3: Simulated mid-flight crash / power outage / network failure
            raise RuntimeError("CRITICAL_SIMULATED_NETWORK_FAULT_MID_TRANSACTION")
    except RuntimeError:
        tx_failed_cleanly = True

    assert tx_failed_cleanly is True

    # VERIFY ZERO ORPHANED ROWS: Balance must still be 500, and transfers must be EMPTY
    with factory.session_scope() as session:
        bal = session.execute(select(tbl_accounts.c.balance).where(tbl_accounts.c.id == 1)).scalar()
        transfer_count = session.execute(select(tbl_audit.c.id)).all()
        assert bal == 500  # Rolled back successfully!
        assert len(transfer_count) == 0  # Zero orphaned audit records!

    polyglot_reporter.log_action(
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        dialect="sqlite_wal",
        action_name="acid_unit_of_work_rollback_verification",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        query_sql="UPDATE accounts ...; INSERT INTO transfers ...; -> ROLLBACK [0 ORPHANS]",
    )

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_ACID_ROLLBACK_VERIFICATION",
        name="ACID Transaction Unit-of-Work Rollback (Zero Orphaned Records)",
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        primary_dialect="sqlite_wal",
        status="PASS",
        duration_ms=(time.perf_counter() - t_start) * 1000.0,
    )

    db_mgr.shutdown()
    DatabaseManager.reset_instance()
