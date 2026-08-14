# aps-esaf-fetcher

A self-contained web service that fetches Experiment Safety Assessment Form (ESAF) data
from the APS Data Management API, stores it in a local SQLite database, and exposes a
browsable web UI and a REST API for querying by downstream apps such as EasyBluesky.

Built with **FastAPI + Jinja2 + HTMX + Bootstrap 5**. No frontend build step.

---

## Features

- **Sync** — Periodic auto-sync from the APS DM API (configurable interval); manual
  trigger + dry-run preview before committing; sync year range 1998 → present
- **Browse** — Filter ESAFs by year, beamline, status, or free-text; full detail view
  with users, funding sources, institution types, and GUP linkage
- **Edit** — Inline notes, custom user-defined fields (text/number/date/select/textarea),
  technique tags — never overwritten by a subsequent sync
- **Import** — Upload a ChemMatCARS-style combined master CSV/XLSX (one row per user
  per ESAF) to bulk-load historical ESAFs, users, institution types, and ESAF–user links
- **Institution classification** — ROR lookup for canonical institution names; imported
  institution types (from CSV) override ROR types; editable country and state per institution
- **Users** — Unique user list, detail view, per-user ESAF history, beamline scientist roster
- **Admin** — Session-based authentication; admin user management; full audit log with
  date/user/action filtering
- **Public REST API** — Unauthenticated JSON endpoints for ESAFs and users, designed for
  consumption by downstream Python apps (EasyBluesky, etc.)
- **Statistics** — Totals, by-year, by-beamline, by-institution, by-funding-source, top users
- **GUP linking** — Associate ESAFs with APS GUP (General User Proposal) records
- **Production-ready** — systemd unit + procServ launcher; WAL-mode SQLite; audit log

---

## Quick start (development)

```bash
git clone https://github.com/nayanbera/aps-esaf-fetcher.git
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
| `BEAMLINE_NAMES` | `15-ID-C,D` | Comma-separated beamline name strings |
| `SYNC_YEARS` | current + previous year | Comma-separated years to sync (1998 – present supported) |
| `SYNC_INTERVAL_HOURS` | `24` | Auto-sync interval (0 = disabled) |
| `DB_PATH` | `~/.aps-esaf-fetcher/esaf.db` | SQLite database path |
| `HOST` | `0.0.0.0` | Bind host |
| `PORT` | `8088` | Bind port |
| `APP_SECRET_KEY` | auto-generated | Session secret (set explicitly in production) |

---

## Admin setup

On first access, navigate to `/admin/login`. Because no admin users exist yet, a
**bootstrap form** appears — enter a name, email, and password to create the first admin.
Subsequent admins can be added from `/admin` once logged in.

Admin credentials are stored with PBKDF2-SHA256 (260 000 iterations). Sessions persist
for 7 days via a signed cookie.

All write actions (sync, import, field edits, admin management) are logged to the audit
log visible at `/admin`.

---

## Importing historical data (master file upload)

Navigate to `/upload` (login required). Two formats are supported:

### A — Combined master file (ChemMatCARS format)

One row per user per ESAF. Accepted columns (case-insensitive):

| Column | Destination |
|---|---|
| `Experiment Id` | ESAF ID (key) |
| `Exp FY` | Fiscal year |
| `Posted Date` | Start date |
| `Pen` | Local/internal ID |
| `Beamline Name` | Beamline |
| `Funding Source` | Funding sources |
| `Research Subject` | Technique |
| `Badge` | User badge (key) |
| `First Name` / `Last Name` | User name |
| `Email` | User email |
| `Inst Name` | Institution name |
| `Institution Type` | Institution type → stored as override in Institutions tab |
| `Gender` | Gender |
| `Employment Level` | Career stage |
| `User Type` | ON-SITE / OFF-SITE per ESAF |
| `Spokesperson` | Y → PI role for this ESAF |

ESAFs not yet in the DB are inserted as stubs (`ESAF {id} (imported)`).
Existing ESAFs and users are updated field-by-field; user-edited notes and
custom fields are never touched.

Clicking **Preview Changes** shows a diff before committing. Click **Apply** to write.

### B — Simple ESAF file

Columns: `esaf_id`, `technique`, `notes`, `pi_group`, `local_id`.

---

## Institutions tab

Shows all unique institution names extracted from users and ESAFs, with:

- **Institution Type** — populated from the imported CSV (takes priority over ROR types).
  Edit via the pencil icon; choose from the standard APS vocabulary:
  `U.S. academic inst.`, `U.S. national laboratory`, `U.S. govt-funded agency/inst.`,
  `U.S. industrial firm`, `U.S. medical school`, `U.S. pvt. research inst.`,
  `Foreign academic inst.`, `Foreign national lab.`, `Foreign industry`,
  `Foreign other`, `No information provided`
- **Country / State** — editable per institution; state falls back to linked users if not set
- **Users / ESAFs** — live counts from the DB
- **ROR lookup** — "Lookup All via ROR" button queries the
  [Research Organization Registry](https://ror.org) to enrich institution records
  with canonical names and country data

---

## Sync

Navigate to `/sync`.

- **Preview** — runs a dry-run against the APS DM API and shows what would be added/updated
- **Sync Now** — fetches and writes immediately
- **Year range** — dropdown covers 1998 to the current year
- **Auto-sync** — configured via `SYNC_INTERVAL_HOURS` in `.env`; runs in a background thread

---

## Public REST API

All endpoints are **unauthenticated read-only GET** routes. No API key required.

Interactive docs: `http://<host>:<port>/docs`

