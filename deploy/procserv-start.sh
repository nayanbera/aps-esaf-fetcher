#!/usr/bin/env bash
# Start aps-esaf-fetcher under procServ (alternative to systemd).
# Adjust paths to match your installation.

INSTALL_DIR=/opt/aps-esaf-fetcher
PORT=8088
CTRL_PORT=60640   # procServ management port (choose a free port)
LOG=/tmp/aps-esaf-fetcher.log

set -a
source /etc/aps-esaf-fetcher/secrets.env
set +a

exec procServ \
    --logfile "$LOG" \
    --name aps-esaf-fetcher \
    --noautorestart \
    "$CTRL_PORT" \
    "$INSTALL_DIR/venv/bin/uvicorn" app.main:app \
        --app-dir "$INSTALL_DIR" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --log-level info
