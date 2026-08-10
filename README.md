# aps-esaf-fetcher

A self-contained web service that fetches Experiment Safety Assessment Form (ESAF) data
from the APS Data Management API, stores it in a local SQLite database, and exposes a
browsable web UI and a REST API for querying.

Built with **FastAPI + Jinja2 + HTMX + Bootstrap 5**. No frontend build step.

---

## Features

- Periodic auto-sync from the APS DM API (configurable interval, default 24 h)
- Manual "Sync Now" trigger from the web UI
- Browse and filter ESAFs by year, beamline, status, or free-text search
- Full detail view: users, funding sources, raw API response
- Inline editing: notes and custom user-defined fields per ESAF
- Custom field definitions: add any field type (text, number, date, select, textarea) without schema migrations
- Statistics dashboard: totals, by-year, by-beamline, by-institution, by-funding-source, top users
- REST JSON API for downstream apps (e.g. EasyBluesky)
- systemd unit file and procServ launcher for production deployment
- User-edited notes and custom fields are **never overwritten by a sync**

---

## Quick start (development)

```bash
git clone <this-repo> aps-esaf-fetcher
cd aps-esaf-fetcher
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # edit and fill in credentials
bash launch.sh
# open http://localhost:8088
```

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `DM_USERNAME` | — | APS DM API username (required) |
| `DM_PASSWORD` | — | APS DM API password (required) |
| `DM_URL` | `https://catdtn03.aps.anl.gov:11337` | DM API base URL |
| `STATION_ID` | `CHMCARS` | APS station ID |
| `BEAMLINE_NAMES` | `15-ID-C,D` | Pipe-separated beamline name strings |
| `SYNC_YEARS` | current + previous year | Comma-separated years to sync |
| `SYNC_INTERVAL_HOURS` | `24` | Auto-sync interval (0 = disabled) |
| `DB_PATH` | `~/.aps-esaf-fetcher/esaf.db` | SQLite database path |
| `HOST` | `0.0.0.0` | Bind host |
| `PORT` | `8088` | Bind port |

---

## Production deployment (systemd)

The install script clones the repo, creates a `conda` environment named
`aps-esaf-fetcher`, installs dependencies, patches the systemd unit with real
paths, and places credentials in `/etc/aps-esaf-fetcher/secrets.env` (mode 600).

```bash
# On the RE machine — the systemd steps require sudo:
cd ~
git clone https://github.com/nayanbera/aps-esaf-fetcher.git
cd aps-esaf-fetcher

# Pass service user and conda prefix if different from defaults
sudo bash deploy/install.sh chem_epics /home/chem_epics/anaconda3

# Fill in credentials
sudo vi /etc/aps-esaf-fetcher/secrets.env

# dm library is installed automatically by install.sh via:
#   conda install aps-anl-tag::aps-dm-api

sudo systemctl start aps-esaf-fetcher
sudo journalctl -fu aps-esaf-fetcher
```

### procServ alternative (no root needed for the process itself)

```bash
# Credentials still need to be at /etc/aps-esaf-fetcher/secrets.env (sudo once)
bash deploy/procserv-start.sh
```

---

## REST API

| Endpoint | Method | Description |
|---|---|---|
| `/api/esafs` | GET | List ESAFs — query params: `year`, `beamline`, `status`, `search`, `limit`, `offset` |
| `/api/esafs/{id}` | GET | Full ESAF detail including users and funding sources |
| `/api/stats` | GET | Aggregate statistics |
| `/api/sync/status` | GET | Last sync info and whether a sync is running |
| `/api/sync/trigger` | POST | Trigger an async sync |

Interactive API docs: `http://<host>:8088/docs`

---

## Project structure

```
app/
  main.py          — FastAPI app, lifespan (DB init + scheduler)
  config.py        — Settings from environment / .env
  db.py            — SQLite schema, CRUD, statistics queries
  sync.py          — DM API fetcher, APScheduler background sync
  routers/
    esafs.py       — ESAF list, detail, edit endpoints
    stats.py       — Statistics page and API
    sync_router.py — Sync control (trigger, status)
    fields.py      — Custom field definition management
  templates/       — Jinja2 templates (base + pages + HTMX partials)
static/            — Minimal CSS overrides
deploy/
  aps-esaf-fetcher.service  — systemd unit
  install.sh                — one-shot install script
  procserv-start.sh         — procServ alternative
```

---

## DM library installation

The `dm` package is provided by APS via the `aps-anl-tag` conda channel and is
not on PyPI. The install script handles this automatically:

```bash
conda install aps-anl-tag::aps-dm-api
```
