# Example plugin (`_template`)

Copy-paste skeleton for a FAIRDatabase plugin. The plugin loader **skips** any
folder whose name starts with `_`, so this template never registers itself —
copying it to a real name is what activates it.

## What it does

Exposes a tiny CRUD API for "runs" stored in `_fd.example_runs`: create, get,
list, delete — plus a landing page. It demonstrates every contract a real
plugin must honour: `kernel.*`-only imports, ownership checks, audit on every
mutation, and a working delete path.

## Create a new plugin from this template

```bash
cp -r plugins/_template plugins/<your_plugin>
```

Then rename, in the copy:

| Place | Change |
|---|---|
| `plugin.py` | `name`, `url_prefix` (and uncomment optional fields as needed) |
| `sql/001_schema.sql` | `_fd.example_*` table + index names → `_fd.<your_plugin>_*` |
| `routes.py` | `_TABLE`, the `record(...)` resource string, blueprint name |
| `helpers.py` / `form.py` | any references to the example table / session keys |
| `templates/example/` | rename directory to `templates/<your_plugin>/`; fix `render_template` paths |
| `tests/` | table names, url prefix, `ALLOWED` matrix |

Drop the renamed folder under `plugins/`, restart — the loader discovers it,
applies the migration, mounts the blueprint.

## Layout

```
plugin.py            manifest (required) — the only file the loader looks for
routes.py            Blueprint + route handlers
form.py              session-backed handlers (delete if your plugin is a pure API)
helpers.py           pure helpers, no Flask globals
sql/001_schema.sql   idempotent migration, only touches _fd.<plugin>_*
templates/<name>/    Jinja templates, auto-mounted into the core loader
tests/               pytest, runs in the main suite
```

## Python dependencies

Drop a `requirements.txt` next to `plugin.py`. The file uses normal pip syntax
and is installed at image build time by the project `Dockerfile`. For venv
work do `./scripts/install-plugin-deps.sh` from the repo root after the usual
`pip install -r backend/requirements.txt`.

Two important rules:

1. The shared `backend/requirements.txt` is passed as a pip `--constraint`
   when installing your plugin's deps. So a plugin cannot upgrade or downgrade
   a version pinned by the core — declare the version range you need to be
   *compatible* with, not the one you'd prefer in isolation.
2. List the *import* module names (not pip distribution names) under
   `required_packages` in `plugin.py`. The loader uses
   `importlib.util.find_spec` at boot; any missing import → the plugin is
   skip-mounted with a warning, but the app starts. Lazy-imported optional
   deps (only one route uses them) should appear in `requirements.txt` but
   NOT in `required_packages`, otherwise the whole plugin disappears when the
   optional dep is missing.

Example mapping for the common gotchas:

| pip name        | import name |
|-----------------|-------------|
| `python-libsbml`| `libsbml`   |
| `Pillow`        | `PIL`       |
| `scikit-learn`  | `sklearn`   |

## Navigation

**Convention: one flat sidebar entry per plugin. Sub-pages live inside the
plugin, not in the global sidebar.**

Set `nav={"label": "...", "icon": "..."}` in `plugin.py`. The entry renders as
a single sidebar link to your landing page. `icon` is a FontAwesome class
suffix (rendered as `fa-<icon>`). The link target defaults to
`<url_prefix>/ui`; override with `"path": "..."` (joined onto `url_prefix`, or
absolute if it starts with `/`) if your landing route differs. Note the bare
`url_prefix` usually has no route of its own, so don't point the link there.

If your plugin has multiple top-level pages (e.g. a main UI plus several
catalogued sub-pages), render a tab strip *inside* the plugin's own templates
— do **not** declare them in `nav`. The reference implementation is
`backend/plugins/pbpk/templates/pbpk/_studies_tabs.html`: a Jinja partial
included at the top of every pbpk page, driven by a `plugin_studies` list
injected via a blueprint-scoped `context_processor` in `routes.py`, with the
active tab marked by a per-route `pbpk_active_tab` variable.

Why: the global sidebar lists features, not pages. A plugin-private dropdown
would clutter it as soon as any plugin has more than a couple of sub-pages,
and the active-state behaviour gets confusing across sibling plugins.

## Environment variables

None by default. To use one, declare it in `plugin.py`'s `required_env` and
read it via `kernel.env.get("YOUR_KEY")` — never `os.getenv`. Core secrets
(`SUPABASE_SERVICE_ROLE_KEY`, `POSTGRES_SECRET`, `SECRET_KEY`, `ADMIN_EMAIL`)
are refused.

## FAIR / GDPR notes

- `example_runs` carries `id`, `owner_id` (→ `auth.users`), `created_at`,
  `updated_at` — the required columns (guide §7).
- Every mutation calls `kernel.audit.record(...)` inside the same transaction.
- `DELETE /runs/<id>` provides right-to-erasure. If you add uploaded
  artifacts, the delete route must also remove the blob via
  `kernel.storage.delete_object`.
- If your plugin derives a dataset, store the privacy parameters (k, l, t,
  p29, DP ε) alongside the data, not in session.

See `docs/PLUGIN_GUIDE.md` for the full contract.
