#!/usr/bin/env bash
# Install aps-esaf-fetcher as a systemd service.
# Run as root: sudo bash deploy/install.sh

set -euo pipefail

INSTALL_DIR=/opt/aps-esaf-fetcher
SERVICE_USER=chem_epics
SECRETS_DIR=/etc/aps-esaf-fetcher

echo "==> Creating install directory $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --exclude '.git' --exclude 'venv' --exclude '*.pyc' . "$INSTALL_DIR/"

echo "==> Creating Python venv"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo "==> Setting ownership to $SERVICE_USER"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "==> Creating secrets directory $SECRETS_DIR"
mkdir -p "$SECRETS_DIR"
if [ ! -f "$SECRETS_DIR/secrets.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$SECRETS_DIR/secrets.env"
    echo ""
    echo "  *** Edit $SECRETS_DIR/secrets.env and fill in DM_USERNAME and DM_PASSWORD ***"
fi
chmod 600 "$SECRETS_DIR/secrets.env"
chown "$SERVICE_USER:$SERVICE_USER" "$SECRETS_DIR/secrets.env"

echo "==> Installing systemd unit"
cp "$INSTALL_DIR/deploy/aps-esaf-fetcher.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable aps-esaf-fetcher.service

echo ""
echo "Done. Start with:  systemctl start aps-esaf-fetcher"
echo "Check status with: systemctl status aps-esaf-fetcher"
echo "View logs with:    journalctl -fu aps-esaf-fetcher"
