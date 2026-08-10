"""Shared Jinja2Templates instance used by all routers."""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from starlette.templating import Jinja2Templates

_templates_dir = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=True,
)
# Set cache=None directly — the meaning of cache_size=0 varies across Jinja2
# versions (disabled vs unlimited dict), so this is the only reliable way to
# prevent "unhashable type: dict" when Starlette passes env.globals as a cache key.
_env.cache = None

templates = Jinja2Templates(env=_env)
