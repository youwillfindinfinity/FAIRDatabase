"""Main application routes handling user landing and dashboard rendering based
   on authentication."""


from flask import Blueprint, redirect, render_template, request, session

routes = Blueprint("main_routes", __name__)


@routes.route("/documentation")
def documentation():
    return render_template("/documentation/documentation.html", current_path=request.path), 200


# ── Legacy FL redirects ───────────────────────────────────────────────────────
# The federated-learning module became the horizontal_fl plugin (mounted at
# /fl) in migration plan Phase 5. These keep old /federated/* bookmarks working
# and can be removed once no external links rely on them.

@routes.route("/federated/ui")
def legacy_federated_ui():
    return redirect("/fl/ui", code=301)


@routes.route("/federated/federated_learning/federated_learning")
def legacy_federated_redirect():
    return redirect("/fl/ui", code=301)


@routes.route("/")
def index():
    """
    Route to render the appropriate homepage based on user authentication status.
    ---
    tags:
      - main
    responses:
      200:
        description: Renders the dashboard page if the user is logged in, otherwise renders the login page.
      401:
        description: Error response if the user is not authenticated (handled by redirect to login page).
    """
    if "user" in session:
        return render_template("/dashboard/dashboard.html"), 200
    return render_template("/auth/login.html"), 200