### ESAFs

| Endpoint | Params | Description |
|---|---|---|
| `GET /api/esafs` | `year`, `beamline`, `status`, `search`, `limit` (default 200), `offset` | Paginated ESAF list with user counts |
| `GET /api/esafs/{esaf_id}` | — | Full ESAF detail |

**`GET /api/esafs/{esaf_id}` response:**
```json
{
  "esaf_id": "12345",
  "title": "...",
  "beamline": "14-BM-C",
  "year": 2024,
  "status": "Approved",
  "start_date": "2024-01-15",
  "end_date": "2024-12-31",
  "pi_name": "Jane Smith",
  "pi_badge": "99001",
  "pi_institution": "University of Chicago",
  "technique": "SAXS",
  "local_id": "PEN-123",
  "gup_id": "GUP-12345",
  "funding_sources": ["DOE BES", "NSF"],
  "users": [
    {
      "badge": "99001",
      "first_name": "Jane",
      "last_name": "Smith",
      "email": "jsmith@uchicago.edu",
      "institution": "University of Chicago",
      "institution_type": "U.S. academic inst.",
      "institution_country": "US",
      "institution_state": "IL",
      "role": "PI",
      "user_type": "ON-SITE",
      "gender": "F",
      "employment_level": "Faculty"
    }
  ]
}
```

### Users

| Endpoint | Params | Description |
|---|---|---|
| `GET /api/users` | `q` (name/email/badge search), `badge` (exact), `institution`, `limit`, `offset` | Paginated user list |
| `GET /api/users/{badge}` | — | Full user detail with ESAF history |

**`GET /api/users` response:**
```json
{
  "total": 1523,
  "limit": 200,
  "offset": 0,
  "users": [
    {
      "badge": "99001",
      "first_name": "Jane",
      "last_name": "Smith",
      "email": "jsmith@uchicago.edu",
      "institution": "University of Chicago",
      "institution_type": "U.S. academic inst.",
      "institution_country": "US",
      "institution_state": "IL",
      "gender": "F",
      "employment_level": "Faculty",
      "orcid_id": "0000-0001-2345-6789"
    }
  ]
}
```

**`GET /api/users/{badge}` response:**
```json
{
  "badge": "99001",
  "first_name": "Jane",
  "last_name": "Smith",
  "institution": "University of Chicago",
  "institution_type": "U.S. academic inst.",
  "institution_country": "US",
  "institution_state": "IL",
  "is_beamline_scientist": false,
  "esafs": [
    {
      "esaf_id": "12345",
      "title": "...",
      "year": 2024,
      "beamline": "14-BM-C",
      "status": "Approved",
      "role": "PI",
      "user_type": "ON-SITE"
    }
  ]
}
```

### Other endpoints

| Endpoint | Description |
|---|---|
| `GET /api/stats` | Aggregate statistics (totals, by-year, by-beamline, by-institution) |
| `GET /api/sync/status` | Last sync timestamp and whether a sync is running |
| `POST /api/sync/trigger` | Trigger async sync (params: `from_year`, `to_year`) |

### Python client example

