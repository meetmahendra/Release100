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
Central Database Manager for Core Platform & Modular Cartridges.

Adheres strictly to GEES v2.0:
- Dual-Mode Persistence: Core-facilitated shared database + Cartridge-autonomous dedicated databases.
- Microkernel Invariant: Zero domain entities or app-specific tables hardcoded in Core.
"""

from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional
from sqlalchemy import MetaData
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from core_platform.app.config import settings
from core_platform.app.db.config import DatabaseConfig
from core_platform.app.db.connection_factory import DatabaseConnectionFactory
from core_platform.app.db.migrations import DatabaseMigrationHelper


class DatabaseManager:
    """Manages platform-wide database lifecycles, migrations, and autonomous cartridge databases."""

    _instance: Optional["DatabaseManager"] = None

    @classmethod
    def get_instance(cls, database_url: Optional[str] = None) -> "DatabaseManager":
        """Retrieve or initialize singleton instance of DatabaseManager."""
        if cls._instance is None:
            resolved_url = database_url or settings.DATABASE_URL
            cls._instance = cls(db_url=resolved_url)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (primarily for clean test fixture isolation)."""
        if cls._instance is not None:
            cls._instance.shutdown()
            cls._instance = None

    def __init__(self, db_url: Optional[str] = None) -> None:
        """Initialize DatabaseManager with primary platform connection factory.

        Args:
            db_url: Primary database connection string. If omitted, resolved from settings.DATABASE_URL.
        """
        resolved_url = db_url or settings.DATABASE_URL
        self.config = DatabaseConfig(
            database_url=resolved_url,
            pool_size=getattr(settings, "DB_POOL_SIZE", 20),
            max_overflow=getattr(settings, "DB_MAX_OVERFLOW", 10),
        )
        self.primary_factory = DatabaseConnectionFactory(self.config)
        self._cartridge_metadata: Dict[str, MetaData] = {}
        self._custom_factories: Dict[str, DatabaseConnectionFactory] = {}

    # ── Core-Facilitated Database Operations ──────────────────────────────────

    def get_engine(self) -> Engine:
        """Return the primary SQLAlchemy Engine managed by Core Platform."""
        return self.primary_factory.get_engine()

    def get_primary_factory(self) -> DatabaseConnectionFactory:
        """Return the primary platform DatabaseConnectionFactory."""
        return self.primary_factory

    def register_cartridge_metadata(self, app_id: str, metadata: MetaData) -> None:
        """Register a cartridge's SQLAlchemy MetaData for core-managed table creation and migrations."""
        self._cartridge_metadata[app_id] = metadata

    def get_all_registered_metadata(self) -> List[MetaData]:
        """Return list of all registered cartridge MetaData objects."""
        return list(self._cartridge_metadata.values())

    def init_tables(self) -> List[str]:
        """Create all tables for registered cartridges on the primary platform database via MigrationHelper."""
        metadata_list = list(self._cartridge_metadata.values())
        if not metadata_list:
            return []
        return DatabaseMigrationHelper.initialize_metadata_tables(
            engine=self.primary_factory.get_engine(),
            metadata_list=metadata_list,
            enable_sqlite_wal=True,
        )

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Provide deterministic context-managed Session from the primary platform database."""
        with self.primary_factory.session_scope() as session:
            yield session


    # ── Cartridge-Autonomous / 3rd-Party Dedicated Databases ───────────────────

    def create_custom_factory(
        self,
        cartridge_id: str,
        custom_db_url: str,
        **kwargs: Any,
    ) -> DatabaseConnectionFactory:
        """Create or retrieve a dedicated, autonomous connection factory for a 3rd-party cartridge.

        Args:
            cartridge_id: Unique cartridge identifier.
            custom_db_url: Custom database connection URL.
            **kwargs: Extra database configuration parameters.

        Returns:
            Configured DatabaseConnectionFactory instance.
        """
        if cartridge_id in self._custom_factories:
            existing = self._custom_factories[cartridge_id]
            if existing.db_url == custom_db_url:
                return existing
            existing.dispose()

        cfg = DatabaseConfig(database_url=custom_db_url, **kwargs)
        factory = DatabaseConnectionFactory(cfg)
        self._custom_factories[cartridge_id] = factory
        return factory

    def get_custom_factory(self, cartridge_id: str) -> Optional[DatabaseConnectionFactory]:
        """Retrieve existing custom connection factory for a cartridge."""
        return self._custom_factories.get(cartridge_id)

    # ── Observability & Health Telemetry ───────────────────────────────────────

    def check_health(self) -> Dict[str, Any]:
        """Verify database connectivity and compile status report for diagnostics endpoints."""
        is_healthy, latency_ms, error = self.primary_factory.ping()
        
        custom_health: Dict[str, Any] = {}
        for cid, factory in self._custom_factories.items():
            c_healthy, c_lat, c_err = factory.ping()
            custom_health[cid] = {
                "status": "UP" if c_healthy else "DOWN",
                "dialect": factory.dialect,
                "latency_ms": c_lat,
                "error": c_err,
            }

        return {
            "status": "UP" if is_healthy else "DOWN",
            "primary_dialect": self.primary_factory.dialect,
            "latency_ms": latency_ms,
            "registered_cartridges": list(self._cartridge_metadata.keys()),
            "custom_cartridge_databases": custom_health,
            "error": error,
        }

    def shutdown(self) -> None:
        """Cleanly close all primary and custom database connection pools."""
        self.primary_factory.dispose()
        for factory in self._custom_factories.values():
            factory.dispose()
        self._custom_factories.clear()

    def close(self) -> None:
        """Alias for shutdown to cleanly release all connection pools."""
        self.shutdown()



def get_db_manager() -> DatabaseManager:
    """Helper function to access the central DatabaseManager singleton."""
    return DatabaseManager.get_instance()
