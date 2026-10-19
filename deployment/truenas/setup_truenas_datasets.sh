#!/usr/bin/env bash
# =============================================================================
# TrueNAS SCALE (ElectricEel-24.10.0.2) ZFS Appdata Dataset Setup Script
# Copyright 2026 Mahendra GURAV | Apache License 2.0
# [CODE-MARKER: TN-ENV-01]
#
# Run once via TrueNAS System -> Shell (or SSH) to create persistent host
# directories owned by the TrueNAS built-in 'apps' user (UID 568 / GID 568).
# =============================================================================

set -euo pipefail

TRUENAS_APPDATA_ROOT="${1:-/mnt/tank/apps/release100}"

echo "[TrueNAS-Setup] Creating Release100 ZFS host directories under: ${TRUENAS_APPDATA_ROOT}"

mkdir -p \
    "${TRUENAS_APPDATA_ROOT}/config" \
    "${TRUENAS_APPDATA_ROOT}/postgres-shared" \
    "${TRUENAS_APPDATA_ROOT}/postgres-mail" \
    "${TRUENAS_APPDATA_ROOT}/postgres-temp" \
    "${TRUENAS_APPDATA_ROOT}/core/data" \
    "${TRUENAS_APPDATA_ROOT}/core/logs/audit_partitions" \
    "${TRUENAS_APPDATA_ROOT}/core/credentials" \
    "${TRUENAS_APPDATA_ROOT}/ops/data" \
    "${TRUENAS_APPDATA_ROOT}/ops/logs" \
    "${TRUENAS_APPDATA_ROOT}/mail_organizer/data" \
    "${TRUENAS_APPDATA_ROOT}/mail_organizer/logs" \
    "${TRUENAS_APPDATA_ROOT}/mail_organizer/credentials" \
    "${TRUENAS_APPDATA_ROOT}/temperature_marker/data" \
    "${TRUENAS_APPDATA_ROOT}/temperature_marker/logs"

chown -R 568:568 "${TRUENAS_APPDATA_ROOT}"
chmod -R 750 "${TRUENAS_APPDATA_ROOT}"

echo "[TrueNAS-Setup] Done. Ownership set to 568:568 (TrueNAS 'apps' user)."
