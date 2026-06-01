"""The plugin manifest. See ``docs/PLUGIN_GUIDE.md`` §5.

Every plugin exposes a module-level ``PLUGIN = Plugin(...)`` in its
``plugin.py``. The plugin loader (migration plan Phase 2) discovers it,
validates it, applies SQL migrations, creates storage buckets, and mounts the
blueprint at ``url_prefix``.
"""
from dataclasses import dataclass, field
from typing import Optional

from kernel.env import is_core_secret

__all__ = ["Plugin"]


@dataclass
class Plugin:
    """Declarative description of a plugin. Anything not declared here is
    unavailable to the plugin at runtime."""

    name: str
    version: str
    url_prefix: str
    blueprint: object

    sql_migrations: list = field(default_factory=list)
    storage_buckets: list = field(default_factory=list)
    required_env: list = field(default_factory=list)
    # Importable module names (NOT pip distribution names) whose absence makes
    # the plugin non-functional. Loader skip-mounts the plugin if any are
    # missing. Truly optional deps (lazy-imported inside one route) should stay
    # out of this list. The actual install convention lives at
    # ``plugins/<name>/requirements.txt``; that file is pip-installed at image
    # build time and listed packages must resolve to importable modules below.
    required_packages: list = field(default_factory=list)
    roles_required: tuple = ()
    templates_dir: Optional[str] = None
    # Navigation entry rendered by the core layout: ``{"label": str,
    # "icon": str, "path": str}`` where ``icon`` is a FontAwesome suffix
    # (rendered as ``fa-<icon>``) and ``path`` is the landing page. ``path`` is
    # joined onto ``url_prefix`` (or absolute if it starts with ``/``); it
    # defaults to ``"ui"`` → ``<url_prefix>/ui``, the standard landing route.
    # The bare ``url_prefix`` itself usually has no route, so set ``path`` if
    # your landing page isn't ``/ui``.
    #
    # Convention (see ``backend/plugins/_template/README.md``): the global
    # sidebar lists **one** entry per plugin. Sub-pages live inside the plugin
    # and are reached from a tab strip or pill nav rendered at the top of the
    # plugin's own templates — NOT from this manifest. This keeps the sidebar
    # uncluttered as plugins grow.
    nav: Optional[dict] = None
    # Identifier prefix this plugin owns inside the ``_fd`` schema. Defaults to
    # ``"<name>_"`` (guide §3). Override only when the plugin has a stable
    # legacy prefix predating the manifest (e.g. ``horizontal_fl`` owns the
    # ``fl_`` namespace from its pre-plugin life). The loader enforces this
    # against every CREATE/ALTER TABLE in the plugin's SQL migrations.
    table_prefix: Optional[str] = None

    def __post_init__(self):
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError(
                f"plugin name must be alphanumeric/underscore: {self.name!r}"
            )
        if not self.url_prefix.startswith("/"):
            raise ValueError(
                f"url_prefix must start with '/': {self.url_prefix!r}"
            )
        if self.table_prefix is None:
            self.table_prefix = f"{self.name}_"
        if not self.table_prefix.endswith("_"):
            raise ValueError(
                f"table_prefix {self.table_prefix!r} must end with '_'"
            )

        # A plugin may only own buckets prefixed with "<name>-" (guide §3, §5).
        for bucket in self.storage_buckets:
            bid = bucket.get("id", "") if isinstance(bucket, dict) else ""
            if not bid.startswith(f"{self.name}-"):
                raise ValueError(
                    f"bucket id {bid!r} must start with {self.name + '-'!r}"
                )

        # Core refuses a manifest that asks for a core secret (guide §5).
        for key in self.required_env:
            if is_core_secret(key):
                raise ValueError(
                    f"required_env {key!r} is a core secret; "
                    "not allowed (PLUGIN_GUIDE.md §5)"
                )
