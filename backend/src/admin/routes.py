"""Admin & dataset-grants console routes."""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
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
