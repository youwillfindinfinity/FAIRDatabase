"""Allow-listed environment access for plugins. See ``docs/PLUGIN_GUIDE.md`` §3, §5.

Plugins must NOT call ``os.getenv`` or read ``.env`` directly. They read config
through ``kernel.env.get``, which refuses the core secrets a plugin must never
see. Per-plugin scoping — a plugin sees only the keys it declared in its
manifest ``required_env`` — is enforced by the plugin loader (migration plan
Phase 2); this module enforces the absolute core-secret denylist.
"""
import os

__all__ = ["get", "CORE_SECRETS", "is_core_secret"]

# Keys a plugin manifest may never request and kernel.env will never return.
# Mirrors PLUGIN_GUIDE.md §5.
CORE_SECRETS = frozenset(
    {
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SERVICE_KEY",
        "POSTGRES_PASSWORD",
        "SECRET_KEY",
        "ADMIN_EMAIL",
    }
)

_CORE_SECRETS_UPPER = frozenset(s.upper() for s in CORE_SECRETS)


def is_core_secret(key):
    """Return True if ``key`` is a core secret no plugin may read."""
    return key.strip().upper() in _CORE_SECRETS_UPPER


def get(key, default=None):
    """Return the environment value for ``key``.

    Raises ``PermissionError`` if ``key`` is a core secret (see ``CORE_SECRETS``).
    """
    if is_core_secret(key):
        raise PermissionError(
            f"{key} is a core secret; plugins cannot read it (PLUGIN_GUIDE.md §5)"
        )
    return os.getenv(key, default)
