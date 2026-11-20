# aps-esaf-fetcher

A self-contained web service that fetches Experiment Safety Assessment Form (ESAF) data
from the APS Data Management API, stores it in a local database, and exposes a
browsable web UI and a REST API for querying by downstream apps such as EasyBluesky.

Built with **FastAPI + Jinja2 + HTMX + Bootstrap 5**. No frontend build step.
Supports **SQLite** (default, zero-config) and **MongoDB** (set `MONGODB_URI` to switch).

---

## Features

- **Sync** — Periodic auto-sync from the APS DM API (configurable interval); manual
  trigger + dry-run preview before committing; sync year range 1998 → present
- **Browse** — Filter ESAFs by year, beamline, status, or free-text; full detail view
  with users, funding sources, institution types, GUP linkage, and DOI
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
- **Production-ready** — systemd unit + procServ launcher; SQLite WAL-mode or MongoDB;
  audit log

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
| `ESAF_SYSTEM_URL` | APS ESAF start page | Login page of the APS ESAF system, used when an ESAF has no direct link |
| `ESAF_URL` | `<ESAF_SYSTEM_URL>?i_attrib={esaf_id}` | Link opened from the ESAF table and detail page (asks for the APS login, then opens the ESAF); `{esaf_id}` is replaced. Empty = no direct links |
| `SYNC_YEARS` | current + previous year | Comma-separated years to sync (1998 – present supported) |
| `SYNC_INTERVAL_HOURS` | `24` | Auto-sync interval (0 = disabled) |
| `DB_PATH` | `~/.aps-esaf-fetcher/esaf.db` | SQLite database path (ignored when MongoDB is used) |
| `MONGODB_URI` | — | MongoDB connection URI; if set, MongoDB is used instead of SQLite |
| `MONGODB_ESAF_DB` | `aps_esaf` | MongoDB database name (only used when `MONGODB_URI` is set) |
| `HOST` | `0.0.0.0` | Bind host |
| `PORT` | `8088` | Bind port |
| `APP_SECRET_KEY` | auto-generated | Session secret (set explicitly in production) |

### Backend selection

The backend is chosen automatically at startup:

- **SQLite** (default) — no extra config needed; database file created at `DB_PATH`.
  Schema migrations run automatically on every startup.
- **MongoDB** — set `MONGODB_URI` to any valid MongoDB connection string
  (local: `mongodb://localhost:27017`, Atlas: `mongodb+srv://...`).
  Indexes are created on first startup.

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

The header row may sit below title rows (as in the APS user-report export); footer rows
such as "Total uniques users count" are ignored. On MongoDB, users are embedded in each
ESAF, so user fields are compared and written per ESAF, and an ESAF that already has a PI
(from the APS sync) keeps it.

Clicking **Preview Changes** shows a diff before committing. Click **Apply** to write.

**Duplicates between the master file and the APS sync.** The master file's *Experiment Id* is
numbered differently from APS ESAF numbers, so the same visit can exist twice (a synced ESAF and an
`ESAF <id> (imported)` stub). The import now attaches an experiment to a real ESAF when all of its
users are on it and the start dates are within 7 days (nearest wins), fills only that ESAF's blank
fields, and remembers the experiment id so a re-import never recreates the stub. For stubs created
earlier: `python check_duplicate_esafs.py` reports likely duplicates, and
`python merge_imported_duplicates.py` (dry run; `--apply` after a backup) merges them; add `--ties`
to also merge stubs whose nearest real ESAFs are tied (twin ESAFs of one visit). Blank career
stages that sit between two identical known stages of the same person can be filled with
`python backfill_career_stage.py` (dry run; `--apply` after a backup).

**Statistics charts** (Statistics page, same filters as the tables): Approved ESAFs per year (bars), unique users per
career stage and ESAFs per funding agency (pies), and unique users per US state and per country (maps). Users are the
unique users (badge + institution); their country and state are the ones stored on the user (ISO country codes or names
are both understood). Users without a recognisable country or state are not drawn; the number left out is printed
under the map. The charts load Plotly from a CDN, so the browser needs internet access.
The **Calendar years / Fiscal years (Oct–Sep)** switch at the top chooses what a year means for the per-year chart and the year filters; both are worked out from each ESAF's start date (FY2026 = Oct 2025 – Sep 2026), so the stored `year` field is not used.
Each chart has a **PNG** button that saves it as an image, and a **How the numbers are obtained** card (also on the Excel Summary sheet) explains how every number is counted.

