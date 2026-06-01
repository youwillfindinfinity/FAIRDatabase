"""Per-request plugin identity. See ``docs/PLUGIN_GUIDE.md`` §3.

The loader attaches a ``before_request`` hook to every plugin blueprint that
calls ``set_current_plugin(<name>)``. ``kernel.storage`` reads this via
``current_plugin()`` to scope bucket access to the calling plugin.

Stored on Flask's request-scoped ``g`` (not a contextvar) so it auto-clears
between requests and stays isolated across threads / async workers without
extra plumbing.
"""
from flask import g, has_request_context

__all__ = ["set_current_plugin", "current_plugin"]


def set_current_plugin(name):
    """Bind ``name`` as the plugin owning the current request. No-op outside
    a request context (e.g. boot-time SQL apply)."""
    if has_request_context():
        g._current_plugin = name


def current_plugin():
    """Return the plugin name bound to the current request, or ``None``."""
    if has_request_context():
        return getattr(g, "_current_plugin", None)
    return None
