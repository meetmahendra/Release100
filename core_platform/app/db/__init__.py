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
Core Platform Pluggable Polyglot Database Subsystem.

Provides:
1. Universal connection factory supporting SQLite, PostgreSQL, MySQL, TimescaleDB, MSSQL.
2. Dual-mode persistence: Core-facilitated shared tables + Cartridge-autonomous dedicated databases.
3. Deterministic session scopes with zero resource leaks.
"""

from core_platform.app.db.base import Base, TenantIsolationMixin, TimestampMixin, UUIDPrimaryKeyMixin
from core_platform.app.db.config import DatabaseConfig
from core_platform.app.db.connection_factory import DatabaseConnectionFactory
from core_platform.app.db.manager import DatabaseManager, get_db_manager
from core_platform.app.db.migrations import DatabaseMigrationHelper

__all__ = [
    "Base",
    "DatabaseConfig",
    "DatabaseConnectionFactory",
    "DatabaseManager",
    "DatabaseMigrationHelper",
    "TenantIsolationMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "get_db_manager",
]

