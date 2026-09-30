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
Alembic Migration Environment.
Alembic env.py for multi-app schema migrations.
"""

from logging.config import fileConfig
import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Ensure project root is on PYTHONPATH ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ── Dynamically collect all cartridge MetaData via PluginLoader ───────────────
# Each loaded cartridge exposes its SQLAlchemy MetaData via get_metadata().
# Adding a new app cartridge automatically includes its tables — no changes here.
target_metadata = []
try:
    from core_platform.app.plugin_engine.loader import PluginLoader
    from core_platform.app.config import settings

    _loader = PluginLoader(enabled_apps=settings.ENABLED_APPLICATIONS)
    _loaded = _loader.load_all()
    for _app_instance in _loaded.values():
        _meta = _app_instance.get_metadata()
        if _meta is not None:
            target_metadata.append(_meta)
except Exception as _exc:
    # Fallback: try dynamic cartridge discovery so offline dev still works.
    import importlib
    import warnings
    warnings.warn(f"[Alembic] PluginLoader metadata collection failed: {_exc}. Falling back to dynamic cartridge models.")
    for _app_name in ["temperature_marker", "mail_organizer"]:
        try:
            _mod = importlib.import_module(f"apps.{_app_name}.database.models")
            _base = getattr(_mod, "Base", None)
            if _base is not None and hasattr(_base, "metadata"):
                target_metadata.append(_base.metadata)
        except Exception:
            pass


# Alembic config object
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_url() -> str:
    """Resolve the database URL: .env override > alembic.ini > SQLite default."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return str(url)
    return str(config.get_main_option("sqlalchemy.url", "sqlite:///logs/release100.db"))


def run_migrations_offline() -> None:
    """Run migrations in offline mode (no live DB connection needed)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,  # Required for SQLite ALTER TABLE support
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode (live DB connection)."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,  # Required for SQLite ALTER TABLE support
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
