# =============================================================================
# Release100 Multi-Stage, Multi-Target Docker Build (TrueNAS SCALE ElectricEel)
# Copyright 2026 Mahendra GURAV | Apache License 2.0
# [CODE-MARKER: TN-DOCKER-01]
#
# Supported Build Targets:
#   - core-runtime                 (ghcr.io/meetmahendra/release100-core)
#   - ops-control                  (ghcr.io/meetmahendra/release100-ops)
#   - cartridge-mail-organizer     (ghcr.io/meetmahendra/release100-mail-organizer)
#   - cartridge-temperature-marker (ghcr.io/meetmahendra/release100-temperature-marker)
#   - runtime                      (default unified image)
# =============================================================================

# ── Stage 1: Dependency Builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install system build tools needed for Python packages and RDBMS drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency manifests first (Docker layer caching)
COPY core_platform/requirements.txt ./

# Create virtual environment and install dependencies + PostgreSQL/MySQL drivers
RUN python -m venv /venv && \
    /venv/bin/pip install --upgrade pip --quiet && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt \
        psycopg2-binary>=2.9.0 \
        pymysql>=1.1.0

# ── Stage 2: Shared Base Runtime (TrueNAS SCALE apps UID/GID 568:568) ─────────
FROM python:3.12-slim AS base-runtime

LABEL maintainer="Mahendra GURAV" \
      version="3.0.32" \
      description="Release100 Multi-Container Platform — TrueNAS SCALE ElectricEel Runtime"

# Runtime system libraries (OpenCV, face recognition, libpq5, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 568 kiosk \
    && useradd -u 568 -g 568 --create-home --shell /bin/bash kiosk

# Copy virtual environment from builder
COPY --from=builder /venv /venv

# Copy application source
WORKDIR /opt/release100
COPY . .

# Install package in editable mode without reinstalling dependencies
RUN /venv/bin/pip install --no-cache-dir --no-deps -e .

# Remove development artifacts
RUN find . -name "*.pyc" -delete && \
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf tests/ .git/ .env

# Create log, data, and credential directories owned by TrueNAS apps UID/GID (568:568)
RUN mkdir -p logs/audit_partitions data .local_credentials && \
    chmod +x deployment/docker/entrypoint.sh && \
    chown -R 568:568 /opt/release100

USER 568:568

ENV PATH="/venv/bin:$PATH" \
    PYTHONIOENCODING="utf-8" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1"

EXPOSE 8000
EXPOSE 8001
EXPOSE 8002
EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-${ORCHESTRATOR_PORT:-8000}}/health || exit 1

ENTRYPOINT ["bash", "deployment/docker/entrypoint.sh"]

# ── Target A: Core Platform & Ingress Container (release100-core) ─────────────
FROM base-runtime AS core-runtime
ENV CONTAINER_ROLE="core" \
    PORT="8000" \
    ORCHESTRATOR_PORT="8000"

# ── Target B: Ops Control Plane Container (release100-ops) ────────────────────
FROM base-runtime AS ops-control
ENV CONTAINER_ROLE="ops_control" \
    PORT="8010" \
    ORCHESTRATOR_PORT="8010" \
    ENABLED_APPLICATIONS="[]"

# ── Target C: Mail Organizer Cartridge Container (release100-mail-organizer) ──
FROM base-runtime AS cartridge-mail-organizer
ENV CONTAINER_ROLE="cartridge_mail_organizer" \
    PORT="8001" \
    ORCHESTRATOR_PORT="8001" \
    ENABLED_APPLICATIONS='["mail_organizer"]'

# ── Target D: Temperature Marker Cartridge Container (release100-temperature-marker) ──
FROM base-runtime AS cartridge-temperature-marker
ENV CONTAINER_ROLE="cartridge_temperature_marker" \
    PORT="8002" \
    ORCHESTRATOR_PORT="8002" \
    ENABLED_APPLICATIONS='["temperature_marker"]'

# ── Default Unified Target (Backward-Compatible Default) ──────────────────────
FROM core-runtime AS runtime
ENV CONTAINER_ROLE="unified" \
    PORT="8002" \
    ORCHESTRATOR_PORT="8002"
