"""Shared Jinja2Templates instance used by all routers."""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from jinja2.utils import LRUCache
from starlette.templating import Jinja2Templates

_templates_dir = Path(__file__).parent / "templates"


class _SafeCache(LRUCache):
    """LRUCache that silently ignores unhashable cache keys.

    Starlette injects env.globals (a dict) into the Jinja2 cache key tuple,
    making it unhashable on certain Jinja2/Starlette version combinations.
    This wrapper catches the TypeError so templates are loaded fresh on a
    cache miss rather than crashing.
    """
    def get(self, key):
        try:
            return super().get(key)
        except TypeError:
            return None

    def __setitem__(self, key, value):
        try:
            super().__setitem__(key, value)
        except TypeError:
            pass


_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=True,
)
_env.cache = _SafeCache(400)

templates = Jinja2Templates(env=_env)
