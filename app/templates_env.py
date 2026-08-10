"""Shared Jinja2Templates instance used by all routers."""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from starlette.templating import Jinja2Templates

_templates_dir = Path(__file__).parent / "templates"

# cache_size=0 disables the LRU cache that triggers "unhashable type: dict"
# on certain Starlette/Jinja2 version combinations.
_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=True,
    cache_size=0,
)

templates = Jinja2Templates(env=_env)
