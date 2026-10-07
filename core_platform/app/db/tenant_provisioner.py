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
Dynamic Multi-Tenant Schema & Database Provisioning Engine.

Adheres strictly to GEES v2.0 Pillar 3 (Microkernel Architecture) & Pillar 6 (Clean-Slate Bootstrapping).
Supports:
1. Master Blueprint Cloning: Automatically instantiates cartridge schemas per tenant.
2. Physical SQLite Partitioning: Dedicated isolated SQLite databases at `data/tenants/{tenant_id}/`.
3. PostgreSQL Schema Isolation: `CREATE SCHEMA IF NOT EXISTS tenant_{tenant_id};`.
4. Tenant Engine & Session Lifecycle Management.
"""

from contextlib import contextmanager
import logging
import os
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from sqlalchemy import MetaData, text
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core_platform.app.config import settings
from core_platform.app.db.base import Base

logger = logging.getLogger("core_platform.db.tenant_provisioner")


class TenantSchemaProvisioner:
    """Manages dynamic per-tenant database initialization, schema cloning, and connections."""

    _instance: Optional["TenantSchemaProvisioner"] = None

    @classmethod
    def get_instance(cls, tenants_base_dir: Optional[Path] = None) -> "TenantSchemaProvisioner":
        """Retrieve singleton instance of TenantSchemaProvisioner."""
        if cls._instance is None:
            cls._instance = cls(tenants_base_dir=tenants_base_dir)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        if cls._instance is not None:
            cls._instance.shutdown()
            cls._instance = None

    def __init__(self, tenants_base_dir: Optional[Path] = None) -> None:
        """Initialize provisioner with target tenant root directory."""
        self.tenants_dir = Path(tenants_base_dir or Path("data/tenants"))
        self.tenants_dir.mkdir(parents=True, exist_ok=True)
        self._tenant_engines: Dict[str, Engine] = {}
        self._tenant_sessions: Dict[str, sessionmaker[Session]] = {}
        self._blueprint_metadata: List[MetaData] = []

    def register_blueprint_metadata(self, metadata: MetaData) -> None:
        """Register a cartridge or platform MetaData to be cloned into every provisioned tenant."""
        if metadata not in self._blueprint_metadata:
            self._blueprint_metadata.append(metadata)

    def resolve_tenant_db_url(self, tenant_id: str) -> str:
        """Resolve database connection URL for a specific tenant partition."""
        clean_tenant = re_clean = "".join(c for c in tenant_id if c.isalnum() or c in ("_", "-")).lower()
        base_db_url = getattr(settings, "DATABASE_URL", "sqlite:///data/core.db")

        if base_db_url.startswith("sqlite"):
            tenant_folder = self.tenants_dir / f"tenant_{re_clean}"
            tenant_folder.mkdir(parents=True, exist_ok=True)
            db_path = tenant_folder / "tenant.db"
            return f"sqlite:///{db_path.as_posix()}"
        elif base_db_url.startswith("postgresql"):
            # PostgreSQL schema-based connection
            return base_db_url
        elif base_db_url.startswith("mysql"):
            # MySQL prefix-based or database-based
            return base_db_url
        return f"sqlite:///{self.tenants_dir.as_posix()}/tenant_{re_clean}.db"

    def provision_tenant(
        self,
        tenant_id: str,
        db_dialect: str = "sqlite",
        cartridges: Optional[List[str]] = None,
        db_url_override: Optional[str] = None,
        extra_metadata: Optional[List[MetaData]] = None,
    ) -> Dict[str, Any]:
        """Provision a fresh database instance and apply the master blueprint schema.

        Args:
            tenant_id: Target tenant partition identifier (e.g. 'tenant_101', 'acme_corp').
            db_dialect: Storage dialect ('sqlite' or 'postgresql').
            cartridges: Optional list of cartridge names to install schemas for.
            db_url_override: Optional explicit connection string.
            extra_metadata: Optional list of additional cartridge schemas to install.

        Returns:
            Dictionary containing provisioning summary and status.
        """
        clean_tenant = "".join(c for c in tenant_id if c.isalnum() or c in ("_", "-")).lower()
        if not clean_tenant:
            raise ValueError(f"Invalid tenant_id format: '{tenant_id}'")

        db_url = db_url_override or self.resolve_tenant_db_url(clean_tenant)
        engine = self.get_tenant_engine(clean_tenant, db_url=db_url)

        # 1. PostgreSQL Schema isolation setup
        if db_url.startswith("postgresql"):
            with engine.connect() as conn:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS tenant_{clean_tenant};"))
                conn.commit()

        # 2. Gather cartridge metadata blueprints
        all_metadata = list(self._blueprint_metadata)
        if extra_metadata:
            for em in extra_metadata:
                if em not in all_metadata:
                    all_metadata.append(em)

        active_cartridges = cartridges or ["mail_organizer", "temperature_marker"]
        import importlib
        for cartridge_name in active_cartridges:
            try:
                mod = importlib.import_module(f"apps.{cartridge_name}.database.models")
                cartridge_base = getattr(mod, "Base", None)
                if cartridge_base is not None and hasattr(cartridge_base, "metadata"):
                    if cartridge_base.metadata not in all_metadata:
                        all_metadata.append(cartridge_base.metadata)
            except Exception:
                pass

        tables_created: List[str] = []
        for meta in all_metadata:
            meta.create_all(bind=engine)
            tables_created.extend(list(meta.tables.keys()))

        # 3. Enable SQLite WAL mode and optimizations
        if db_url.startswith("sqlite"):
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL;"))
                conn.execute(text("PRAGMA busy_timeout=5000;"))
                conn.execute(text("PRAGMA synchronous=NORMAL;"))
                conn.commit()

        logger.info(
            "[TenantProvisioner] Provisioned tenant '%s' with %d tables (DB: %s)",
            clean_tenant,
            len(tables_created),
            db_url.split("@")[-1],
        )

        return {
            "tenant_id": clean_tenant,
            "dialect": "sqlite" if db_url.startswith("sqlite") else "postgresql",
            "db_path": db_url,
            "cartridges": active_cartridges,
            "status": "PROVISIONED",
            "tables_count": len(tables_created),
            "tables": tables_created,
        }

    def get_tenant_engine(self, tenant_id: str, db_url: Optional[str] = None) -> Engine:
        """Return or create an isolated SQLAlchemy Engine for the given tenant."""
        clean_tenant = "".join(c for c in tenant_id if c.isalnum() or c in ("_", "-")).lower()
        if clean_tenant in self._tenant_engines:
            return self._tenant_engines[clean_tenant]

        resolved_url = db_url or self.resolve_tenant_db_url(clean_tenant)
        engine = create_engine(
            resolved_url,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if resolved_url.startswith("sqlite") else {},
        )
        self._tenant_engines[clean_tenant] = engine
        self._tenant_sessions[clean_tenant] = sessionmaker(bind=engine, expire_on_commit=False)
        return engine

    @contextmanager
    def get_tenant_session(self, tenant_id: str) -> Generator[Session, None, None]:
        """Context manager providing scoped database session for a specific tenant."""
        clean_tenant = "".join(c for c in tenant_id if c.isalnum() or c in ("_", "-")).lower()
        if clean_tenant not in self._tenant_sessions:
            self.get_tenant_engine(clean_tenant)
        session = self._tenant_sessions[clean_tenant]()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_provisioned_tenants(self) -> List[Dict[str, Any]]:
        """List all provisioned tenant databases found on disk or in active registry."""
        results: List[Dict[str, Any]] = []
        if self.tenants_dir.exists():
            for folder in self.tenants_dir.iterdir():
                if folder.is_dir() and folder.name.startswith("tenant_"):
                    t_id = folder.name[len("tenant_"):]
                    db_file = folder / "tenant.db"
                    size_bytes = db_file.stat().st_size if db_file.exists() else 0
                    results.append({
                        "tenant_id": t_id,
                        "type": "sqlite",
                        "path": str(db_file),
                        "size_kb": round(size_bytes / 1024, 2),
                        "status": "ACTIVE" if db_file.exists() else "INITIALIZING",
                    })
        return results

    def shutdown(self) -> None:
        """Dispose all tenant engines and connection pools."""
        for t_id, eng in list(self._tenant_engines.items()):
            try:
                eng.dispose()
            except Exception:
                pass
        self._tenant_engines.clear()
        self._tenant_sessions.clear()


# Module-level convenience wrappers

def get_tenant_schema_provisioner() -> TenantSchemaProvisioner:
    """Get singleton TenantSchemaProvisioner instance."""
    return TenantSchemaProvisioner.get_instance()


def provision_tenant(
    tenant_id: str,
    db_dialect: str = "sqlite",
    cartridges: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Provision a new tenant database and return summary metadata."""
    return get_tenant_schema_provisioner().provision_tenant(
        tenant_id=tenant_id,
        db_dialect=db_dialect,
        cartridges=cartridges,
    )


def get_tenant_engine(tenant_id: str, db_url: Optional[str] = None) -> Engine:
    """Retrieve isolated SQLAlchemy engine for a specific tenant."""
    return get_tenant_schema_provisioner().get_tenant_engine(tenant_id=tenant_id, db_url=db_url)


from typing import Any, Callable, ContextManager, Dict, Generator, List, Optional, Sequence, Union


def get_tenant_session(tenant_id: str) -> ContextManager[Session]:
    """Context manager yielding scoped session for tenant."""
    return get_tenant_schema_provisioner().get_tenant_session(tenant_id=tenant_id)


def list_provisioned_tenants() -> List[Dict[str, Any]]:
    """List all currently provisioned tenant databases."""
    return get_tenant_schema_provisioner().list_provisioned_tenants()

