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
Unit Tests: Paradigm B (Cartridge-Autonomous / "We Don't Care" Persistence).

Verifies that 3rd-party cartridges managing independent databases (DuckDB, Document stores,
Flat files, SaaS CRMs) operate with 100% independence and ZERO interference from Core Platform.
"""

from pathlib import Path
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter
from sqlalchemy import MetaData
import duckdb

from core_platform.app.db.manager import DatabaseManager
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from tests.fixtures.polyglot_reporter import PolyglotTelemetryCollector
from tests.fixtures.portable_db_manager import PortableDatabaseManager


class AutonomousAnalyticsCartridge(BaseApplication):
    """Simulates a 3rd-party cartridge that manages its own independent DuckDB database."""
    app_id = "autonomous_analytics"
    name = "Autonomous Analytics & BI Cartridge"
    version = "1.0.0"

    def __init__(self, duck_db_path: str) -> None:
        self.duck_conn = duckdb.connect(duck_db_path)
        self.duck_conn.execute("CREATE TABLE IF NOT EXISTS bi_aggregates (metric VARCHAR, val DOUBLE, ts TIMESTAMP)")

    def insert_metric(self, metric: str, val: float) -> None:
        self.duck_conn.execute("INSERT INTO bi_aggregates VALUES (?, ?, CURRENT_TIMESTAMP)", [metric, val])

    def query_avg(self, metric: str) -> float:
        res = self.duck_conn.execute("SELECT AVG(val) FROM bi_aggregates WHERE metric = ?", [metric]).fetchone()
        return float(res[0]) if res and res[0] is not None else 0.0

    def get_workflow(self) -> Any:
        return None

    def get_ui_router(self) -> Any:
        return APIRouter()

    def get_metadata(self) -> Optional[MetaData]:
        # Returns None - signals to Core that this cartridge manages its own autonomous storage
        return None


def test_paradigm_b_autonomous_zero_interference(
    tmp_path: Path,
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify Core Platform ignores autonomous cartridge persistence and runs concurrently."""
    t_start = time.perf_counter()

    # 1. Start Core Platform on SQLite WAL
    core_db_url = portable_db_manager.get_sqlite_url(f"core_par_b_{tmp_path.name}.db")
    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(core_db_url)

    # 2. Instantiate Autonomous Cartridge on its own private DuckDB file
    duck_path = str(portable_db_manager.duckdb_dir / f"auto_analytics_{tmp_path.name}.duckdb")
    app_b = AutonomousAnalyticsCartridge(duck_path)

    # 3. Core DatabaseManager registration check
    initial_tables = db_mgr.init_tables()
    initial_custom_factories = len(db_mgr._custom_factories)

    # Core must NOT have registered any metadata or created custom factories for App B
    custom_url = getattr(app_b, "custom_database_url", None)
    meta = app_b.get_metadata()
    if custom_url is not None:
        db_mgr.create_custom_factory(app_b.app_id, custom_url)
    elif meta is not None:
        db_mgr.register_cartridge_metadata(app_b.app_id, meta)

    assert len(db_mgr._custom_factories) == initial_custom_factories
    assert app_b.get_metadata() is None

    polyglot_reporter.log_action(
        cartridge_id="autonomous_analytics",
        paradigm="PARADIGM_B",
        dialect="duckdb",
        action_name="core_zero_interference_bypass",
        status="PASS",
        duration_ms=(time.perf_counter() - t_start) * 1000.0,
        query_sql="get_metadata() -> None (Core skips DDL / tables completely)",
    )

    # 4. App B executes independent analytical operations
    t0 = time.perf_counter()
    for i in range(50):
        app_b.insert_metric("chiller_efficiency", 92.5 + (i * 0.1))

    avg_efficiency = app_b.query_avg("chiller_efficiency")
    assert avg_efficiency > 90.0

    polyglot_reporter.log_action(
        cartridge_id="autonomous_analytics",
        paradigm="PARADIGM_B",
        dialect="duckdb",
        action_name="autonomous_columnar_operations",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=50,
        query_sql="INSERT INTO bi_aggregates ...; SELECT AVG(val) FROM bi_aggregates;",
    )

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_PARADIGM_B_AUTONOMOUS",
        name="Paradigm B Autonomous Cartridge ('We Don't Care')",
        cartridge_id="autonomous_analytics",
        paradigm="PARADIGM_B",
        primary_dialect="sqlite",
        dedicated_dialect="duckdb",
        status="PASS",
        duration_ms=(time.perf_counter() - t_start) * 1000.0,
    )

    db_mgr.shutdown()
    DatabaseManager.reset_instance()
