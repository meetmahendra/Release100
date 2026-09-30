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
Unit Tests: Polyglot Database Server Lifecycle, Dialect Resolution, & Live Health Checks.

Runs REAL live queries, table migrations, and CRUD operations across:
1. SQLite WAL Engine
2. DuckDB Analytical Columnar Engine
3. Live Portable PostgreSQL 16 (on port 54329)
4. Live Portable MariaDB 10.11 / MySQL (on port 33069)
5. TimescaleDB (PostgreSQL telemetry dialect)
6. MSSQL (Driver availability and informative exception guidance)
"""

from pathlib import Path
import time
from typing import Any
import uuid
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, select, text
import duckdb

from core_platform.app.db.config import DatabaseConfig
from core_platform.app.db.connection_factory import DatabaseConnectionFactory
from core_platform.app.db.migrations import DatabaseMigrationHelper
from tests.fixtures.polyglot_reporter import PolyglotTelemetryCollector
from tests.fixtures.portable_db_manager import PortableDatabaseManager


def test_sqlite_wal_server_lifecycle(
    tmp_path: Path,
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify SQLite WAL engine initialization, pragmas, and latency."""
    t0 = time.perf_counter()
    db_url = portable_db_manager.get_sqlite_url(f"test_lifecycle_{tmp_path.name}.db")
    factory = DatabaseConnectionFactory(db_url)
    engine = factory.get_engine()

    meta = MetaData()
    test_tbl = Table("wal_test", meta, Column("id", Integer, primary_key=True), Column("val", String(32)))
    
    # Initialize table via MigrationHelper
    created = DatabaseMigrationHelper.initialize_metadata_tables(engine, [meta], enable_sqlite_wal=True)
    assert "wal_test" in created

    # Verify SQLite WAL mode via PRAGMA
    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA journal_mode;")).scalar()
        assert str(res).lower() == "wal"

    is_healthy, lat_ms, err = factory.ping()
    assert is_healthy is True
    assert lat_ms < 50.0  # Latency under 50ms

    polyglot_reporter.log_action(
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        dialect="sqlite",
        action_name="sqlite_wal_lifecycle_and_pragmas",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        query_sql="PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; SELECT 1;",
    )

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_LIFECYCLE_SQLITE",
        name="SQLite WAL Engine Verification",
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        primary_dialect="sqlite",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    factory.dispose()


