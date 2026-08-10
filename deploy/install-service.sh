#!/usr/bin/env bash
# Run once as root (sudo) — installs the systemd unit and secrets file.
# Everything else is already handled by deploy/setup.sh (run as chem_epics).

set -euo pipefail

SERVICE_USER="${1:-chem_epics}"
CONDA_PATH="${2:-/home/${SERVICE_USER}/anaconda3}"
CONDA_ENV="aps-esaf-fetcher"
INSTALL_DIR="/home/${SERVICE_USER}/aps-esaf-fetcher"
SECRETS_DIR="/etc/aps-esaf-fetcher"
ENV_UVICORN="$CONDA_PATH/envs/$CONDA_ENV/bin/uvicorn"

# ── 1. Secrets file ──────────────────────────────────────────────────────────
echo "==> Creating secrets file at $SECRETS_DIR/secrets.env"
mkdir -p "$SECRETS_DIR"
if [ ! -f "$SECRETS_DIR/secrets.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$SECRETS_DIR/secrets.env"
    sed -i "s|DB_PATH=.*|DB_PATH=/home/${SERVICE_USER}/.aps-esaf-fetcher/esaf.db|" \
        "$SECRETS_DIR/secrets.env"
    echo "  Created — fill in DM_USERNAME and DM_PASSWORD before starting."
fi
chmod 600 "$SECRETS_DIR/secrets.env"
chown root:root "$SECRETS_DIR/secrets.env"

# ── 2. Systemd unit ──────────────────────────────────────────────────────────
echo "==> Installing systemd unit"
sed \
    -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
    -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    -e "s|__ENV_UVICORN__|${ENV_UVICORN}|g" \
    "$INSTALL_DIR/deploy/aps-esaf-fetcher.service" \
    > /etc/systemd/system/aps-esaf-fetcher.service

systemctl daemon-reload
systemctl enable aps-esaf-fetcher.service

echo ""
echo "Done. Next steps:"
echo "  1. Edit $SECRETS_DIR/secrets.env  (DM_USERNAME, DM_PASSWORD, BEAMLINE_NAMES)"
echo "  2. sudo systemctl start aps-esaf-fetcher"
echo "  3. sudo journalctl -fu aps-esaf-fetcher"
