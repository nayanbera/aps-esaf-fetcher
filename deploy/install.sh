#!/usr/bin/env bash
# Install aps-esaf-fetcher on the RE machine.
#
# Usage (run from the repo root):
#   sudo bash deploy/install.sh [chem_epics] [/home/chem_epics/anaconda3]
#
# The script must be run as root (sudo) so it can install the systemd unit
# and create the secrets file under /etc/. Everything else is owned by the
# service user.

set -euo pipefail

SERVICE_USER="${1:-chem_epics}"
CONDA_PATH="${2:-/home/chem_epics/anaconda3}"
CONDA_ENV="aps-esaf-fetcher"
INSTALL_DIR="/home/${SERVICE_USER}/aps-esaf-fetcher"
SECRETS_DIR="/etc/aps-esaf-fetcher"
REPO_URL="https://github.com/nayanbera/aps-esaf-fetcher.git"

# ── 1. Clone or update the repo ─────────────────────────────────────────────
echo "==> Setting up code at $INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "    Pulling latest changes"
    sudo -u "$SERVICE_USER" git -C "$INSTALL_DIR" pull --ff-only
else
    sudo -u "$SERVICE_USER" git clone "$REPO_URL" "$INSTALL_DIR"
fi

# ── 2. Create conda environment ──────────────────────────────────────────────
CONDA_BIN="$CONDA_PATH/bin/conda"
ENV_PYTHON="$CONDA_PATH/envs/$CONDA_ENV/bin/python"
ENV_PIP="$CONDA_PATH/envs/$CONDA_ENV/bin/pip"
ENV_UVICORN="$CONDA_PATH/envs/$CONDA_ENV/bin/uvicorn"

if [ ! -f "$ENV_PYTHON" ]; then
    echo "==> Creating conda environment '$CONDA_ENV' (Python 3.10)"
    sudo -u "$SERVICE_USER" "$CONDA_BIN" create -n "$CONDA_ENV" python=3.10 -y
else
    echo "==> Conda environment '$CONDA_ENV' already exists"
fi

echo "==> Installing Python dependencies"
sudo -u "$SERVICE_USER" "$ENV_PIP" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ── 3. Install dm library (APS Data Management) ──────────────────────────────
echo "==> Installing aps-dm-api into conda env '$CONDA_ENV'"
sudo -u "$SERVICE_USER" "$CONDA_BIN" install -n "$CONDA_ENV" aps-anl-tag::aps-dm-api -y

# ── 4. Secrets file (root-owned, mode 600) ───────────────────────────────────
echo "==> Setting up secrets at $SECRETS_DIR/secrets.env"
mkdir -p "$SECRETS_DIR"
if [ ! -f "$SECRETS_DIR/secrets.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$SECRETS_DIR/secrets.env"
    # Point DB into the service user's home by default
    sed -i "s|DB_PATH=.*|DB_PATH=/home/${SERVICE_USER}/.aps-esaf-fetcher/esaf.db|" \
        "$SECRETS_DIR/secrets.env"
    echo "  Created $SECRETS_DIR/secrets.env — fill in DM_USERNAME and DM_PASSWORD"
fi
chmod 600 "$SECRETS_DIR/secrets.env"

# ── 5. Patch and install systemd unit ────────────────────────────────────────
echo "==> Installing systemd unit"
UNIT_SRC="$INSTALL_DIR/deploy/aps-esaf-fetcher.service"
UNIT_DST="/etc/systemd/system/aps-esaf-fetcher.service"

# Substitute real paths into the unit file
sed \
    -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
    -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    -e "s|__ENV_UVICORN__|${ENV_UVICORN}|g" \
    "$UNIT_SRC" > "$UNIT_DST"

systemctl daemon-reload
systemctl enable aps-esaf-fetcher.service

echo ""
echo "Done."
echo ""
echo "Next steps:"
echo "  1. Edit $SECRETS_DIR/secrets.env (DM_USERNAME, DM_PASSWORD, BEAMLINE_NAMES, …)"
echo "  2. Install the dm conda package (see above)"
echo "  3. sudo systemctl start aps-esaf-fetcher"
echo "  4. sudo journalctl -fu aps-esaf-fetcher"
