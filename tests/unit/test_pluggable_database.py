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
Unit Test Suite for Pluggable Polyglot Database Architecture (GEES v2.0).

Tests:
1. Connection factory lifecycle, connection pooling, and dialect resolution.
2. Deterministic context management (commit on success, rollback on error).
3. Async session management.
4. Core-Facilitated shared database operations (cartridge metadata registration & table init).
5. Cartridge-Autonomous dedicated database isolation (3rd-party plug-in DBs).
6. Health checks and latency telemetry.
"""

import os
from pathlib import Path
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, select, text
from sqlalchemy.orm import declarative_base

from core_platform.app.db.base import Base, TenantIsolationMixin, TimestampMixin, UUIDPrimaryKeyMixin
from core_platform.app.db.config import DatabaseConfig
from core_platform.app.db.connection_factory import DatabaseConnectionFactory
from core_platform.app.db.manager import DatabaseManager, get_db_manager


@pytest.fixture(autouse=True)
def reset_database_manager() -> None:
    """Ensure clean DatabaseManager state before and after each test."""
    DatabaseManager.reset_instance()
    yield
    DatabaseManager.reset_instance()


def test_database_config_defaults() -> None:
    """Verify DatabaseConfig defaults and typed attribute validations."""
    cfg = DatabaseConfig()
    assert cfg.database_url == "sqlite:///logs/platform_data.db"
    assert cfg.pool_size == 20
    assert cfg.max_overflow == 10
    assert cfg.pool_timeout_seconds == 30
    assert cfg.echo is False


def test_connection_factory_dialect_resolution() -> None:
    """Verify dialect identification across multiple SQL engines."""
    f_sqlite = DatabaseConnectionFactory("sqlite:///:memory:")
    assert f_sqlite.dialect == "sqlite"
    assert f_sqlite._resolve_dialect("sqlite:///data.db") == "sqlite"
    assert f_sqlite._resolve_dialect("postgresql://user:pass@localhost:5432/testdb") == "postgresql"
    assert f_sqlite._resolve_dialect("timescaledb://user:pass@localhost:5432/telemetry") == "postgresql"
    assert f_sqlite._resolve_dialect("mysql+pymysql://user:pass@localhost:3306/shop") == "mysql"
    assert f_sqlite._resolve_dialect("mssql+pyodbc://user:pass@localhost/enterprise") == "mssql"
    assert f_sqlite._resolve_dialect("oracle://user:pass@localhost/xe") == "oracle"

    # Verify that attempting to instantiate uninstalled driver raises descriptive RuntimeError
    with pytest.raises(RuntimeError, match="Database driver for dialect 'oracle' is not installed"):
        DatabaseConnectionFactory("oracle+cx_oracle://user:pass@localhost:1521/xe")


def test_session_scope_commit_and_rollback() -> None:
    """Verify deterministic session scope commits on success and rolls back on exception."""
    factory = DatabaseConnectionFactory("sqlite:///:memory:")

    # Create test table
    with factory.engine.connect() as conn:
        conn.execute(text("CREATE TABLE test_items (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.commit()

    # Success case: Commit
    with factory.session_scope() as session:
        session.execute(text("INSERT INTO test_items (id, name) VALUES (1, 'Alpha')"))

    with factory.session_scope() as session:
        result = session.execute(text("SELECT name FROM test_items WHERE id = 1")).scalar()
        assert result == "Alpha"

    # Failure case: Rollback on exception
    with pytest.raises(ValueError, match="Simulated Failure"):
        with factory.session_scope() as session:
            session.execute(text("INSERT INTO test_items (id, name) VALUES (2, 'Beta')"))
            raise ValueError("Simulated Failure")

    # Verify 'Beta' was rolled back and not persisted
    with factory.session_scope() as session:
        result_beta = session.execute(text("SELECT name FROM test_items WHERE id = 2")).scalar()
        assert result_beta is None


@pytest.mark.asyncio
async def test_async_session_scope() -> None:
    """Verify asynchronous session scope manages transactions seamlessly."""
    factory = DatabaseConnectionFactory("sqlite:///:memory:")

    with factory.engine.connect() as conn:
        conn.execute(text("CREATE TABLE async_items (id INTEGER PRIMARY KEY, value TEXT)"))
        conn.commit()

    async with factory.async_session_scope() as session:
        session.execute(text("INSERT INTO async_items (id, value) VALUES (10, 'AsyncVal')"))

    async with factory.async_session_scope() as session:
        val = session.execute(text("SELECT value FROM async_items WHERE id = 10")).scalar()
        assert val == "AsyncVal"


def test_connection_factory_ping_and_health() -> None:
    """Verify ping measurement on active and in-memory SQLite instances."""
    factory = DatabaseConnectionFactory("sqlite:///:memory:")
    is_healthy, latency_ms, error = factory.ping()
    assert is_healthy is True
    assert latency_ms >= 0.0
    assert error is None
    factory.dispose()


def test_core_facilitated_database_registration_and_table_init() -> None:
    """Mode 1: Verify Core-Facilitated database collects cartridge metadata and creates tables."""
    db_mgr = DatabaseManager.get_instance("sqlite:///:memory:")

    # Define mock cartridge metadata
    cartridge_meta = MetaData()
    Table(
        "cartridge_events",
        cartridge_meta,
        Column("id", Integer, primary_key=True),
        Column("event_name", String(50), nullable=False),
    )

    db_mgr.register_cartridge_metadata("mock_cartridge", cartridge_meta)
    assert "mock_cartridge" in db_mgr._cartridge_metadata

    # Init tables on primary database
    db_mgr.init_tables()

    # Verify table exists and can be written to via core session
    with db_mgr.get_session() as session:
        session.execute(text("INSERT INTO cartridge_events (id, event_name) VALUES (1, 'CHECKIN')"))

    with db_mgr.get_session() as session:
        evt = session.execute(text("SELECT event_name FROM cartridge_events WHERE id = 1")).scalar()
        assert evt == "CHECKIN"

    # Verify health report reflects registered cartridge
    health = db_mgr.check_health()
    assert health["status"] == "UP"
    assert "mock_cartridge" in health["registered_cartridges"]


def test_cartridge_autonomous_dedicated_database_isolation() -> None:
    """Mode 2: Verify Cartridge-Autonomous database creates independent connection pool and storage."""
    db_mgr = DatabaseManager.get_instance("sqlite:///:memory:")

    # 3rd-Party Cartridge spins up its own dedicated autonomous database
    custom_factory = db_mgr.create_custom_factory(
        cartridge_id="custom_erp_plugin",
        custom_db_url="sqlite:///:memory:",
    )
    assert custom_factory is not None
    assert custom_factory.db_url == "sqlite:///:memory:"

    # Initialize tables on custom DB
    with custom_factory.engine.connect() as conn:
        conn.execute(text("CREATE TABLE erp_invoices (invoice_id TEXT PRIMARY KEY, amount REAL)"))
        conn.commit()

    # Write to custom DB
    with custom_factory.session_scope() as session:
        session.execute(text("INSERT INTO erp_invoices (invoice_id, amount) VALUES ('INV-001', 450.50)"))

    # Verify row exists in custom DB
    with custom_factory.session_scope() as session:
        amt = session.execute(text("SELECT amount FROM erp_invoices WHERE invoice_id = 'INV-001'")).scalar()
        assert amt == 450.50

    # Verify primary DB does NOT have the table (complete isolation)
    with pytest.raises(Exception):
        with db_mgr.get_session() as session:
            session.execute(text("SELECT * FROM erp_invoices"))

    # Health check verifies custom DB reporting
    health = db_mgr.check_health()
    assert health["status"] == "UP"
    assert "custom_erp_plugin" in health["custom_cartridge_databases"]
    assert health["custom_cartridge_databases"]["custom_erp_plugin"]["status"] == "UP"


def test_universal_entity_mixins() -> None:
    """Verify TimestampMixin, UUIDPrimaryKeyMixin, and TenantIsolationMixin work with DeclarativeBase."""
    TestDeclarativeBase = declarative_base()

    class SampleEntity(TestDeclarativeBase, UUIDPrimaryKeyMixin, TimestampMixin, TenantIsolationMixin):
        __tablename__ = "sample_entities"
        title = Column(String(100), nullable=False)

    factory = DatabaseConnectionFactory("sqlite:///:memory:")
    TestDeclarativeBase.metadata.create_all(bind=factory.engine)

    with factory.session_scope() as session:
        item = SampleEntity(title="Sensor Calibration", tenant_id="tenant_chicago_01")
        session.add(item)

    with factory.session_scope() as session:
        stmt = select(SampleEntity).where(SampleEntity.title == "Sensor Calibration")
        saved = session.scalars(stmt).one()
        assert len(saved.id) == 36  # UUID length
        assert saved.tenant_id == "tenant_chicago_01"
        assert saved.created_at is not None
        assert saved.updated_at is not None
