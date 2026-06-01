"""Admin & dataset-grants console routes."""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    session,
    g,
    current_app,
)

from src.auth.decorators import login_required
from .form import GrantsHandler, RoleAssignHandler, UserListHandler


routes = Blueprint("admin_routes", __name__)


@routes.route("/users", methods=["GET"])
@login_required("admin")
def users():
    handler = UserListHandler().load()
    return render_template("admin/users.html", **handler.ctx)


@routes.route("/users/<user_id>/role", methods=["POST"])
@login_required("admin")
def assign_role(user_id):
    new_role = request.form.get("role", "")
    ok, msg = RoleAssignHandler(user_id, new_role).apply()
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("admin_routes.users"))


@routes.route("/datasets/<int:dataset_id>/grants", methods=["GET"])
@login_required("admin", "curator")
def grants(dataset_id):
    handler = GrantsHandler(dataset_id).load()
    if not handler.ctx["allowed"]:
        return render_template("admin/grants.html", **handler.ctx), 403
    return render_template("admin/grants.html", **handler.ctx)


@routes.route("/datasets/<int:dataset_id>/grants", methods=["POST"])
@login_required("admin", "curator")
def grant_user(dataset_id):
    target = request.form.get("user_id", "")
    ok, msg = GrantsHandler(dataset_id).grant(target)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("admin_routes.grants", dataset_id=dataset_id))


@routes.route(
    "/datasets/<int:dataset_id>/grants/<user_id>/revoke", methods=["POST"]
)
@login_required("admin", "curator")
def revoke_user(dataset_id, user_id):
    ok, msg = GrantsHandler(dataset_id).revoke(user_id)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("admin_routes.grants", dataset_id=dataset_id))


@routes.route("/fl", methods=["GET"])
@login_required("admin")
def fl_dashboard():
    """FL admin console: active tasks, epsilon budgets, audit summary."""
    tasks = []
    budgets = []
    try:
        with g.db.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, algorithm, rounds_total, rounds_done,
                       dp_epsilon, simulation, created_at
                FROM _fd.fl_tasks ORDER BY created_at DESC
                """
            )
            cols = [d[0] for d in cur.description]
            tasks = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT b.dataset_id, m.table_name, b.total_budget, b.spent,
                       b.total_budget - b.spent AS remaining, b.last_updated
                FROM _fd.fl_epsilon_budget b
                LEFT JOIN _fd.metadata_tables m ON m.id = b.dataset_id
                ORDER BY b.last_updated DESC
                """
            )
            cols = [d[0] for d in cur.description]
            budgets = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        g.db.rollback()
        current_app.logger.exception("FL admin dashboard query failed")

    return render_template(
        "admin/fl.html",
        tasks=tasks,
        budgets=budgets,
        user_email=session.get("email"),
        current_path=request.path,
    )
