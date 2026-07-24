#!/usr/bin/env bash
set -e

export OPENPLC_WEB_PORT="${OPENPLC_WEB_PORT:-8080}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec ~/OpenPLC_v3/.venv/bin/python3 "$PROJECT_DIR/setup/run_openplc.py"
