-- Example plugin schema. Idempotent — re-running this file must be a no-op.
-- Only ever touch tables prefixed with your plugin name: `_fd.example_*`.
-- See docs/PLUGIN_GUIDE.md §6, §7.

CREATE TABLE IF NOT EXISTS _fd.example_runs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    uuid NOT NULL REFERENCES auth.users(id),
    label       text NOT NULL,
    params      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS example_runs_owner_idx
    ON _fd.example_runs (owner_id);
