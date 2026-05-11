"""Main application of the Flask API. Registers all blueprints and then
starts the server."""

import os

import psycopg2
from flask import Flask, json, g, url_for, redirect, flash
from flask_cors import CORS
from supabase import create_client

from config import Config, supabase_extension, limiter, get_db, teardown_db
from src.exceptions import GenericExceptionHandler
from src.auth.routes import routes as auth_routes
from src.dashboard.routes import routes as dashboard_routes
from src.data.routes import routes as data_routes
from src.privacy.routes import routes as privacy_routes
from src.main.routes import routes as main_routes
from src.visualization.routes import routes as visualization_routes
from src.federated.routes import routes as federated_routes
from src.model.routes import routes as model_routes
from src.admin.routes import routes as admin_routes
from src.demo.routes import routes as demo_routes

from config import load_settings


def _bootstrap_admin(app):
    """Promote the user identified by ADMIN_EMAIL to the 'admin' role.

    Idempotent and best-effort: silently no-op if the env var is missing, the
    Supabase service role key is unavailable, or the user has not yet
    registered. Re-runs on every boot so that newly registering admins are
    promoted as soon as their account exists.
    """
    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if not admin_email:
        return

    url = app.config.get("SUPABASE_URL")
    service_key = app.config.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_key:
        return

    try:
        from src.admin.form import list_supabase_users

        client = create_client(url, service_key)
        users = list_supabase_users(client=client)
        user_id = next(
            (uid for uid, email in users if email.lower() == admin_email),
            None,
        )
        if not user_id:
            app.logger.info(
                "ADMIN_EMAIL=%s not yet registered; skipping admin promotion",
                admin_email,
            )
            return

        conn = psycopg2.connect(
            host=app.config["POSTGRES_HOST"],
            port=app.config["POSTGRES_PORT"],
            user=app.config["POSTGRES_USER"],
            password=app.config["POSTGRES_SECRET"],
            database=app.config["POSTGRES_DB_NAME"],
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO _fd.user_roles (user_id, role, assigned_by) "
                    "VALUES (%s, 'admin', %s) "
                    "ON CONFLICT (user_id) DO UPDATE "
                    "SET role = EXCLUDED.role, assigned_at = now() "
                    "WHERE _fd.user_roles.role <> 'admin'",
                    (user_id, user_id),
                )
                cur.execute(
                    "INSERT INTO _fd.role_audit "
                    "(user_id, old_role, new_role, changed_by) "
                    "SELECT %s, NULL, 'admin', %s "
                    "WHERE NOT EXISTS (SELECT 1 FROM _fd.role_audit "
                    "                  WHERE user_id = %s AND new_role = 'admin')",
                    (user_id, user_id, user_id),
                )
            conn.commit()
            app.logger.info("Promoted %s to admin", admin_email)
        finally:
            conn.close()
    except Exception as exc:
        app.logger.warning("Admin bootstrap failed: %s", exc)


def _bootstrap_pbpk_bucket(app):
    """Ensure the ``pbpk-artifacts`` Supabase Storage bucket exists.

    Runs once at app-factory time (not per-request). Idempotent: a 409 /
    "already exists" response from Supabase is treated as success. Any other
    failure is logged and swallowed so a transient Supabase outage does not
    crash the Flask boot — the artifact upload route will surface a clearer
    502 to the caller if the bucket is genuinely missing later.

    Storage RLS policies (``storage.objects``) are NOT applied here — see
    ``backend/pbpk_storage_policies.sql`` for the one-shot psql apply.
    """
    bucket_id = "pbpk-artifacts"
    file_size_limit = 200 * 1024 * 1024  # keep in sync with routes.ARTIFACT_MAX_BYTES

    url = app.config.get("SUPABASE_URL")
    service_key = app.config.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_key:
        app.logger.info("Supabase not configured; skipping PBPK bucket bootstrap")
        return

    try:
        client = create_client(url, service_key)
        try:
            client.storage.create_bucket(
                bucket_id,
                options={"public": False, "file_size_limit": file_size_limit},
            )
            app.logger.info("Created Supabase Storage bucket %r", bucket_id)
        except Exception as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "duplicate" in msg or "409" in msg:
                app.logger.info("Supabase bucket %r already exists; skipping", bucket_id)
                return
            raise
    except Exception as exc:
        app.logger.warning("PBPK bucket bootstrap failed: %s", exc)


def create_app(db_name=None):
    """Construct the core application of Flask. Holds an
    optional argument to override the databse URI, this is used
    for Pytest."""
    app = Flask(
        __name__,
        template_folder=os.path.abspath("../frontend/templates"),
        static_folder=os.path.abspath("../static"),
    )
    app.config.from_object(Config)
    if db_name is not None:
        app.config["POSTGRES_DB_NAME"] = db_name

    app.register_blueprint(main_routes, url_prefix="/")
    app.register_blueprint(auth_routes, url_prefix="/auth")
    app.register_blueprint(dashboard_routes, url_prefix="/dashboard")
    app.register_blueprint(data_routes, url_prefix="/data")
    app.register_blueprint(privacy_routes, url_prefix="/privacy")
    app.register_blueprint(visualization_routes, url_prefix="/visualization")
    app.register_blueprint(federated_routes, url_prefix="/federated")
    app.register_blueprint(model_routes, url_prefix="/model")
    app.register_blueprint(admin_routes, url_prefix="/admin")
    app.register_blueprint(demo_routes, url_prefix="/api/demo")

    if app.config["ENV"] == "development":
        CORS(app, origins="http://localhost:5000", supports_credentials=True)

    if app.config["ENV"] != "testing":
        limiter.init_app(app)

    supabase_extension.init_app(app)

    if app.config.get("ENV") != "testing":
        _bootstrap_admin(app)
        _bootstrap_pbpk_bucket(app)

    app.teardown_appcontext(teardown_db)

    @app.before_request
    def before_request():
        """Establish the database connection for the current request."""
        g.db = get_db()

    @app.context_processor
    def inject_role():
        role = getattr(g, "role", None)
        return {
            "current_role": role,
            "is_admin": role == "admin",
            "is_curator": role == "curator",
            "can_upload": role in ("admin", "curator"),
        }

    @app.errorhandler(GenericExceptionHandler)
    def handle_generic_exception(e):
        if hasattr(e, "redirect_to") and e.redirect_to:
            flash(e.message, "danger")
            return redirect(url_for(e.redirect_to))
        return json.jsonify(e.to_dict()), e.status_code

    return app


if __name__ == "__main__":
    app = create_app()
    load_settings(app)
    app.run(debug=True)
