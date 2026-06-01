"""Plugin manifest. See docs/PLUGIN_GUIDE.md §5.

RENAME CHECKLIST when you copy this template (see README.md):
  * this file: `name`, `url_prefix`
  * routes.py / form.py / helpers.py: the `_fd.example_*` table names
  * sql/001_schema.sql: the table names
  * templates/example/: rename the subdirectory
  * tests/: the table names and url prefix
"""
from kernel.plugin import Plugin

from .routes import routes

PLUGIN = Plugin(
    # `name` must be alphanumeric/underscore. It prefixes your tables
    # (`_fd.<name>_*`) and buckets (`<name>-*`).
    name="example",
    version="0.1.0",
    url_prefix="/example",
    blueprint=routes,

    # Idempotent SQL, applied at boot. Paths are relative to this folder.
    sql_migrations=["sql/001_schema.sql"],

    # Default role scope. Routes still declare their own @login_required(...);
    # this documents the plugin's intended audience and is checked by review.
    roles_required=("admin", "curator"),

    # Jinja templates under this folder are mounted into the core loader.
    templates_dir="templates",

    # --- optional, uncomment as needed ----------------------------------------
    # storage_buckets=[{
    #     "id": "example-artifacts",          # MUST start with "<name>-"
    #     "public": False,
    #     "size_limit": 200 * 1024 * 1024,    # 200 MB
    #     "mime_whitelist": {"image/png", "application/octet-stream"},
    # }],
    # required_env=["EXAMPLE_API_KEY"],       # read via kernel.env.get(...)
    # nav={"label": "Example", "icon": "flask"},
)
