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
Polyglot Database Connection Factory for Core Platform.

Adheres strictly to GEES v2.0:
- Pillar 3: Microkernel architecture (100% domain-agnostic persistence).
- Pillar 4: Zero hardcoding (Connection URL dynamic resolution).
- Pillar 5: Type discipline (mypy --strict compliant).
- Pillar 6: Deterministic context management (Zero resource leaks).
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import os
from pathlib import Path
import time
from typing import Any, AsyncGenerator, Dict, Generator, Optional, Tuple, Union
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

from core_platform.app.db.config import DatabaseConfig


class DatabaseConnectionFactory:
    """Manages SQLAlchemy engines, connection pooling, and deterministic session lifecycles."""

    def __init__(self, config: Union[DatabaseConfig, str]) -> None:
        """Initialize connection factory with typed configuration or connection URL.

        Args:
            config: DatabaseConfig instance or raw connection URL string.
        """
        if isinstance(config, str):
            self.config = DatabaseConfig(database_url=config)
        else:
            self.config = config

        self.db_url: str = self.config.database_url
        self.dialect: str = self._resolve_dialect(self.db_url)
        self.engine: Engine = self._create_engine()
        self.session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    def _resolve_dialect(self, url: str) -> str:
        """Extract dialect identifier from database URL."""
        if url.startswith("sqlite"):
            return "sqlite"
        elif "postgres" in url or "timescale" in url:
            return "postgresql"
        elif "mysql" in url or "mariadb" in url:
            return "mysql"
        elif "mssql" in url:
            return "mssql"
        elif "oracle" in url:
            return "oracle"
        return "generic"

    def _create_engine(self) -> Engine:
        """Create and configure SQLAlchemy Engine based on dialect and pool settings."""
        connect_args: Dict[str, Any] = dict(self.config.connect_args)

        if self.dialect == "sqlite":
            clean_url = self.db_url
            if clean_url.startswith("sqlite+aiosqlite:///"):
                clean_url = clean_url.replace("sqlite+aiosqlite:///", "sqlite:///")

            if clean_url.startswith("sqlite:///"):
                raw_path = clean_url.replace("sqlite:///", "")
                if raw_path != ":memory:":
                    db_path = Path(raw_path)
                    db_path.parent.mkdir(parents=True, exist_ok=True)

            connect_args.setdefault("check_same_thread", False)

            if ":memory:" in clean_url:
                return create_engine(
                    clean_url,
                    connect_args=connect_args,
                    poolclass=StaticPool,
                    echo=self.config.echo,
                )

            return create_engine(
                clean_url,
                connect_args=connect_args,
                poolclass=NullPool,
                echo=self.config.echo,
            )

        # Standard client-server relational databases (PostgreSQL, MySQL, MSSQL)
        clean_url = self.db_url
        if clean_url.startswith(("timescaledb://", "timescale://")):
            clean_url = clean_url.replace("timescaledb://", "postgresql+psycopg2://").replace("timescale://", "postgresql+psycopg2://")
        elif clean_url.startswith("postgresql://"):
            import importlib.util
            if importlib.util.find_spec("psycopg") is None:
                clean_url = clean_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        elif clean_url.startswith("postgres://"):
            clean_url = clean_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif clean_url.startswith("mysql://"):
            import importlib.util
            if importlib.util.find_spec("MySQLdb") is None:
                clean_url = clean_url.replace("mysql://", "mysql+pymysql://", 1)

        try:
            return create_engine(
                clean_url,
                connect_args=connect_args,
                poolclass=QueuePool,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_timeout=self.config.pool_timeout_seconds,
                pool_recycle=self.config.pool_recycle_seconds,
                echo=self.config.echo,
            )
        except (ImportError, ModuleNotFoundError) as err:
            raise RuntimeError(
                f"Database driver for dialect '{self.dialect}' is not installed: {err}. "
                f"Please install the appropriate driver (e.g. psycopg2-binary, pymysql, asyncpg)."
            ) from err

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Provide a deterministic transactional scope around a series of operations.

        Yields:
            SQLAlchemy Session.

        Raises:
            Exception: Re-raises any exception encountered after performing rollback.
        """
        session: Session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def async_session_scope(self) -> AsyncGenerator[Session, None]:
        """Provide an asynchronous context manager wrapping synchronous sessions cleanly."""
        session: Session = self.session_factory()
        try:
            yield session
            await asyncio.to_thread(session.commit)
        except Exception:
            await asyncio.to_thread(session.rollback)
            raise
        finally:
            await asyncio.to_thread(session.close)

    def ping(self) -> Tuple[bool, float, Optional[str]]:
        """Verify database connectivity and measure query round-trip latency.

        Returns:
            Tuple of (is_healthy: bool, latency_ms: float, error_message: Optional[str]).
        """
        start_time = time.perf_counter()
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return True, round(latency_ms, 2), None
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return False, round(latency_ms, 2), str(exc)

    def get_engine(self) -> Engine:
        """Return the underlying SQLAlchemy Engine."""
        return self.engine

    def dispose(self) -> None:
        """Dispose and close all pooled database connections cleanly."""
        self.engine.dispose()

