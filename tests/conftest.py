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
Global Pytest Configuration & Polyglot Database Test Fixtures.
"""

from pathlib import Path
import pytest
from typing import Generator

from tests.fixtures.polyglot_reporter import PolyglotTelemetryCollector, get_polyglot_reporter
from tests.fixtures.portable_db_manager import PortableDatabaseManager, get_portable_db_manager
from core_platform.app.db.manager import DatabaseManager


@pytest.fixture(scope="session", autouse=True)
def polyglot_test_session() -> Generator[None, None, None]:
    """Session fixture to track overall polyglot testing and output reports at finish."""
    reporter = get_polyglot_reporter()
    db_mgr = get_portable_db_manager()
    yield
    # Shutdown any portable database daemons cleanly
    db_mgr.shutdown_all()
    # Generate all tri-format reports on session finish
    report_paths = reporter.generate_all_reports()
    print("\n" + "=" * 80)
    print("  POLYGLOT DATABASE TEST EXECUTION COMPLETE (GEES v2.0)")
    print(f"  JSON Report : {report_paths['json']}")
    print(f"  MD Report   : {report_paths['md']}")
    print(f"  HTML Report : {report_paths['html']}")
    print("=" * 80)


@pytest.fixture
def polyglot_reporter() -> PolyglotTelemetryCollector:
    """Fixture providing access to the deep telemetry collector."""
    return get_polyglot_reporter()


@pytest.fixture
def portable_db_manager() -> PortableDatabaseManager:
    """Fixture providing access to portable database cluster paths."""
    return get_portable_db_manager()


@pytest.fixture(autouse=True)
def isolate_database_manager() -> Generator[None, None, None]:
    """Cleanly reset DatabaseManager before and after each test."""
    DatabaseManager.reset_instance()
    yield
    DatabaseManager.reset_instance()
