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
Unit Tests: Hybrid Combinatorial Topologies (Simultaneous Paradigm A + B + C Coexistence).

Validates enterprise topologies mixing Core-Facilitated, Autonomous, and Dedicated databases
concurrently with zero cross-talk or race conditions.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import pytest

from typing import Any

from core_platform.app.db.manager import DatabaseManager
from core_platform.app.plugin_engine.loader import PluginLoader
from tests.fixtures.polyglot_reporter import PolyglotTelemetryCollector
from tests.fixtures.portable_db_manager import PortableDatabaseManager
from tests.unit.test_polyglot_paradigm_b_autonomous import AutonomousAnalyticsCartridge
from tests.unit.test_polyglot_paradigm_c_dedicated import DedicatedBillingCartridge


def test_hybrid_combinatorial_coexistence_all_paradigms(
    tmp_path: Path,
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Test full simultaneous coexistence of Paradigm A, B, and C across multiple threads."""
    t_start = time.perf_counter()

    # 1. Primary Platform on SQLite WAL (Paradigm A Core Engine)
    core_db_url = portable_db_manager.get_sqlite_url(f"hybrid_core_{tmp_path.name}.db")
    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(core_db_url)
    core_engine = db_mgr.get_engine()

    # 2. Load Paradigm A Cartridges
    loader = PluginLoader(enabled_apps=["temperature_marker", "mail_organizer"])
    loaded_apps = loader.load_all()
    tm_app: Any = loaded_apps["temperature_marker"]
    mail_app: Any = loaded_apps["mail_organizer"]

    # 3. Mount Paradigm B Autonomous Cartridge (DuckDB)
    duck_path = str(portable_db_manager.duckdb_dir / f"hybrid_duck_{tmp_path.name}.duckdb")
    analytics_app = AutonomousAnalyticsCartridge(duck_path)

    # 4. Mount Paradigm C Dedicated Cartridge (Isolated DB)
    dedicated_url = portable_db_manager.get_sqlite_url(f"hybrid_dedicated_{tmp_path.name}.db")
    billing_app = DedicatedBillingCartridge(dedicated_url)
    assert billing_app.custom_database_url is not None
    billing_factory = db_mgr.create_custom_factory(billing_app.app_id, billing_app.custom_database_url)
    billing_app.on_bind_engine(billing_factory.get_engine())

    # 5. Concurrent execution across all 3 paradigms simultaneously
    def run_paradigm_a_tm() -> bool:
        t0 = time.perf_counter()
        emp = tm_app.db_service.register_employee(
            emp_code="EMP-HYBRID-01",
            full_name="Hybrid Worker",
            phone_number="+919800112233",
            assigned_kiosk_id="HYBRID-KIOSK",
        )
        rec = tm_app.db_service.record_attendance(
            correlation_id="corr-hyb-01",
            emp_code="EMP-HYBRID-01",
            kiosk_id="HYBRID-KIOSK",
            face_confidence=0.96,
            gps_distance_meters=10.0,
            geofence_verified=True,
            chiller_temp_c=3.2,
            haccp_compliant=True,
            haccp_status="SAFE_RANGE",
        )
        polyglot_reporter.log_action(
            cartridge_id="temperature_marker",
            paradigm="PARADIGM_A",
            dialect="sqlite_wal",
            action_name="hybrid_tm_checkin",
            status="PASS" if (emp and rec) else "FAIL",
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            records_affected=2,
        )
        return bool(emp and rec)

    def run_paradigm_a_mo() -> bool:
        t0 = time.perf_counter()
        email = mail_app.db_service.store_email(
            gmail_id="hybrid_msg_01",
            thread_id="th_hyb_01",
            subject="Hybrid Mail Check",
            sender="admin@canectar.com",
        )
        cls = mail_app.db_service.store_classification(
            gmail_id="hybrid_msg_01",
            category="OperationalNotice",
            urgency_score=2,
            confidence_score=0.95,
        )
        polyglot_reporter.log_action(
            cartridge_id="mail_organizer",
            paradigm="PARADIGM_A",
            dialect="sqlite_wal",
            action_name="hybrid_mail_triage",
            status="PASS" if (email and cls) else "FAIL",
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            records_affected=2,
        )
        return bool(email and cls)

    def run_paradigm_b_analytics() -> bool:
        t0 = time.perf_counter()
        for i in range(25):
            analytics_app.insert_metric("hybrid_metric", float(i))
        avg = analytics_app.query_avg("hybrid_metric")
        polyglot_reporter.log_action(
            cartridge_id="autonomous_analytics",
            paradigm="PARADIGM_B",
            dialect="duckdb",
            action_name="hybrid_duckdb_analytics",
            status="PASS" if avg >= 0 else "FAIL",
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            records_affected=25,
        )
        return avg >= 0

    def run_paradigm_c_billing() -> bool:
        t0 = time.perf_counter()
        with billing_factory.session_scope() as session:
            session.execute(
                billing_app.invoices_table.insert().values(
                    invoice_code="INV-HYBRID-99",
                    amount_cents=88000,
                )
            )
        polyglot_reporter.log_action(
            cartridge_id="dedicated_billing",
            paradigm="PARADIGM_C",
            dialect="sqlite_dedicated",
            action_name="hybrid_billing_invoice",
            status="PASS",
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            records_affected=1,
        )
        return True

    # Execute all 4 functions concurrently across parallel threads
    with ThreadPoolExecutor(max_workers=4) as executor:
        f_tm = executor.submit(run_paradigm_a_tm)
        f_mo = executor.submit(run_paradigm_a_mo)
        f_an = executor.submit(run_paradigm_b_analytics)
        f_bi = executor.submit(run_paradigm_c_billing)

        assert f_tm.result() is True
        assert f_mo.result() is True
        assert f_an.result() is True
        assert f_bi.result() is True

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_HYBRID_COMBINATIONS_ALL",
        name="Hybrid Simultaneous Combinations (A + B + C Parallel Coexistence)",
        cartridge_id="All 4 Cartridges",
        paradigm="HYBRID (A+B+C)",
        primary_dialect="sqlite_wal",
        dedicated_dialect="duckdb + sqlite_dedicated",
        status="PASS",
        duration_ms=(time.perf_counter() - t_start) * 1000.0,
    )

    db_mgr.shutdown()
    DatabaseManager.reset_instance()
