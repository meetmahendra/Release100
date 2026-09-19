#!/usr/bin/env bash
# =============================================================================
# Release100 Docker Container Entrypoint
# Copyright 2026 Mahendra GURAV | Apache License 2.0
#
# Runs on container start: applies Alembic migrations, then starts uvicorn.
# =============================================================================

set -euo pipefail

echo "[Release100] Container starting..."
echo "[Release100] Running database migrations..."

# Run Alembic schema migrations before binding sockets (Plan 05 §2)
alembic upgrade head || {
    echo "[Release100] WARNING: Alembic migration failed — continuing with existing schema."
}

echo "[Release100] Starting Core Platform on port ${ORCHESTRATOR_PORT:-8002}..."

exec uvicorn core_platform.main:app \
    --host 0.0.0.0 \
    --port "${ORCHESTRATOR_PORT:-8002}" \
    --workers 1 \
    --log-level info \
    --no-access-log
