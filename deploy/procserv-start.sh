#!/usr/bin/env bash
# Start aps-esaf-fetcher under procServ (no root needed).
# Adjust CONDA_PATH and INSTALL_DIR if different from defaults.

set -euo pipefail

SERVICE_USER="${USER}"
CONDA_PATH="${HOME}/anaconda3"
CONDA_ENV="aps-esaf-fetcher"
INSTALL_DIR="${HOME}/aps-esaf-fetcher"
CTRL_PORT=60640   # procServ management port — choose a free port
LOG_FILE=/tmp/aps-esaf-fetcher.log
SECRETS="/etc/aps-esaf-fetcher/secrets.env"

ENV_UVICORN="$CONDA_PATH/envs/$CONDA_ENV/bin/uvicorn"

# Load credentials
[ -f "$SECRETS" ] && set -a && source "$SECRETS" && set +a

exec procServ \
    --logfile "$LOG_FILE" \
    --name aps-esaf-fetcher \
    --noautorestart \
    "$CTRL_PORT" \
    "$ENV_UVICORN" app.main:app \
        --app-dir "$INSTALL_DIR" \
        --host 0.0.0.0 \
        --port "${PORT:-8088}" \
        --log-level info
