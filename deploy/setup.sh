#!/usr/bin/env bash
# Run as chem_epics — no sudo needed.
# Sets up the conda env and installs all dependencies.

set -euo pipefail

CONDA_PATH="${1:-${HOME}/anaconda3}"
CONDA_ENV="aps-esaf-fetcher"
INSTALL_DIR="${HOME}/aps-esaf-fetcher"
REPO_URL="https://github.com/nayanbera/aps-esaf-fetcher.git"

CONDA_BIN="$CONDA_PATH/bin/conda"
ENV_PIP="$CONDA_PATH/envs/$CONDA_ENV/bin/pip"

# ── 1. Clone or update repo ──────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "==> Updating repo"
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "==> Cloning repo"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# ── 2. Create conda env (skip if already exists) ────────────────────────────
if [ ! -f "$CONDA_PATH/envs/$CONDA_ENV/bin/python" ]; then
    echo "==> Creating conda env '$CONDA_ENV'"
    "$CONDA_BIN" create -n "$CONDA_ENV" python=3.10 -y
else
    echo "==> Conda env '$CONDA_ENV' already exists"
fi

# ── 3. Python dependencies ───────────────────────────────────────────────────
echo "==> Installing Python dependencies"
"$ENV_PIP" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ── 4. APS dm library ────────────────────────────────────────────────────────
echo "==> Installing aps-dm-api"
"$CONDA_BIN" install -n "$CONDA_ENV" aps-anl-tag::aps-dm-api -y

echo ""
echo "Done. Now ask your admin to run (once):"
echo "  sudo bash $INSTALL_DIR/deploy/install-service.sh"
