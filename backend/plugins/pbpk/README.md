# PBPK plugin

Lifetime PBPK (physiologically-based pharmacokinetic) simulation. Migrated from
`src/model/` in Phase 4 of the plugin migration (see
`docs/PLUGIN_MIGRATION_PLAN.md`).

## What it does

- **Parameter sets** — named, versioned input parameter collections
  (`_fd.pbpk_parameter_sets`).
- **Simulation runs** — executes a scenario against a parameter set via the
  `PBKFAIRModel` package, persisting status, summary, and timeseries
  (`_fd.pbpk_simulation_runs`).
- **Run artifacts** — binary outputs (jpg/png/mp4/vtk) attached to a run; bytes
  in the `pbpk-artifacts` Supabase bucket, catalog rows in
  `_fd.pbpk_run_artifacts`.

Mounted at `url_prefix=/model` (kept for frontend compatibility — the UI issues
hardcoded `/model/*` fetches).

## Dependencies

- `PBKFAIRModel` — the simulation engine, a package at the repository root.
  `helpers.py` adds the repo root to `sys.path` if it is not already
  importable.

## Environment variables

None.

## RBAC

- `admin` — all runs/artifacts.
- `curator` — creates and owns parameter sets, runs, artifacts.
- `accessor` — reads own runs/artifacts only (no cross-user grants in the PoC).
- `visualizer` — reaches only the open routes (`/ui`, `/run`, `/scenarios`,
  parameter-set catalog); never row-level run/artifact data.

Row-level ownership is enforced by `assert_can_read_run` / `assert_can_modify_run`
in `helpers.py` (load-bearing on the Flask path — see the RLS note below).

## Schema & storage

- `sql/001_schema.sql` — tables + RLS policies, applied by the plugin loader at
  boot. Idempotent.
- `sql/pbpk_storage_policies.sql` — `storage.objects` RLS for the
  `pbpk-artifacts` bucket. **NOT** auto-applied; apply out of band via the
  Supabase dashboard / admin SQL. Until then only the service-role backend can
  read/write the bucket, which is fine since the backend mediates every request
  and issues the signed URLs.
- The `pbpk-artifacts` bucket itself is declared in `plugin.py` and created by
  the loader's `bootstrap_plugin_buckets`.

RLS in `001_schema.sql` is defense-in-depth: the Flask app connects as a
Postgres superuser and bypasses RLS, so the handler-level checks in `helpers.py`
are load-bearing on the web path.

## Dependencies

Plugin-specific Python deps live in `requirements.txt` next to this README
(`scipy`, `python-libsbml`). They are installed at image build time by the
project `Dockerfile`; for venv development run
`./scripts/install-plugin-deps.sh` from the repo root after the standard
`pip install -r backend/requirements.txt`. The shared core requirements file
is passed to pip as a `--constraint` so plugin installs cannot drift shared
versions (numpy, pandas, supabase, ...).

The manifest declares `required_packages=["scipy", "libsbml"]` (import names,
not pip names — `python-libsbml` imports as `libsbml`). The loader uses
`importlib.util.find_spec` at boot and skip-mounts the plugin with a warning
if any are missing, so the rest of the app still starts.

## Bundled FAIR study models (`studies/`)

In addition to the lifetime simulation surface above, the plugin ships four
canonical PBPK study models packaged as a read-only catalog under
`/model/studies/<slug>/`:

| Slug      | Source                              | Scenarios | Compounds |
|-----------|-------------------------------------|-----------|-----------|
| `ratier`  | Ratier 2024 (lifetime PFAS)         | yes       | no        |
| `rovira`  | Rovira 2019 (PFAS)                  | no        | yes       |
| `verner`  | Ouidir 2025 / Verner (PFAS)         | no        | yes       |
| `generic` | Generic PFAS PBPK                   | yes       | yes       |

Each study lives in `studies/<slug>/` as `runner.py` + its SBML XML +
`parameters.csv`. The registry in `studies/__init__.py` maps slug → module and
loads the runner **lazily** — `libsbml`/`scipy` are only imported the first
time a study endpoint is hit, so plugin discovery and the rest of pbpk keep
working without them.

Endpoints (mounted by `study_routes.register(routes)` in `routes.py`):

- `GET  /model/studies` — list available studies.
- `GET  /model/studies/<slug>/ui` — render the study's interactive page.
- `POST /model/studies/<slug>/run` — execute one scenario; returns timeseries
  + summary JSON. Missing optional deps → `503`.
- `GET  /model/studies/<slug>/scenarios` — scenario metadata (empty for
  compound-only studies).
- `GET  /model/studies/<slug>/compounds` — compound metadata (empty for
  scenario-only studies).

Templates live under `templates/pbpk/studies/<slug>.html` and extend
`dashboard/layout.html`. Every pbpk page (lifetime + each study) includes
`templates/pbpk/_studies_tabs.html` near the top — that partial is the
in-plugin tab strip the convention asks for (see `_template/README.md`). It
is driven by `plugin_studies` (injected via a blueprint-scoped
`context_processor` in `routes.py`) and `pbpk_active_tab` (set per-route).
Adding a new study = drop a subpackage in `studies/<new>/`, add a row to
`STUDIES`, add the template, and include the partial.

Sourced from PR #17 (the `PBKFAIR/` tree); the original src-blueprint layout
was refolded into this plugin contract.

## Tests

`tests/` — RBAC, parameter-set, run, artifact, and stress coverage. Picked up by
the project pytest (`testpaths = tests plugins`). `conftest.py` imports the
shared app/auth fixtures from the project `tests/conftest.py`.

## FAIR / GDPR notes

- Every resource table carries `id`, `owner_id`, `created_at`.
- `DELETE /model/artifacts/<id>` provides right-to-erasure (blob + catalog row).
- **Known gap vs guide §7:** mutations do not yet call `kernel.audit.record`.
  See the migration plan Phase 4 follow-up.
