#!/usr/bin/env bash
# Development launcher — loads .env and starts uvicorn with auto-reload.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && export $(grep -v '^#' .env | xargs)
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8088}" --reload
