# Alembic Migration Environment
# Copyright 2026 Mahendra GURAV | Apache License 2.0
#
# Alembic env.py for Release100 multi-app schema migrations.
# Manages schema versioning for temperature_marker and mail_organizer SQLAlchemy models.

from logging.config import fileConfig
import os
import sys
from pathlib import Path

from alembic import context  # type: ignore[import-not-found]
from sqlalchemy import engine_from_config, pool

# ── Ensure project root is on PYTHONPATH ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ── Import all model metadata ─────────────────────────────────────────────────
from apps.temperature_marker.database.models import Base as TMBase  # noqa: E402
from apps.mail_organizer.database.models import Base as MOBase  # noqa: E402

# Alembic config object
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Combined target metadata — all app models
target_metadata = [TMBase.metadata, MOBase.metadata]


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