**Download all statistics (Excel)** on the same page gives every table as its own sheet (summary, ESAFs per year, career stage,
funding, funding detail, users per US state / country, institutions, top users, beamlines, ESAF status), for the filters applied.
The bar and pie charts are native Excel charts on their sheets; the two maps are not (Excel cannot be written with map charts), so
those sheets hold the tables only.

**Publication awards.** A facility award is recognised by its number, however the publisher wrote it (`CHE-2335833`, `NSF/CHE-2335833`, `NSF/CHE- 2335833`, a bare `2335833`), so it lands in *Facility ack.* instead of *NSF awards*. **Re-check awards** on the Publications page moves facility awards out of the NSF / other award columns of publications that were saved before.

**Journal impact factor.** The Publications page has an *Impact factor* column. The Clarivate JIF is licensed data, so the value is OpenAlex's *2-year mean citedness* of the journal (the same calculation on OpenAlex's citation data; it is kept current and can differ from the official JIF). A journal is looked up when its first publication is added, and **Update impact factors** refreshes all of them. Theses are skipped and a journal OpenAlex does not know by its exact name shows a dash; a value with `source: manual` in the `journal_metrics` records is never overwritten.

**Linking ESAFs to GUPs.** An ESAF gets its GUP from its own PDF, from a sibling ESAF (same title and PI), or by matching: an unlinked ESAF whose PI and title equal a GUP's (a title that starts the same also counts) is linked to it, which also brings funding and technique. This runs when a GUP is imported, after each sync and with **Sync funding & technique from GUPs**. `python link_esafs_to_gups.py` (dry run; `--apply`, and `--likely` for ESAFs matched only by PI and run cycle) lists what would be linked; ESAFs that fit several GUPs are left alone.

**GUP instruments and ESAF technique.** The Experiment Time Request table of each GUP PDF is stored on the GUP (ETR number, run cycle,
resource, instrument, requested technique, shifts) and shown on the ESAF page in an *Instrument* card. The ESAF's own technique is set from
the 15-ID instrument (`app/instruments.py`: 15-ID-D Crystallography = Xtal, 15-ID-C Liquid interface = Surf, 15-ID-D Anomalous Small Angle
X-ray Scattering = ASWAXS): the ETR rows of the ESAF's run cycle count first, otherwise the GUP's 15-ID instrument. It is only set where the ESAF
has no technique or where this rule set it before; a technique chosen by hand is kept, and the card offers **Use <technique>** to replace it.
It runs after a GUP or ESAF PDF import and with **Sync funding & technique from GUPs** on the ESAFs page. GUPs that request two different 15-ID
instruments in the same cycle are left alone. GUPs imported before this feature need their PDF imported again to get their instruments.
The GUP's own technique (GUPs page) follows its instrument the same way (the proposal's run cycle first) and keeps what was set by hand; a GUP re-import keeps a GUP's technique. The GUP's Beamlines column is the Resource column of the same table.

**Funding sources** come from the GUP PDFs (pushed to linked ESAFs), ESAF PDFs and the master file; the APS sync has none,
so it leaves an ESAF's funding as it is. Earlier versions emptied it on every sync: `python restore_funding.py` (dry run;
`--apply` after a backup) refills ESAFs that now have none from their linked GUP and never changes ESAFs that have funding.
The same refill is in the app: **Sync from GUP** on an ESAF's Funding card copies its GUP's funding onto that ESAF, and
**Sync funding from GUPs** on the ESAFs page links sibling ESAFs to their GUP and fills every ESAF that has no funding.

### C — User list (career stage only)

A sheet with `Last Name`, `First Name`, optional `E-mail` and `Institutional Role`
(e.g. sheet `2026-3` of the ChemMatCARS user list). Use **Update career stage from a user
list** on `/upload`, choose the workbook, tick the sheets to import (each has an "applies from"
date, default the start of the run cycle: `2026-3` = 2026-09-01), preview (old → new per user,
and any people the ticked sheets disagree about), then apply. Sheets are applied in workbook
order, so a later sheet overrides an earlier one where their periods overlap.
Users are matched by e-mail, then name. Only that unique user's ESAFs from the date on get the
new career stage; earlier ESAFs keep theirs. People not in the database are skipped.

