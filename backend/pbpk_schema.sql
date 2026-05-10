-- backend/pbpk_schema.sql
-- Run after migrate_schema.sql AND rbac_schema.sql.
-- Idempotent: every statement uses IF NOT EXISTS / CREATE OR REPLACE / DROP-then-CREATE.
--
-- This file owns the PBPK module's persistence + RBAC. RLS policies here are
-- defense-in-depth: the Flask app currently connects as a superuser and
-- bypasses RLS, so handler-level checks in src/model/helpers.py are the
-- load-bearing layer on the web path. These policies protect non-superuser
-- callers (Supabase edge functions, direct psql, future API gateways).

-- ---------------------------------------------------------------------------
-- Core tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS _fd.pbpk_parameter_sets (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    model_id    TEXT NOT NULL DEFAULT 'lifetime_pbpk',
    params      JSONB NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS _fd.pbpk_simulation_runs (
    id              SERIAL PRIMARY KEY,
    param_set_id    INT REFERENCES _fd.pbpk_parameter_sets(id),
    scenario        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    error_message   TEXT,
    summary         JSONB,
    timeseries      JSONB,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- RBAC: add owner_id (nullable for backfill) and an index for policy lookups.
-- created_by stays as the human-readable email for audit; owner_id is the
-- uuid that policies and handler-level checks key on.
-- ---------------------------------------------------------------------------
ALTER TABLE _fd.pbpk_parameter_sets
    ADD COLUMN IF NOT EXISTS owner_id UUID;
ALTER TABLE _fd.pbpk_simulation_runs
    ADD COLUMN IF NOT EXISTS owner_id UUID;

CREATE INDEX IF NOT EXISTS pbpk_parameter_sets_owner_idx
    ON _fd.pbpk_parameter_sets(owner_id);
CREATE INDEX IF NOT EXISTS pbpk_simulation_runs_owner_idx
    ON _fd.pbpk_simulation_runs(owner_id);

-- Backfill owner_id for rows created before the column existed. Idempotent:
-- only touches rows where owner_id IS NULL and a matching auth.users row
-- exists for the recorded created_by email. Wrapped in DO block so the file
-- still parses on a fresh DB where auth.users does not yet exist (Supabase
-- provisions it asynchronously on first boot).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'auth' AND table_name = 'users') THEN
        UPDATE _fd.pbpk_simulation_runs r
           SET owner_id = u.id
          FROM auth.users u
         WHERE u.email = r.created_by AND r.owner_id IS NULL;
        UPDATE _fd.pbpk_parameter_sets p
           SET owner_id = u.id
          FROM auth.users u
         WHERE u.email = p.created_by AND p.owner_id IS NULL;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Artifacts: jpg / png / mp4 / vtk produced by a simulation run.
-- The bytes live in Supabase Storage (bucket "pbpk-artifacts"); this table is
-- the catalog row that ties each blob to a run + owner so RBAC applies.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS _fd.pbpk_run_artifacts (
    id            BIGSERIAL PRIMARY KEY,
    run_id        INT NOT NULL REFERENCES _fd.pbpk_simulation_runs(id) ON DELETE CASCADE,
    owner_id      UUID NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('image', 'video', 'mesh')),
    storage_path  TEXT NOT NULL UNIQUE,
    mime          TEXT NOT NULL,
    size_bytes    BIGINT NOT NULL CHECK (size_bytes > 0),
    original_name TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS pbpk_run_artifacts_run_idx
    ON _fd.pbpk_run_artifacts(run_id);
CREATE INDEX IF NOT EXISTS pbpk_run_artifacts_owner_idx
    ON _fd.pbpk_run_artifacts(owner_id);

-- ---------------------------------------------------------------------------
-- RLS: parameter_sets
-- Catalog (SELECT) visible to every authenticated user; mutations restricted
-- to admin or the owning curator.
-- ---------------------------------------------------------------------------
ALTER TABLE _fd.pbpk_parameter_sets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS pbpk_param_select ON _fd.pbpk_parameter_sets;
CREATE POLICY pbpk_param_select ON _fd.pbpk_parameter_sets FOR SELECT
    USING (auth.uid() IS NOT NULL);

DROP POLICY IF EXISTS pbpk_param_insert ON _fd.pbpk_parameter_sets;
CREATE POLICY pbpk_param_insert ON _fd.pbpk_parameter_sets FOR INSERT
    WITH CHECK (
        _fd.current_role() IN ('admin', 'curator')
        AND owner_id = auth.uid()
    );

DROP POLICY IF EXISTS pbpk_param_update ON _fd.pbpk_parameter_sets;
CREATE POLICY pbpk_param_update ON _fd.pbpk_parameter_sets FOR UPDATE
    USING (
        _fd.current_role() = 'admin'
        OR (_fd.current_role() = 'curator' AND owner_id = auth.uid())
    );

DROP POLICY IF EXISTS pbpk_param_delete ON _fd.pbpk_parameter_sets;
CREATE POLICY pbpk_param_delete ON _fd.pbpk_parameter_sets FOR DELETE
    USING (
        _fd.current_role() = 'admin'
        OR (_fd.current_role() = 'curator' AND owner_id = auth.uid())
    );

-- ---------------------------------------------------------------------------
-- RLS: simulation_runs
-- Admin sees all. Curator sees / mutates own runs. Accessor sees own runs
-- only (no cross-user grants in the PoC — share via dataset link later).
-- Visualizer is excluded from row-level reads; aggregate viz endpoints handle
-- that role separately.
-- ---------------------------------------------------------------------------
ALTER TABLE _fd.pbpk_simulation_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS pbpk_runs_select ON _fd.pbpk_simulation_runs;
CREATE POLICY pbpk_runs_select ON _fd.pbpk_simulation_runs FOR SELECT
    USING (
        _fd.current_role() = 'admin'
        OR (_fd.current_role() IN ('curator', 'accessor') AND owner_id = auth.uid())
    );

DROP POLICY IF EXISTS pbpk_runs_insert ON _fd.pbpk_simulation_runs;
CREATE POLICY pbpk_runs_insert ON _fd.pbpk_simulation_runs FOR INSERT
    WITH CHECK (
        _fd.current_role() IN ('admin', 'curator')
        AND owner_id = auth.uid()
    );

DROP POLICY IF EXISTS pbpk_runs_update ON _fd.pbpk_simulation_runs;
CREATE POLICY pbpk_runs_update ON _fd.pbpk_simulation_runs FOR UPDATE
    USING (
        _fd.current_role() = 'admin'
        OR (_fd.current_role() = 'curator' AND owner_id = auth.uid())
    );

DROP POLICY IF EXISTS pbpk_runs_delete ON _fd.pbpk_simulation_runs;
CREATE POLICY pbpk_runs_delete ON _fd.pbpk_simulation_runs FOR DELETE
    USING (
        _fd.current_role() = 'admin'
        OR (_fd.current_role() = 'curator' AND owner_id = auth.uid())
    );

-- ---------------------------------------------------------------------------
-- RLS: run_artifacts
-- Strictly admin or owner. Bytes are gated separately by storage.objects
-- policies on the pbpk-artifacts bucket (configured in Supabase, not here).
-- ---------------------------------------------------------------------------
ALTER TABLE _fd.pbpk_run_artifacts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS pbpk_artifacts_select ON _fd.pbpk_run_artifacts;
CREATE POLICY pbpk_artifacts_select ON _fd.pbpk_run_artifacts FOR SELECT
    USING (
        _fd.current_role() = 'admin'
        OR owner_id = auth.uid()
    );

DROP POLICY IF EXISTS pbpk_artifacts_insert ON _fd.pbpk_run_artifacts;
CREATE POLICY pbpk_artifacts_insert ON _fd.pbpk_run_artifacts FOR INSERT
    WITH CHECK (
        _fd.current_role() IN ('admin', 'curator')
        AND owner_id = auth.uid()
        AND EXISTS (
            SELECT 1 FROM _fd.pbpk_simulation_runs r
            WHERE r.id = run_id AND (r.owner_id = auth.uid() OR _fd.current_role() = 'admin')
        )
    );

DROP POLICY IF EXISTS pbpk_artifacts_delete ON _fd.pbpk_run_artifacts;
CREATE POLICY pbpk_artifacts_delete ON _fd.pbpk_run_artifacts FOR DELETE
    USING (
        _fd.current_role() = 'admin'
        OR owner_id = auth.uid()
    );