```python
import requests

BASE = "http://your-server:8088"

# Active ESAFs for a beamline this year
esafs = requests.get(f"{BASE}/api/esafs", params={
    "beamline": "14-BM-C",
    "year": 2024,
    "status": "Approved",
}).json()

# Full detail for one ESAF (includes users with institution_type)
esaf = requests.get(f"{BASE}/api/esafs/12345").json()

# Find a user by badge
user = requests.get(f"{BASE}/api/users/99001").json()

# Search users from a given institution
result = requests.get(f"{BASE}/api/users", params={
    "institution": "Chicago", "limit": 50
}).json()
print(result["total"], "users found")
for u in result["users"]:
    print(u["last_name"], u["first_name"], u["institution_type"])
```

---

## Project structure

```
app/
  main.py                    — FastAPI app, lifespan (DB init + scheduler)
  config.py                  — Settings from environment / .env
  auth.py                    — PBKDF2 password hashing, session helpers, audit log
  db.py                      — Proxy functions over the active repository
  repository.py              — Abstract repository interface
  sync.py                    — APS DM API fetcher, dry-run mode, APScheduler
  ror_client.py              — ROR API client + institution type colour map
  templates_env.py           — Shared Jinja2 environment (filters, globals)
  backends/
    sqlite_backend.py        — SQLiteESAFRepository (WAL mode, schema migrations)
  routers/
    admin_router.py          — Login/logout, admin user CRUD, audit log view
    upload_router.py         — Master file preview + apply (CSV/XLSX)
    public_api.py            — Unauthenticated JSON API (users + ESAFs)
    esafs.py                 — ESAF list, detail, inline edit
    users_router.py          — User list and detail pages
    institutions.py          — Institution list, ROR lookup, edit
    gups.py                  — GUP list and detail
    sync_router.py           — Sync trigger, preview, status
    stats.py                 — Statistics page and API
    fields.py                — Custom field definition management
    pi_groups_router.py      — PI group management
    beamline_scientists_router.py — Beamline scientist roster
    overrides.py             — Domain override rules
  templates/
    base.html                — Bootstrap 5 shell + HTMX + admin nav
    esafs.html / esaf_detail.html
    institutions.html
    upload.html
    admin.html / admin_login.html
    sync.html
    partials/                — HTMX swap targets
  scripts/                   — (reserved for startup scripts)
static/                      — Minimal CSS overrides
deploy/
  aps-esaf-fetcher.service   — systemd unit
  install.sh                 — one-shot install script
  procserv-start.sh          — procServ alternative (no root needed)
```

---

## Database schema (key tables)

| Table | Purpose |
|---|---|
| `esafs` | One row per ESAF; user-editable fields (`notes`, `technique`, `local_id`, `gup_id`, …) never overwritten |
| `users` | One row per user badge; `gender`, `employment_level` added by CSV import |
| `esaf_users` | ESAF ↔ user links; stores `role` (PI / User) and `user_type` (ON-SITE / OFF-SITE) |
| `funding_sources` | One row per (esaf_id, source) |
| `institution_ror` | Institution names with ROR metadata + `manual_types`, `imported_type`, `country`, `state` |
| `gups` | GUP records from the DM API |
| `beamline_scientists` | Roster of beamline staff |
| `admin_users` | Hashed admin credentials |
| `audit_log` | Every write action with user, action, table, timestamp |
| `field_definitions` | Custom field schemas |
| `pi_groups` | Named PI groups for ESAF organisation |

---

## Production deployment (systemd)

```bash
# On the server — sudo required for systemd steps
git clone https://github.com/nayanbera/aps-esaf-fetcher.git
cd aps-esaf-fetcher

sudo bash deploy/install.sh chem_epics /home/chem_epics/anaconda3

# Fill in APS DM credentials
sudo vi /etc/aps-esaf-fetcher/secrets.env

sudo systemctl start aps-esaf-fetcher
sudo journalctl -fu aps-esaf-fetcher
```

### procServ alternative (no root for the process)

```bash
bash deploy/procserv-start.sh
```

### Updating the service

```bash
git pull
sudo systemctl restart aps-esaf-fetcher
```

The SQLite migration runs automatically on startup — no manual schema changes needed.

---

## DM library installation

The `dm` package is provided by APS via the `aps-anl-tag` conda channel:

```bash
conda install aps-anl-tag::aps-dm-api
```

The install script handles this automatically.
