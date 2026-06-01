"""Horizontal federated-learning plugin manifest. See docs/PLUGIN_GUIDE.md §5.

DP-FedProx/FedAvg federated learning: task creation, encrypted gradient
submission, in-process simulation, and DP epsilon accounting. Migrated from
src/federated/ (migration plan Phase 5).

Mounted at url_prefix="/fl" — the stable API contract. The dashboard UI is at
/fl/ui (was /federated/ui before the migration).

torch is an OPTIONAL dependency: only POST /fl/tasks/<id>/simulate needs it,
and it is imported lazily inside that handler. The task-CRUD surface loads
fine without torch installed.
"""
from kernel.plugin import Plugin

from .routes import routes

PLUGIN = Plugin(
    name="horizontal_fl",
    version="0.1.0",
    url_prefix="/fl",
    blueprint=routes,

    sql_migrations=["sql/001_schema.sql"],

    # Legacy prefix predating the plugin migration — the FL tables have been
    # named ``_fd.fl_*`` since before this plugin existed. Documented here so
    # the loader's CREATE/ALTER TABLE prefix guard accepts them.
    table_prefix="fl_",

    # Reads/UI open to any authenticated user; task mutations are admin/curator
    # (enforced per-route). No row-level dataset reads, so visualizer is fine.
    roles_required=("admin", "curator", "accessor", "visualizer"),

    templates_dir="templates",
    # ``icon`` is a FontAwesome class suffix (rendered as ``fa-<icon>``).
    nav={"label": "Federated Learning", "icon": "arrows-split-up-and-left"},
)
