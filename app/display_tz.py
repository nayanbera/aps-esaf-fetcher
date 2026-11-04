"""Display time zone for the web UI.

Timestamps are stored in UTC; they are converted to the admin-selected zone
only when rendered (see the ``localtime`` Jinja filter).  The choice is kept
in ``PDF_DIR/app_settings.json`` and defaults to Chicago.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from . import config

log = logging.getLogger(__name__)

DEFAULT_TZ = "America/Chicago"

COMMON_TZS = [
    "America/Chicago", "America/New_York", "America/Denver", "America/Los_Angeles",
    "America/Anchorage", "Pacific/Honolulu", "America/Toronto", "America/Mexico_City",
    "Europe/London", "Europe/Paris", "Europe/Berlin", "Asia/Kolkata", "Asia/Shanghai",
    "Asia/Tokyo", "Australia/Sydney", "UTC",
]

_lock = threading.Lock()
_cache: dict = {"mtime": None, "name": DEFAULT_TZ}


def _path() -> Path:
    p = Path(config.PDF_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p / "app_settings.json"


def all_timezones() -> list[str]:
    return sorted(available_timezones())


def is_valid(name: str) -> bool:
    return name in available_timezones()


def get_timezone_name() -> str:
    """Current display zone (re-read when the settings file changes)."""
    try:
        mtime = _path().stat().st_mtime_ns
    except OSError:
        return DEFAULT_TZ
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                name = json.loads(_path().read_text()).get("timezone", DEFAULT_TZ)
            except (OSError, ValueError):
                name = DEFAULT_TZ
            _cache.update(mtime=mtime, name=name if is_valid(name) else DEFAULT_TZ)
        return _cache["name"]


def set_timezone_name(name: str) -> None:
    if not is_valid(name):
        raise ValueError(f"Unknown time zone: {name}")
    with _lock:
        path = _path()
        try:
            settings = json.loads(path.read_text())
        except (OSError, ValueError):
            settings = {}
        settings["timezone"] = name
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2))
        tmp.replace(path)
        _cache["mtime"] = None  # force re-read


@lru_cache(maxsize=None)
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def localtime(value, fmt: str = "%Y-%m-%d %H:%M:%S %Z"):
    """Jinja filter: convert a stored UTC timestamp to the display zone.

    Accepts ISO strings (with or without offset) and datetimes; naive values
    are taken as UTC.  Date-only strings and anything unparseable are returned
    unchanged.
    """
    if value in (None, ""):
        return "—"
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            s = str(value).strip()
            if len(s) <= 10:          # date only — no time to convert
                return s
            s = s.replace("Z", "+00:00")
            # Python 3.9's fromisoformat only accepts 3- or 6-digit fractions.
            s = re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), s, count=1)
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_zone(get_timezone_name())).strftime(fmt)
    except (ValueError, OSError):
        return value
