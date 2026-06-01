"""Routes for the example plugin. See docs/PLUGIN_GUIDE.md §6.

Every import is from ``kernel.*`` — never reach into ``src.*`` or a sibling
plugin (guide §3). Every mutation records an audit row (guide §7). Every
resource has a working delete route (right-to-erasure).
"""
from flask import Blueprint, g, jsonify, render_template, request

from kernel.audit import record
from kernel.auth import login_required
from kernel.errors import GenericExceptionHandler
from kernel.rbac import assert_owns

from .helpers import serialize_run

routes = Blueprint("example_routes", __name__)

_TABLE = "_fd.example_runs"


@routes.get("/")
@login_required()
def index():
    """Render the plugin's landing page (template auto-mounted by the loader)."""
    return render_template("example/index.html")


@routes.post("/runs")
@login_required("admin", "curator")
def create_run():
    body = request.get_json(force=True) or {}
    label = (body.get("label") or "").strip()
    if not label:
        raise GenericExceptionHandler("label required", status_code=400)

    with g.db.cursor() as cur:
        cur.execute(
            f"INSERT INTO {_TABLE} (owner_id, label, params) "
            "VALUES (%s, %s, %s) RETURNING id",
            (g.user, label, json_param(body.get("params"))),
        )
        run_id = cur.fetchone()[0]
        # Audit row joins the same transaction as the insert.
        record("example_runs", actor=g.user, action="create",
               before=None, after={"id": str(run_id), "label": label})
    g.db.commit()
    return jsonify({"id": str(run_id)}), 201


@routes.get("/runs/<uuid:run_id>")
@login_required()
def get_run(run_id):
    with g.db.cursor() as cur:
        assert_owns(cur, _TABLE, "id", str(run_id))
        cur.execute(
            f"SELECT id, label, params, created_at FROM {_TABLE} WHERE id = %s",
            (str(run_id),),
        )
        row = cur.fetchone()
    return jsonify(serialize_run(row))


@routes.get("/runs")
@login_required()
def list_runs():
    """List the caller's runs. Admins see all; everyone else sees their own."""
    with g.db.cursor() as cur:
        if g.role == "admin":
            cur.execute(
                f"SELECT id, label, params, created_at FROM {_TABLE} "
                "ORDER BY created_at DESC"
            )
        else:
            cur.execute(
                f"SELECT id, label, params, created_at FROM {_TABLE} "
                "WHERE owner_id = %s ORDER BY created_at DESC",
                (g.user,),
            )
        rows = cur.fetchall()
    return jsonify([serialize_run(r) for r in rows])


@routes.delete("/runs/<uuid:run_id>")
@login_required("admin", "curator")
def delete_run(run_id):
    """Right-to-erasure: remove the row (and any associated blob, if added)."""
    with g.db.cursor() as cur:
        assert_owns(cur, _TABLE, "id", str(run_id))
        cur.execute(
            f"SELECT id, label FROM {_TABLE} WHERE id = %s", (str(run_id),)
        )
        before = cur.fetchone()
        cur.execute(f"DELETE FROM {_TABLE} WHERE id = %s", (str(run_id),))
        record("example_runs", actor=g.user, action="delete",
               before={"id": str(before[0]), "label": before[1]}, after=None)
    g.db.commit()
    return jsonify({"deleted": str(run_id)})


def json_param(value):
    """psycopg2 adapts a dict to jsonb via Json; keep params a plain dict."""
    import json
    return json.dumps(value or {})
