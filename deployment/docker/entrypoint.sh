#!/usr/bin/env bash
# =============================================================================
# Release100 Docker Container Entrypoint (Role-Aware Multi-Container Runtime)
# Copyright 2026 Mahendra GURAV | Apache License 2.0
# [CODE-MARKER: TN-ENTRY-01]
#
# Runs on container start: applies Alembic migrations, configures role-scoped
# cartridge activation, and starts uvicorn on the target container port.
# =============================================================================

set -euo pipefail

ROLE="${CONTAINER_ROLE:-unified}"
BIND_PORT="${PORT:-${ORCHESTRATOR_PORT:-8002}}"

echo "[Release100] Container starting (role=${ROLE}, port=${BIND_PORT})..."

case "${ROLE}" in
    ops_control)
        export ENABLED_APPLICATIONS="${ENABLED_APPLICATIONS:-[]}"
        ;;
    cartridge_mail_organizer)
        export ENABLED_APPLICATIONS="${ENABLED_APPLICATIONS:-[\"mail_organizer\"]}"
        ;;
    cartridge_temperature_marker)
        export ENABLED_APPLICATIONS="${ENABLED_APPLICATIONS:-[\"temperature_marker\"]}"
        ;;
    core|unified|*)
        ;;
esac

echo "[Release100] Running database migrations..."
alembic upgrade head || {
    echo "[Release100] WARNING: Alembic migration notice — continuing with SQLAlchemy create_all fallback."
}

echo "[Release100] Starting Release100 (${ROLE}) on port ${BIND_PORT}..."

exec uvicorn core_platform.main:app \
    --host 0.0.0.0 \
    --port "${BIND_PORT}" \
    --workers 1 \
    --log-level info \
    --no-access-log
