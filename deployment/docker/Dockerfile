# =============================================================================
# Release100 Multi-Stage Docker Build
# Copyright 2026 Mahendra GURAV | Apache License 2.0
#
# Stage 1 (builder): Install Python dependencies in an isolated layer.
# Stage 2 (runtime): Minimal image with only production artifacts.
# =============================================================================

# ── Stage 1: Dependency Builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install system build tools needed for some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency manifests first (Docker layer caching)
COPY core_platform/requirements.txt ./

# Create virtual environment and install dependencies
RUN python -m venv /venv && \
    /venv/bin/pip install --upgrade pip --quiet && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Production Runtime ───────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="Mahendra GURAV" \
      version="1.3.0" \
      description="Release100 KioskNode Core Platform — Production Container"

# Runtime system libraries (OpenCV, face recognition, audio)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash kiosk

# Copy virtual environment from builder
COPY --from=builder /venv /venv

# Copy application source
WORKDIR /opt/release100
COPY . .

# Remove development artifacts
RUN find . -name "*.pyc" -delete && \
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf tests/ .git/ .env

# Create log and credential directories
RUN mkdir -p logs/audit_partitions .local_credentials && \
    chown -R kiosk:kiosk /opt/release100

# Switch to non-root service user
USER kiosk

# Activate venv for all subsequent commands
ENV PATH="/venv/bin:$PATH" \
    PYTHONIOENCODING="utf-8" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1"

# Expose platform ports
EXPOSE 8002
EXPOSE 8001

# Health check — polls /health endpoint every 30s
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

ENTRYPOINT ["bash", "deployment/docker/entrypoint.sh"]
