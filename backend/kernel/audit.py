"""Generic mutation audit log for plugins. See ``docs/PLUGIN_GUIDE.md`` §2, §7.

Every plugin mutation must call ``record(...)``. Rows land in
``_fd.plugin_audit`` (defined in ``kernel/sql/001_kernel.sql``, applied by the
plugin loader at boot — migration plan Phase 2).
"""
import json

from flask import g

__all__ = ["record"]


def record(resource, actor, action, before=None, after=None):
    """Append one row to ``_fd.plugin_audit``.

    resource     : str  — logical resource name, e.g. ``"myplugin_runs"``
    actor        : uuid — who performed the action (usually ``g.user``)
    action       : str  — ``"create"`` | ``"update"`` | ``"delete"`` | ...
    before/after : JSON-serialisable snapshots, or ``None``

    Runs on ``g.db`` in the caller's transaction: call it AFTER the mutation
    statements and BEFORE ``g.db.commit()`` so the audit row commits
    atomically with the change it records.
    """
    with g.db.cursor() as cur:
        cur.execute(
            "INSERT INTO _fd.plugin_audit "
            "(resource, actor, action, before_state, after_state) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                resource,
                actor,
                action,
                json.dumps(before) if before is not None else None,
                json.dumps(after) if after is not None else None,
            ),
        )
