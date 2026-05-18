"""Main application of the Flask API. Registers all blueprints and then
starts the server."""

import os

import psycopg2
from flask import Flask, json, g, url_for, redirect, flash
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
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
from src.federated.routes import fl_routes
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


def _apply_schema(app):
    """Idempotently apply the SQL schema files at boot.

    Every file is written with ``CREATE ... IF NOT EXISTS`` / ``ADD COLUMN
    IF NOT EXISTS`` so re-running is safe. ``migrate_schema.sql`` both creates
    the ``_fd`` base objects AND has tail ALTERs that depend on the pbpk/fl
    tables, so it is applied once before and once after those — the second
    pass is a no-op except for the dependent ALTERs.

    Each file runs in its own transaction; a failure is logged and skipped so
    one bad/optional file cannot block Flask boot (same philosophy as
    ``_bootstrap_pbpk_bucket``). ``pbpk_storage_policies.sql`` is intentionally
    excluded — it targets Supabase Storage and is applied out of band.
    """
    base = os.path.dirname(os.path.abspath(__file__))
    order = [
        "migrate_schema.sql",
        "rbac_schema.sql",
        "pbpk_schema.sql",
        "fl_schema.sql",
        "demo_schema.sql",
        "migrate_schema.sql",  # second pass: tail ALTERs need pbpk/fl tables
    ]
    try:
        conn = psycopg2.connect(
            host=app.config["POSTGRES_HOST"],
            port=app.config["POSTGRES_PORT"],
            user=app.config["POSTGRES_USER"],
            password=app.config["POSTGRES_SECRET"],
            database=app.config["POSTGRES_DB_NAME"],
        )
    except Exception as exc:
        app.logger.warning("Schema apply skipped (no DB connection): %s", exc)
        return
    try:
        for fname in order:
            path = os.path.join(base, fname)
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    sql_text = fh.read()
                with conn.cursor() as cur:
                    cur.execute(sql_text)
                conn.commit()
                app.logger.info("Applied schema file: %s", fname)
            except Exception as exc:
                conn.rollback()
                app.logger.warning("Schema file %s failed: %s", fname, exc)
    finally:
        conn.close()


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
    _base = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(_base, "../frontend/templates"),
        static_folder=os.path.join(_base, "../static"),
    )
    app.config.from_object(Config)
    # Trust one layer of reverse proxy so request.remote_addr (and thus the
    # rate limiter's per-client key) reflects the real client IP via
    # X-Forwarded-For instead of collapsing every caller to the proxy IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    if db_name is not None:
        app.config["POSTGRES_DB_NAME"] = db_name

    app.register_blueprint(main_routes, url_prefix="/")
    app.register_blueprint(auth_routes, url_prefix="/auth")
    app.register_blueprint(dashboard_routes, url_prefix="/dashboard")
    app.register_blueprint(data_routes, url_prefix="/data")
    app.register_blueprint(privacy_routes, url_prefix="/privacy")
    app.register_blueprint(visualization_routes, url_prefix="/visualization")
    app.register_blueprint(federated_routes, url_prefix="/federated")
    app.register_blueprint(fl_routes, url_prefix="/fl")
    app.register_blueprint(model_routes, url_prefix="/model")
    app.register_blueprint(admin_routes, url_prefix="/admin")
    app.register_blueprint(demo_routes, url_prefix="/api/demo")

    # Single CORS init — flask-cors must only be applied once per app, or it
    # registers multiple after_request handlers and emits duplicated /
    # conflicting Access-Control-Allow-Origin headers. Per-resource rules:
    #   /api/demo/*  → public portal origin, GET only, no credentials
    #   everything   → (development only) localhost:5000 with credentials
    portal_origin = app.config.get("PORTAL_ORIGIN", "http://localhost:3000")
    cors_resources = {
        r"/api/demo/*": {
            "origins": portal_origin,
            "methods": ["GET"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": False,
        }
    }
    if app.config["ENV"] == "development":
        cors_resources[r"/*"] = {
            "origins": "http://localhost:5000",
            "supports_credentials": True,
        }
    CORS(app, resources=cors_resources)

    if app.config["ENV"] != "testing":
        limiter.init_app(app)

    supabase_extension.init_app(app)

    if app.config.get("ENV") != "testing":
        _apply_schema(app)  # before _bootstrap_admin: it needs _fd.user_roles
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
