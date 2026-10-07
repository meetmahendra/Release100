#!/usr/bin/env bash
# =============================================================================
# Release100 Linux Systemd Service Installer
# Copyright 2026 Mahendra GURAV | Apache License 2.0
#
# Usage: sudo bash install.sh [--uninstall]
# Requirements: Ubuntu 20.04+ / Debian 10+ | Python 3.11+
# =============================================================================

set -euo pipefail

INSTALL_DIR="/opt/release100"
SERVICE_NAME="release100"
SERVICE_USER="kiosk"
SERVICE_GROUP="kiosk"
PYTHON_MIN="3.11"

# ── Colour output helpers ─────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── Require root ─────────────────────────────────────────────────────────────
[[ "$EUID" -ne 0 ]] && error "Run as root: sudo bash install.sh"

# ── Uninstall mode ───────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    info "Uninstalling Release100 systemd service..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    info "Service removed. Data at $INSTALL_DIR is preserved."
    exit 0
fi

# ── Preflight checks ─────────────────────────────────────────────────────────
info "Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || error "python3 not found. Install Python ${PYTHON_MIN}+"
command -v pip3 >/dev/null 2>&1    || error "pip3 not found."

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python version: $PYTHON_VERSION"

# ── Create service user ───────────────────────────────────────────────────────
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    info "Creating service user: $SERVICE_USER"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# ── Install directory ────────────────────────────────────────────────────────
info "Setting up install directory: $INSTALL_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "$SCRIPT_DIR" != "$INSTALL_DIR" ]]; then
    mkdir -p "$INSTALL_DIR"
    rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        "$SCRIPT_DIR/" "$INSTALL_DIR/"
fi

# ── Virtual environment ──────────────────────────────────────────────────────
info "Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip --quiet

info "Installing Python dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/core_platform/requirements.txt" --quiet

# ── Logs directory ────────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR/logs/audit_partitions"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/logs"

# ── .env setup ────────────────────────────────────────────────────────────────
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    warn ".env not found — copying platform.env.example as template"
    cp "$INSTALL_DIR/config/platform.env.example" "$INSTALL_DIR/.env"
    warn "IMPORTANT: Edit $INSTALL_DIR/.env and fill in your API keys before starting."
fi

# ── Alembic database migrations ───────────────────────────────────────────────
info "Running database migrations (Alembic)..."
cd "$INSTALL_DIR"
"$INSTALL_DIR/.venv/bin/alembic" upgrade head || warn "Alembic migration failed — DB may need manual attention."

# ── Install systemd service ───────────────────────────────────────────────────
info "Installing systemd service unit..."
SERVICE_FILE="$INSTALL_DIR/deployment/linux_systemd/${SERVICE_NAME}.service"

# Update WorkingDirectory in service file to match INSTALL_DIR
sed "s|/opt/release100|$INSTALL_DIR|g" "$SERVICE_FILE" \
    > "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# ── Final ownership ────────────────────────────────────────────────────────────
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/.env"

# ── Start service ─────────────────────────────────────────────────────────────
info "Starting Release100 service..."
systemctl start "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    info "✅ Release100 is running!"
    info "   Admin dashboard: http://localhost:8002"
    info "   Health endpoint: http://localhost:8002/health"
    info "   View logs:       journalctl -u $SERVICE_NAME -f"
else
    error "Service failed to start. Check: journalctl -u $SERVICE_NAME -n 50"
fi
