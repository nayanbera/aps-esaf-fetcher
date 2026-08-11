import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DM_USERNAME: str = os.getenv("DM_USERNAME", "")
DM_PASSWORD: str = os.getenv("DM_PASSWORD", "")
DM_URL: str = os.getenv("DM_URL", "https://catdtn03.aps.anl.gov:11337")
STATION_ID: str = os.getenv("STATION_ID", "CHMCARS")

# Pipe-separated list of beamline name strings e.g. "15-ID-C,D|15-ID-E"
BEAMLINE_NAMES: list[str] = [
    b.strip() for b in os.getenv("BEAMLINE_NAMES", "15-ID-C,D").split("|") if b.strip()
]

def _default_years() -> list[str]:
    current = datetime.now().year
    return [str(current - 1), str(current)]

def _parse_years() -> list[str]:
    raw = os.getenv("SYNC_YEARS", "").strip()
    if not raw:
        return _default_years()
    return [y.strip() for y in raw.split(",") if y.strip()]

SYNC_YEARS: list[str] = _parse_years()
SYNC_INTERVAL_HOURS: int = int(os.getenv("SYNC_INTERVAL_HOURS", "24"))

_default_db = str(Path.home() / ".aps-esaf-fetcher" / "esaf.db")
DB_PATH: str = os.getenv("DB_PATH", _default_db)

# MongoDB — set MONGODB_URI to switch the backend; leave unset to use SQLite
MONGODB_URI: str = os.getenv("MONGODB_URI", "")
MONGODB_DB: str  = os.getenv("MONGODB_DB", "aps_esaf")

HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8088"))
