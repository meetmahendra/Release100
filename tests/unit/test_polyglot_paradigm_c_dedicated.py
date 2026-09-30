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
Unit Tests: Paradigm C (Cartridge-Dedicated SQL Database via Core Factory).

Verifies that 3rd-party cartridges requesting an isolated SQL connection pool
receive dedicated factories from Core DatabaseManager with isolated connection lifecycles.
"""

from pathlib import Path
import time
from typing import Any, Optional
from fastapi import APIRouter
from sqlalchemy import Column, Integer, MetaData, String, Table, select

from core_platform.app.db.manager import DatabaseManager
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from tests.fixtures.polyglot_reporter import PolyglotTelemetryCollector
from tests.fixtures.portable_db_manager import PortableDatabaseManager


class DedicatedBillingCartridge(BaseApplication):
    """Simulates a 3rd-party Billing cartridge requesting a private SQL database from Core."""
    app_id = "dedicated_billing"
    name = "Enterprise Billing & Invoicing Cartridge"
    version = "2.0.0"

    def __init__(self, custom_db_url: str) -> None:
        self.custom_database_url = custom_db_url
        self.meta = MetaData()
        self.invoices_table = Table(
            "billing_invoices",
            self.meta,
            Column("id", Integer, primary_key=True),
            Column("invoice_code", String(64), unique=True),
            Column("amount_cents", Integer),
        )
        self.dedicated_engine: Optional[Any] = None

    def on_bind_engine(self, engine: Any) -> None:
        self.dedicated_engine = engine
        self.meta.create_all(bind=engine)

    def get_workflow(self) -> Any:
        return None

    def get_ui_router(self) -> Any:
        return APIRouter()


def test_paradigm_c_dedicated_sql_factory_isolation(
    tmp_path: Path,
    polyglot_reporter: PolyglotTelemetryCollector,
    portable_db_manager: PortableDatabaseManager,
) -> None:
    """Verify Core provisions dedicated isolated connection pools for Paradigm C cartridges."""
    t_start = time.perf_counter()

    # 1. Primary Platform runs on SQLite WAL
    primary_db_url = portable_db_manager.get_sqlite_url(f"primary_core_{tmp_path.name}.db")
    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(primary_db_url)
    primary_engine = db_mgr.get_engine()

    # 2. Cartridge declares dedicated SQL database
    dedicated_db_url = portable_db_manager.get_sqlite_url(f"dedicated_billing_{tmp_path.name}.db")
    billing_app = DedicatedBillingCartridge(dedicated_db_url)

    # 3. Core DatabaseManager creates dedicated factory
    assert billing_app.custom_database_url is not None
    t0 = time.perf_counter()
    custom_factory = db_mgr.create_custom_factory(
        cartridge_id=billing_app.app_id,
        custom_db_url=billing_app.custom_database_url,
    )
    billing_app.on_bind_engine(custom_factory.get_engine())

    assert billing_app.dedicated_engine is not None
    assert billing_app.dedicated_engine is custom_factory.get_engine()
    assert billing_app.dedicated_engine is not primary_engine  # MUST be separate engines

    polyglot_reporter.log_action(
        cartridge_id="dedicated_billing",
        paradigm="PARADIGM_C",
        dialect="sqlite",
        action_name="provision_dedicated_connection_factory",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        query_sql="DatabaseManager.create_custom_factory(cartridge_id='dedicated_billing', ...)",
    )

    # 4. Insert records into dedicated database
    t0 = time.perf_counter()
    with custom_factory.session_scope() as session:
        session.execute(
            billing_app.invoices_table.insert().values(
                invoice_code="INV-2026-001",
                amount_cents=150000,
            )
        )

    # Verify record in dedicated DB
    with custom_factory.session_scope() as session:
        res = session.execute(
            select(billing_app.invoices_table.c.invoice_code).where(
                billing_app.invoices_table.c.invoice_code == "INV-2026-001"
            )
        ).scalar_one_or_none()
        assert res == "INV-2026-001"

    polyglot_reporter.log_action(
        cartridge_id="dedicated_billing",
        paradigm="PARADIGM_C",
        dialect="sqlite",
        action_name="dedicated_invoice_write_and_read",
        status="PASS",
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        records_affected=1,
        query_sql="INSERT INTO billing_invoices (invoice_code, amount_cents) VALUES ('INV-2026-001', 150000);",
    )

    # 5. Verify Health Telemetry reports dedicated database separately
    health = db_mgr.check_health()
    assert "dedicated_billing" in health["custom_cartridge_databases"]
    assert health["custom_cartridge_databases"]["dedicated_billing"]["status"] == "UP"

    polyglot_reporter.record_topology_result(
        scenario_id="SCENARIO_PARADIGM_C_DEDICATED",
        name="Paradigm C Dedicated SQL Connection Pool via Core",
        cartridge_id="dedicated_billing",
        paradigm="PARADIGM_C",
        primary_dialect="sqlite",
        dedicated_dialect="sqlite_dedicated",
        status="PASS",
        duration_ms=(time.perf_counter() - t_start) * 1000.0,
    )

    db_mgr.shutdown()
    DatabaseManager.reset_instance()