**Unique users.** A unique user is a *badge at one institution*: the same badge under another
institution is a separate user (Users and Statistics pages, SQLite and MongoDB alike). Institution
names are compared ignoring case, accents, punctuation and words like "the/of/at"; ESAFs without an
institution count toward the badge's main institution. Affiliation and career stage are stored
per ESAF (MongoDB: inside each ESAF's user entry; SQLite: `esaf_users.institution` / `employment_level`),
so a user's progression stays visible in the expanded Users row. Re-import the master file to fill
per-ESAF values for older ESAFs on an existing SQLite database.

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

Each ESAF record includes the **DOI** field as returned by the DM API. DOIs are
updated on every sync if the DM API provides a new or changed value.

---

## Migrating from SQLite to MongoDB

A one-shot migration script transfers all data from an existing SQLite database
into a MongoDB database. Run it **before** switching `MONGODB_URI` in the service config.

```bash
# Dry run — counts rows, writes nothing
python migrate_sqlite_to_mongo.py --dry-run

# Full migration (default SQLite path: ~/.aps-esaf-fetcher/esaf.db)
export MONGODB_URI="mongodb://localhost:27017"
export MONGODB_ESAF_DB="aps_esaf"   # optional, this is the default
python migrate_sqlite_to_mongo.py

# Custom SQLite path
python migrate_sqlite_to_mongo.py --db /path/to/esaf.db
```

**What is migrated:** ESAFs (with embedded users + funding), GUPs, PI Groups,
Institution ROR records, Beamline Scientists, Custom Field Definitions, Domain
Overrides, Admin Users (password hashes preserved), Audit Log, and Sync Log.

Upserts are idempotent for ESAFs and GUPs — safe to re-run. Audit log entries are
appended, so run the script only once to avoid duplicates.

After the migration completes, add `MONGODB_URI` (and optionally `MONGODB_ESAF_DB`)
to your secrets file and restart the service.

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
  "doi": "10.xxxxx/yyyyy",
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

# Full detail for one ESAF (includes users with institution_type and DOI)
esaf = requests.get(f"{BASE}/api/esafs/12345").json()
print(esaf["doi"])

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
  repository.py              — Abstract repository interface + backend factory
  sync.py                    — APS DM API fetcher, dry-run mode, APScheduler
  ror_client.py              — ROR API client + institution type colour map
  osti.py                    — OSTI Award DOI Service + ORCID lookup for user enrichment
  institution.py             — Institution enrichment helpers
  esaf_pdf_parser.py         — Extract ESAF metadata from PDF files
  gup_pdf_parser.py          — Extract GUP metadata from PDF files
  templates_env.py           — Shared Jinja2 environment (filters, globals)
  backends/
    sqlite_backend.py        — SQLiteESAFRepository (WAL mode, auto schema migrations)
    mongo_backend.py         — MongoESAFRepository (pymongo; indexes created on init)
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
static/                      — Minimal CSS overrides
deploy/
  aps-esaf-fetcher.service   — systemd unit
  install.sh                 — one-shot install script
  procserv-start.sh          — procServ alternative (no root needed)
migrate_sqlite_to_mongo.py   — One-shot SQLite → MongoDB migration script
```

---

## Database schema (key tables / collections)

Both backends expose the same data model. In SQLite these are tables; in MongoDB,
each is a collection with the same fields as document keys.

| Table / Collection | Purpose |
|---|---|
| `esafs` | One row per ESAF; includes `doi` from the DM API; user-editable fields (`notes`, `technique`, `local_id`, `gup_id`, …) never overwritten by sync |
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
| `domain_overrides` | Email-domain → institution/country/state overrides |
| `sync_log` | History of sync runs |

---

## Production deployment (systemd)

```bash
# On the server — sudo required for systemd steps
git clone https://github.com/nayanbera/aps-esaf-fetcher.git
cd aps-esaf-fetcher

sudo bash deploy/install.sh chem_epics /home/chem_epics/anaconda3

# Fill in APS DM credentials (and optionally MONGODB_URI / MONGODB_ESAF_DB)
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

SQLite schema migrations run automatically on startup — no manual changes needed.
For MongoDB, indexes are (re-)created on every startup without side effects.

---

## DM library installation

The `dm` package is provided by APS via the `aps-anl-tag` conda channel:

```bash
conda install aps-anl-tag::aps-dm-api
```

The install script handles this automatically.
