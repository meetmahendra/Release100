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
Unit Tests for Plugin Persistence Paradigms (GEES v2.0).

Verifies:
- Paradigm A: Core-Facilitated (Shared central platform database across standard cartridges).
- Paradigm B: Cartridge-Autonomous (3rd-party cartridge manages its own persistence with zero core interference).
- Paradigm C: Dedicated Database (3rd-party cartridge requests an isolated connection pool from Core).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, select

from core_platform.app.db.manager import DatabaseManager, get_db_manager
from core_platform.app.plugin_engine.base_plugin import BaseApplication
from core_platform.app.plugin_engine.loader import PluginLoader


def test_paradigm_a_core_facilitated_shared_engine(tmp_path: Path) -> None:
    """Verify standard cartridges share the central core database engine."""
    db_file = tmp_path / "shared_platform.db"
    db_url = f"sqlite:///{db_file}"

    # Reset and configure DatabaseManager
    DatabaseManager.reset_instance()
    db_mgr = DatabaseManager.get_instance(db_url)
    core_engine = db_mgr.get_engine()

    loader = PluginLoader(enabled_apps=["temperature_marker", "mail_organizer"])
    loaded = loader.load_all()

    tm_app = loaded.get("temperature_marker")
    mail_app = loaded.get("mail_organizer")

    assert tm_app is not None
    assert mail_app is not None

    # Both cartridges must share the core platform engine
    assert tm_app.db_service.engine is core_engine
    assert mail_app.db_service.engine is core_engine

    # Perform operations in both cartridges
    tm_app.db_service.register_employee(
        emp_code="EMP_PARADIGM_A",
        full_name="Alice Shared",
        phone_number="+919999900001",
        assigned_kiosk_id="K-01",
    )

    mail_app.db_service.store_email(
        gmail_id="gmail_paradigm_a",
        thread_id="th_paradigm_a",
        subject="Shared DB Test",
        sender="alice@example.com",
    )

    # Verify both records exist within the single shared database file
    assert tm_app.db_service.get_employee_by_code("EMP_PARADIGM_A") is not None
    recent = mail_app.db_service.get_recent_emails(limit=5)
    assert any(r["gmail_id"] == "gmail_paradigm_a" for r in recent)

    db_mgr.close()
    DatabaseManager.reset_instance()


def test_paradigm_b_cartridge_autonomous_zero_interference() -> None:
    """Verify 3rd-party autonomous cartridge manages its own persistence with zero core interference."""
    class MockNoSQLCartridge(BaseApplication):
        app_id = "third_party_nosql"
        name = "Third Party NoSQL App"
        version = "1.0.0"

        def __init__(self) -> None:
            # Manages self-contained in-memory document store (simulating MongoDB / TinyDB)
            self.doc_store: Dict[str, Dict[str, Any]] = {}

        def get_workflow(self) -> Any:
            return None

        def get_ui_router(self) -> Any:
            return APIRouter()

        def get_metadata(self) -> Optional[MetaData]:
            # Returns None - no SQL metadata provided
            return None

    autonomous_app = MockNoSQLCartridge()
    autonomous_app.doc_store["doc_1"] = {"title": "Autonomous Doc", "status": "SAVED"}

    # Core platform loader registration check
    db_mgr = get_db_manager()
    initial_factories = len(db_mgr._custom_factories)

    # Simulating PluginLoader registration
    if getattr(autonomous_app, "custom_database_url", None):
        db_mgr.create_custom_factory(autonomous_app.app_id, autonomous_app.custom_database_url)
    elif autonomous_app.get_metadata() is not None:
        db_mgr.register_cartridge_metadata(autonomous_app.app_id, autonomous_app.get_metadata())

    # Verify core database manager did not register or modify anything for this app
    assert len(db_mgr._custom_factories) == initial_factories
    assert autonomous_app.doc_store["doc_1"]["title"] == "Autonomous Doc"


def test_paradigm_c_dedicated_database_via_core(tmp_path: Path) -> None:
    """Verify 3rd-party cartridge with custom_database_url gets dedicated isolated connection factory."""
    custom_db_file = tmp_path / "custom_dedicated.db"
    custom_db_url = f"sqlite:///{custom_db_file}"

    # Define standalone metadata
    custom_meta = MetaData()
    custom_table = Table(
        "custom_invoices",
        custom_meta,
        Column("id", Integer, primary_key=True),
        Column("invoice_no", String(32)),
    )

    class DedicatedCartridge(BaseApplication):
        app_id = "custom_billing"
        name = "Custom Billing Cartridge"
        version = "2.0.0"
        custom_database_url = custom_db_url

        def __init__(self) -> None:
            self.engine: Optional[Any] = None

        def on_bind_engine(self, engine: Any) -> None:
            self.engine = engine
            custom_meta.create_all(bind=engine)

        def get_workflow(self) -> Any:
            return None

        def get_ui_router(self) -> Any:
            return APIRouter()

    dedicated_app = DedicatedCartridge()
    db_mgr = get_db_manager()

    # Core provisions custom factory
    custom_factory = db_mgr.create_custom_factory(dedicated_app.app_id, dedicated_app.custom_database_url)
    dedicated_app.on_bind_engine(custom_factory.get_engine())

    assert dedicated_app.engine is not None
    assert dedicated_app.engine is custom_factory.get_engine()
    assert dedicated_app.engine is not db_mgr.get_engine()  # Must NOT be the shared core engine

    # Write data to dedicated DB
    with custom_factory.session_scope() as session:
        session.execute(custom_table.insert().values(invoice_no="INV-2026-999"))

    # Verify data in dedicated DB
    with custom_factory.session_scope() as session:
        result = session.execute(select(custom_table.c.invoice_no)).scalar_one_or_none()
        assert result == "INV-2026-999"

    custom_factory.dispose()