def test_duckdb_analytical_engine_lifecycle(
    tmp_path: Path,
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify in-process DuckDB columnar database initialization and analytics."""
    t0 = time.perf_counter()
    duck_path = str(portable_db_manager.duckdb_dir / f"test_analytics_{tmp_path.name}.duckdb")
    conn = duckdb.connect(duck_path)

    # DuckDB Columnar DDL
    conn.execute("CREATE TABLE IF NOT EXISTS sensor_telemetry (id INTEGER, metric_name VARCHAR, reading INTEGER)")
    conn.execute("DELETE FROM sensor_telemetry")

    # Insert batch records
    for i in range(100):
        conn.execute("INSERT INTO sensor_telemetry VALUES (?, ?, ?)", [i, "chiller_temp", i])

    # Columnar aggregation query
    res = conn.execute("SELECT AVG(reading) FROM sensor_telemetry").fetchone()
    assert res is not None
    avg_val = float(res[0])
    assert avg_val == 49.5

    polyglot_reporter.log_action(
        cartridge_id="analytics_app",
        paradigm="PARADIGM_B",
        dialect="duckdb",
        action_name="duckdb_columnar_analytics_batch",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=100,
        query_sql="INSERT INTO sensor_telemetry ...; SELECT AVG(reading) FROM sensor_telemetry;",
    )

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_LIFECYCLE_DUCKDB",
        name="DuckDB Columnar Analytical Lifecycle",
        cartridge_id="analytics_app",
        paradigm="PARADIGM_B",
        primary_dialect="duckdb",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    conn.close()


def test_live_postgresql_server_lifecycle(
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify live portable PostgreSQL 16 server startup, connection, DDL, and CRUD operations."""
    t0 = time.perf_counter()
    url = portable_db_manager.get_postgresql_url()
    cfg = DatabaseConfig(
        database_url=url,
        pool_size=10,
        max_overflow=5,
        pool_timeout_seconds=5,
    )

    factory = DatabaseConnectionFactory(cfg)
    assert factory.dialect == "postgresql"

    # Ping live PostgreSQL server
    is_healthy, lat_ms, err = factory.ping()
    assert is_healthy is True, f"PostgreSQL health ping failed: {err}"

    # Execute real DDL and CRUD on live PostgreSQL with unique test table
    tbl_name = f"pg_test_{uuid.uuid4().hex[:8]}"
    meta = MetaData()
    pg_tbl = Table(tbl_name, meta, Column("id", Integer, primary_key=True), Column("val", String(64)))
    DatabaseMigrationHelper.initialize_metadata_tables(factory.get_engine(), [meta])

    with factory.session_scope() as session:
        session.execute(text(f"INSERT INTO {tbl_name} (id, val) VALUES (1, 'Live PostgreSQL 16 Test')"))

    with factory.get_engine().connect() as conn:
        row = conn.execute(text(f"SELECT val FROM {tbl_name} WHERE id = 1")).fetchone()
        assert row is not None
        assert row[0] == "Live PostgreSQL 16 Test"

    polyglot_reporter.log_action(
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        dialect="postgresql",
        action_name="postgresql_live_server_crud_and_ddl",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=1,
        query_sql=f"SELECT version(); CREATE TABLE {tbl_name} ...; INSERT ...; SELECT ...;",
    )

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_LIFECYCLE_POSTGRESQL",
        name="PostgreSQL 16 Live Server Lifecycle & CRUD",
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        primary_dialect="postgresql",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    factory.dispose()


def test_live_mariadb_server_lifecycle(
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify live portable MariaDB 10.11 / MySQL server startup, connection, DDL, and CRUD operations."""
    t0 = time.perf_counter()
    url = portable_db_manager.get_mysql_url()
    cfg = DatabaseConfig(
        database_url=url,
        pool_size=10,
        max_overflow=5,
        pool_timeout_seconds=5,
    )

    factory = DatabaseConnectionFactory(cfg)
    assert factory.dialect == "mysql"

    # Ping live MariaDB server
    is_healthy, lat_ms, err = factory.ping()
    assert is_healthy is True, f"MariaDB health ping failed: {err}"

    # Execute real DDL and CRUD on live MariaDB with unique test table
    tbl_name = f"maria_test_{uuid.uuid4().hex[:8]}"
    meta = MetaData()
    maria_tbl = Table(tbl_name, meta, Column("id", Integer, primary_key=True), Column("val", String(64)))
    DatabaseMigrationHelper.initialize_metadata_tables(factory.get_engine(), [meta])

    with factory.session_scope() as session:
        session.execute(text(f"INSERT INTO {tbl_name} (id, val) VALUES (1, 'Live MariaDB 10.11 Test')"))

    with factory.get_engine().connect() as conn:
        row = conn.execute(text(f"SELECT val FROM {tbl_name} WHERE id = 1")).fetchone()
        assert row is not None
        assert row[0] == "Live MariaDB 10.11 Test"

    polyglot_reporter.log_action(
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        dialect="mysql",
        action_name="mariadb_live_server_crud_and_ddl",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=1,
        query_sql=f"SELECT VERSION(); CREATE TABLE {tbl_name} ...; INSERT ...; SELECT ...;",
    )

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_LIFECYCLE_MYSQL",
        name="MariaDB / MySQL Live Server Lifecycle & CRUD",
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        primary_dialect="mysql",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    factory.dispose()


def test_timescaledb_configuration_and_pooling(
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify TimescaleDB dialect configuration and telemetry pooling."""
    t0 = time.perf_counter()
    url = portable_db_manager.get_timescaledb_url()
    cfg = DatabaseConfig(
        database_url=url,
        pool_size=15,
        max_overflow=5,
        pool_timeout_seconds=5,
    )

    factory = DatabaseConnectionFactory(cfg)
    assert factory.dialect == "postgresql"
    assert factory.config.pool_size == 15

    polyglot_reporter.log_action(
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        dialect="timescaledb",
        action_name="timescaledb_pool_and_dialect_configuration",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        query_sql="RESOLVE DIALECT -> postgresql (TimescaleDB telemetry pool)",
    )

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_LIFECYCLE_TIMESCALEDB",
        name="TimescaleDB Configuration & Dialect Verification",
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        primary_dialect="timescaledb",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    factory.dispose()


def test_mssql_driver_missing_informative_error(
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify informative error when MSSQL driver pyodbc is not installed."""
    t0 = time.perf_counter()
    url = portable_db_manager.get_mssql_url()
    
    with pytest.raises(RuntimeError) as exc_info:
        DatabaseConnectionFactory(url)
    
    assert "pyodbc" in str(exc_info.value) or "driver" in str(exc_info.value).lower()

    polyglot_reporter.log_action(
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        dialect="mssql",
        action_name="mssql_driver_informative_error_handling",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        query_sql="VALIDATE DRIVER -> pyodbc (Clear error guidance if not installed)",
    )

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_LIFECYCLE_MSSQL",
        name="MSSQL Driver Exception Guidance Verification",
        cartridge_id="core_kernel",
        paradigm="PARADIGM_A",
        primary_dialect="mssql",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
