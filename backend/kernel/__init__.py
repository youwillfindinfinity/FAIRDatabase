"""FAIRDatabase kernel — the stable API surface for plugins.

Plugins import **only** from ``kernel.*``. This package is a thin façade over
core internals; importing from anywhere else in the tree is unsupported for
plugin code. See ``docs/PLUGIN_GUIDE.md`` §2 for the full surface and
``docs/PLUGIN_MIGRATION_PLAN.md`` for how the façade was assembled.
"""
from . import (
    audit,
    auth,
    crypto,
    db,
    dp_budget,
    env,
    errors,
    handlers,
    privacy,
    rbac,
    storage,
)
from .plugin import Plugin

__all__ = [
    "audit",
    "auth",
    "crypto",
    "db",
    "dp_budget",
    "env",
    "errors",
    "handlers",
    "privacy",
    "rbac",
    "storage",
    "Plugin",
]
