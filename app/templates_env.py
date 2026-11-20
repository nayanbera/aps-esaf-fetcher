"""Shared Jinja2 template renderer.

Uses Jinja2's Environment directly instead of Starlette's Jinja2Templates to
avoid the unhashable-dict TypeError that arises when Starlette injects url_for
(a closure) into env.globals, which in some Starlette/Jinja2 version
combinations corrupts the LRU cache key tuple.
"""

from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader
from fastapi.responses import HTMLResponse

_templates_dir = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=True,
)
_env.globals["url_quote"] = quote

from . import config as _config
_env.globals["esaf_system_url"] = _config.ESAF_SYSTEM_URL


def _aps_url(esaf) -> str:
    """Login-and-open link for the ESAF in the APS ESAF system; '' for '(imported)' stubs (not APS ESAF numbers)."""
    from .esaf_matching import is_stub
    eid = str(esaf.get("esaf_id") or "")
    if not _config.ESAF_URL or not eid.isdigit() or is_stub(esaf):
        return ""
    return _config.ESAF_URL.replace("{esaf_id}", eid)


_env.filters["aps_url"] = _aps_url
_env.globals["db_backend"] = "MongoDB" if _config.MONGODB_URI else "SQLite"


def _replace_param(query_string, key: str, value) -> str:
    """Replace or add a query-string parameter, returning the new query string."""
    from urllib.parse import parse_qs, urlencode
    # Accept Starlette QueryParams or plain string
    if hasattr(query_string, "multi_items"):
        params: dict = {}
        for k, v in query_string.multi_items():
            params.setdefault(k, []).append(v)
    else:
        params = parse_qs(str(query_string), keep_blank_values=True)
    params[key] = [str(value)]
    return urlencode(params, doseq=True)


_env.filters["replace_param"] = _replace_param

def _run_cycle(esaf) -> str:
    """APS run cycle of an ESAF from its start date: 1 = Jan-Apr, 2 = May-Aug, 3 = Sep-Dec ('2026-3').
    Falls back to the year when the start date is missing."""
    from .esaf_matching import run_cycle
    return run_cycle(esaf.get("start_date")) or str(esaf.get("year") or "")


_env.filters["run_cycle"] = _run_cycle

from .display_tz import get_timezone_name as _tz_name, localtime as _localtime
_env.filters["localtime"] = _localtime
_env.globals["display_tz"] = _tz_name


class _Templates:
    """Drop-in replacement for Starlette's Jinja2Templates."""

    def TemplateResponse(
        self, name: str, context: dict, status_code: int = 200
    ) -> HTMLResponse:
        content = _env.get_template(name).render(**context)
        return HTMLResponse(content=content, status_code=status_code)


templates = _Templates()
