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


_env.globals["replace_param"] = _replace_param


class _Templates:
    """Drop-in replacement for Starlette's Jinja2Templates."""

    def TemplateResponse(
        self, name: str, context: dict, status_code: int = 200
    ) -> HTMLResponse:
        content = _env.get_template(name).render(**context)
        return HTMLResponse(content=content, status_code=status_code)


templates = _Templates()
