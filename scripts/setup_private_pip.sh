#!/usr/bin/env bash
# Copyright 2026 Mahendra GURAV
# Licensed under the Apache License, Version 2.0.

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <github_username> <github_token> [org_name]"
    exit 1
fi

GITHUB_USER="$1"
GITHUB_TOKEN="$2"
ORG="${3:-apex}"

PIP_DIR="$HOME/.config/pip"
mkdir -p "$PIP_DIR"

PIP_CONF="$PIP_DIR/pip.conf"
INDEX_URL="https://${GITHUB_USER}:${GITHUB_TOKEN}@nuget.pkg.github.com/${ORG}/simple/"

cat <<EOF > "$PIP_CONF"
[global]
extra-index-url = $INDEX_URL
EOF

echo "======================================================================"
echo "  PRIVATE PACKAGE REGISTRY CONFIGURED SUCCESSFULLY"
echo "======================================================================"
echo "Config Path : $PIP_CONF"
echo "Registry    : GitHub Packages ($ORG)"
echo ""
echo "You can now install packages directly with standard pip commands:"
echo "  pip install release100-core"
echo "  pip install release100-cartridge-temperature-marker"
echo "  pip install release100-cartridge-mail-organizer"
echo "======================================================================"
