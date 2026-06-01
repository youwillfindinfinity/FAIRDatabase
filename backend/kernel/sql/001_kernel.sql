-- Kernel-owned schema. Idempotent; applied by the plugin loader at boot
-- (FAIRDatabase migration plan Phase 2). Assumes the _fd schema already
-- exists (created by migrate_schema.sql / rbac_schema.sql).

-- Generic mutation audit log written by kernel.audit.record(...).
CREATE TABLE IF NOT EXISTS _fd.plugin_audit (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    resource     text        NOT NULL,
    actor        uuid,
    action       text        NOT NULL,
    before_state jsonb,
    after_state  jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS plugin_audit_resource_idx
    ON _fd.plugin_audit (resource, created_at DESC);
