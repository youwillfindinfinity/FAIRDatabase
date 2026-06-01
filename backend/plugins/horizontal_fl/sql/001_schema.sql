-- Horizontal FL plugin schema. Idempotent — applied by the plugin loader.
-- Only touches _fd.fl_* tables owned by this plugin. The DP epsilon-budget
-- ledger (_fd.fl_epsilon_budget) and metadata_tables.fl_eligible are NOT here
-- — they are kernel-owned (kernel/sql/002_dp_budget.sql), see migration plan.

-- FL task: one federated training job.
CREATE TABLE IF NOT EXISTS _fd.fl_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          TEXT NOT NULL DEFAULT 'pending',
    algorithm       TEXT NOT NULL DEFAULT 'fedprox',
    rounds_total    INT NOT NULL DEFAULT 10,
    rounds_done     INT NOT NULL DEFAULT 0,
    mu              FLOAT NOT NULL DEFAULT 0.01,
    dp_epsilon      FLOAT NOT NULL,
    dp_delta        FLOAT NOT NULL DEFAULT 1e-5,
    dp_noise_mult   FLOAT,
    dp_clip_norm    FLOAT NOT NULL DEFAULT 1.0,
    simulation      BOOLEAN NOT NULL DEFAULT FALSE,
    sim_alpha       FLOAT NOT NULL DEFAULT 0.5,
    sim_n_clients   INT NOT NULL DEFAULT 5,
    model_arch      JSONB NOT NULL DEFAULT '{}',
    dataset_id      UUID,
    created_by      UUID,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- One round per FL task.
CREATE TABLE IF NOT EXISTS _fd.fl_rounds (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id             UUID NOT NULL REFERENCES _fd.fl_tasks(id) ON DELETE CASCADE,
    round_n             INT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',
    client_count        INT NOT NULL DEFAULT 0,
    epsilon_spent       FLOAT,
    aggregated_weights  JSONB,
    loss                FLOAT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (task_id, round_n)
);

-- Clients registered for a task.
CREATE TABLE IF NOT EXISTS _fd.fl_clients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES _fd.fl_tasks(id) ON DELETE CASCADE,
    site_id         TEXT NOT NULL,
    dataset_id      UUID,
    registered_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (task_id, site_id)
);

-- One row per distinct client submission within a round. The UNIQUE
-- constraint binds each client to at most one gradient submission per round,
-- so a single caller cannot satisfy a round's client count alone.
CREATE TABLE IF NOT EXISTS _fd.fl_round_submissions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES _fd.fl_tasks(id) ON DELETE CASCADE,
    round_n         INT NOT NULL,
    client_key      TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (task_id, round_n, client_key)
);
