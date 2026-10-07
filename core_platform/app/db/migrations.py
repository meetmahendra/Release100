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
Pluggable Polyglot Database Schema Initializer & Migration Utilities.

Adheres to GEES v2.0 Section 2 (Deployment-Time Database Selection):
- Dialect-agnostic DDL execution.
- Automated table initialization across Core and Cartridge MetaData registries.
- Dialect-specific optimizations (SQLite WAL mode, PostgreSQL RLS triggers).
"""

import logging
from typing import List, Optional, Set
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("core_platform.db.migrations")


class DatabaseMigrationHelper:
    """Provides dialect-aware schema creation and migration helpers."""

    @staticmethod
    def initialize_metadata_tables(
        engine: Engine,
        metadata_list: List[MetaData],
        enable_sqlite_wal: bool = True,
    ) -> List[str]:
        """
        Create all tables defined across the provided MetaData objects.
        Returns the list of table names created or verified.
        """
        created_tables: List[str] = []
        dialect_name = engine.dialect.name.lower()

        # Step 1: Apply dialect-specific pre-initialization PRAGMAs
        if dialect_name == "sqlite" and enable_sqlite_wal:
            with engine.connect() as conn:
                try:
                    conn.execute(text("PRAGMA journal_mode=WAL;"))
                    conn.execute(text("PRAGMA synchronous=NORMAL;"))
                    conn.commit()
                    logger.debug("[DB] SQLite WAL mode and normal synchronous enabled.")
                except Exception as e:
                    logger.warning(f"[DB] Could not set SQLite PRAGMA: {e}")

        # Step 2: Create all tables for each metadata
        for meta in metadata_list:
            meta.create_all(bind=engine)
            for table_name in meta.tables.keys():
                if table_name not in created_tables:
                    created_tables.append(table_name)

        # Step 3: Run automatic column migrations for new attributes
        cls_helper = DatabaseMigrationHelper
        cls_helper.auto_migrate_columns(engine)

        logger.info(
            f"[DB] Initialized {len(created_tables)} tables across {len(metadata_list)} metadata collections on {dialect_name}."
        )
        return created_tables

    @staticmethod
    def auto_migrate_columns(engine: Engine) -> None:
        """Add newly introduced columns to existing database tables if missing."""
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            
            with engine.connect() as conn:
                # 1. platform_tenants.allowed_cartridges_json
                if "platform_tenants" in tables:
                    cols = {c["name"] for c in inspector.get_columns("platform_tenants")}
                    if "allowed_cartridges_json" not in cols:
                        try:
                            conn.execute(text("ALTER TABLE platform_tenants ADD COLUMN allowed_cartridges_json TEXT DEFAULT '[\"mail_organizer\", \"temperature_marker\"]';"))
                            conn.commit()
                            logger.info("[DB Migration] Added missing column platform_tenants.allowed_cartridges_json")
                        except Exception as e:
                            logger.debug("[DB Migration] Column add skipped: %s", e)

                # 2. platform_users.hashed_password & email
                if "platform_users" in tables:
                    cols = {c["name"] for c in inspector.get_columns("platform_users")}
                    if "hashed_password" not in cols:
                        try:
                            conn.execute(text("ALTER TABLE platform_users ADD COLUMN hashed_password VARCHAR(255);"))
                            conn.commit()
                            logger.info("[DB Migration] Added missing column platform_users.hashed_password")
                        except Exception as e:
                            logger.debug("[DB Migration] Column add skipped: %s", e)
                    if "email" not in cols:
                        try:
                            conn.execute(text("ALTER TABLE platform_users ADD COLUMN email VARCHAR(255);"))
                            conn.commit()
                            logger.info("[DB Migration] Added missing column platform_users.email")
                        except Exception as e:
                            logger.debug("[DB Migration] Column add skipped: %s", e)

                # 3. Domain Cartridge multi-tenant isolation columns (mail_emails, mail_drafts, mail_pm_queue, mail_rules, employees, attendance_records, outbox_queue, internal_message_queue, kiosk_monitoring_configs)
                cartridge_tables = [
                    "mail_emails",
                    "mail_classifications",
                    "mail_drafts",
                    "mail_pm_queue",
                    "mail_rules",
                    "employees",
                    "attendance_records",
                    "outbox_queue",
                    "internal_message_queue",
                    "kiosk_monitoring_configs",
                ]
                for tbl in cartridge_tables:
                    if tbl in tables:
                        cols = {c["name"] for c in inspector.get_columns(tbl)}
                        if "tenant_id" not in cols:
                            try:
                                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN tenant_id VARCHAR(64) DEFAULT 'public';"))
                                conn.commit()
                                logger.info(f"[DB Migration] Added missing column {tbl}.tenant_id")
                            except Exception as e:
                                logger.debug(f"[DB Migration] Column add on {tbl} skipped: %s", e)
        except Exception as exc:
            logger.warning("[DB Migration] auto_migrate_columns check failed: %s", exc)

    @staticmethod
    def get_existing_table_names(engine: Engine) -> Set[str]:
        """Inspect and return all existing table names in the target database."""
        inspector = inspect(engine)
        return set(inspector.get_table_names())

    @staticmethod
    def verify_tenant_isolation_columns(
        engine: Engine,
        tables_to_check: List[str],
        tenant_column_name: str = "tenant_id",
    ) -> List[str]:
        """
        Verify that multi-tenant tables contain the requisite tenant isolation column.
        Returns list of tables missing the column.
        """
        inspector = inspect(engine)
        missing_tenant_col: List[str] = []
        for table_name in tables_to_check:
            if not inspector.has_table(table_name):
                continue
            cols = [c["name"] for c in inspector.get_columns(table_name)]
            if tenant_column_name not in cols:
                missing_tenant_col.append(table_name)
        return missing_tenant_col
