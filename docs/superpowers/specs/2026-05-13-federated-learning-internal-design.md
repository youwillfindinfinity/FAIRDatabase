# Federated Learning Internal Module — Design Spec
**Date:** 2026-05-13
**Status:** Approved for implementation

---

## 1. Objective

Replace the existing `/federated/` proxy (which forwarded to an absent external service on port 7070) with a fully internal, scientifically rigorous federated learning engine embedded in FAIRDatabase. The engine must be privacy-correct (valid DP guarantees), robust to non-IID biomedical data distributions, and integrated across the data, privacy, model, and admin modules.

Aligns with **FAIRification.md Section 10, Phase 2** (intra-institutional FL with DP).

---

## 2. Scientific Corrections to Naive Design

The following issues were identified in the initial design and are corrected here:

| Issue | Correction |
|---|---|
| Naive ε/rounds composition | **Rényi DP (RDP) accountant** for tight multi-round composition |
| Gaussian noise without clipping | **L2 gradient clipping** to bound sensitivity before noise |
| FedAvg on non-IID biomedical data | **FedProx** as default; SCAFFOLD as alternative |
| IID-only simulation | **Dirichlet (α) partitioning** for realistic non-IID simulation |
| Black-box MLP for PBPK | FL targets **PBPK parameter estimation** (mechanistic); separate tabular MLP for microbiome/generic datasets |
| Plaintext gradient storage | Gradient payloads **encrypted at rest**, purged after aggregation |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     FAIRDatabase FL Module                       │
│                                                                  │
│  API Layer                                                        │
│  /fl/tasks  /fl/tasks/{id}  /fl/tasks/{id}/rounds/{n}/gradients  │
│  /fl/tasks/{id}/model  /fl/tasks/{id}/export-params              │
│  /federated/ui  (legacy redirect kept)                           │
│                        │                                         │
│  ┌─────────────────────▼────────────────────────────────────┐   │
│  │                  FL Engine (engine.py)                    │   │
│  │                                                           │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │   │
│  │  │  FedProx /   │  │  Clip + DP   │  │  Simulation   │  │   │
│  │  │  FedAvg      │  │  Gaussian    │  │  (Dirichlet   │  │   │
│  │  │  Aggregation │  │  Noise       │  │   partition)  │  │   │
│  │  └──────────────┘  └──────────────┘  └───────────────┘  │   │
│  │                                                           │   │
│  │  ┌──────────────────────────────────────────────────────┐│   │
│  │  │  RDP Accountant (moments accountant, tight ε bounds) ││   │
│  │  └──────────────────────────────────────────────────────┘│   │
│  └───────────────────────────────────────────────────────────┘  │
│                        │                                         │
│  ┌─────────────────────▼───────────────────────────────────┐    │
│  │          PostgreSQL — _fd schema (new tables)            │    │
│  │   fl_tasks | fl_rounds | fl_clients | fl_epsilon_budget  │    │
│    (gradients encrypted at rest, purged after aggregation)  │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
        │               │                │               │
  Privacy module   Data module     Model module    Admin module
  (clip+noise in   (FL eligibility  (FL weights →  (/admin/fl:
  helpers.py,      flag after P29,  PBPK param      ε budget,
  RDP budget)      enroll datasets) sets export)    audit log)
```

---

## 4. Database Schema (`_fd` schema)

### 4.1 New tables

```sql
-- FL task: one training job
CREATE TABLE _fd.fl_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          TEXT NOT NULL DEFAULT 'pending',
                    -- pending | running | completed | failed
    algorithm       TEXT NOT NULL DEFAULT 'fedprox',
                    -- fedprox | fedavg | scaffold
    rounds_total    INT NOT NULL DEFAULT 10,
    rounds_done     INT NOT NULL DEFAULT 0,
    mu              FLOAT DEFAULT 0.01,    -- FedProx proximal term
    dp_epsilon      FLOAT NOT NULL,        -- total ε budget
    dp_delta        FLOAT NOT NULL DEFAULT 1e-5,
    dp_noise_mult   FLOAT,                 -- σ / C, computed by RDP accountant
    dp_clip_norm    FLOAT NOT NULL DEFAULT 1.0,  -- L2 clip bound C
    simulation      BOOLEAN NOT NULL DEFAULT FALSE,
    sim_alpha       FLOAT DEFAULT 0.5,     -- Dirichlet α for non-IID partition
    sim_n_clients   INT DEFAULT 5,
    model_arch      JSONB,                 -- {type, input_dim, hidden, output_dim, task}
    created_by      UUID REFERENCES auth.users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- One round per FL task
CREATE TABLE _fd.fl_rounds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES _fd.fl_tasks(id) ON DELETE CASCADE,
    round_n         INT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',
                    -- open | aggregating | done
    client_count    INT DEFAULT 0,
    epsilon_spent   FLOAT,                 -- ε consumed this round (RDP accountant)
    aggregated_weights JSONB,             -- stored only until exported; purged after
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (task_id, round_n)
);

-- Clients registered for a task
CREATE TABLE _fd.fl_clients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES _fd.fl_tasks(id) ON DELETE CASCADE,
    site_id         TEXT NOT NULL,
    dataset_id      UUID,                  -- links to _fd.metadata_tables.id
    registered_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (task_id, site_id)
);

-- Per-dataset DP epsilon budget tracking
CREATE TABLE _fd.fl_epsilon_budget (
    dataset_id      UUID PRIMARY KEY,      -- _fd.metadata_tables.id
    total_budget    FLOAT NOT NULL DEFAULT 10.0,
    spent           FLOAT NOT NULL DEFAULT 0.0,
    last_updated    TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.2 Existing table modifications

```sql
-- Flag datasets that have passed P29 and are eligible for FL participation
ALTER TABLE _fd.metadata_tables ADD COLUMN IF NOT EXISTS fl_eligible BOOLEAN DEFAULT FALSE;
```

**Note:** Gradient payloads are **never stored persistently**. They arrive encrypted (AES-256-GCM), are decrypted in memory, clipped and noised, accumulated into the round's aggregated weights, and the aggregated weights are purged from `fl_rounds` after `export-params` or task deletion.

---

## 5. Privacy — Scientifically Correct DP Pipeline

### 5.1 Per-round gradient processing

For every client update arriving at `POST /fl/tasks/{id}/rounds/{n}/gradients`:

```
1. Decrypt payload (AES-256-GCM, per-task key from env/vault)
2. Clip: w_clipped = w * min(1, C / ||w||₂)   where C = dp_clip_norm
3. Accumulate clipped updates
```

At aggregation trigger (all clients submitted):

```
4. Sum clipped updates
5. Add Gaussian noise: noise ~ N(0, σ²I),  σ = dp_noise_mult * C
6. Divide by client count (FedAvg / FedProx average)
7. RDP accountant: compute ε spent this round → deduct from fl_epsilon_budget
8. If budget exhausted: exclude dataset from future rounds
```

### 5.2 RDP accountant

Use Google's `dp-accounting` library (`pip install dp-accounting`). The noise multiplier σ/C is **pre-computed at task creation** using the RDP accountant given `(ε, δ, rounds_total, clients_per_round)`:

```python
from dp_accounting import dp_event, privacy_accountant
from dp_accounting.rdp import rdp_privacy_accountant

accountant = rdp_privacy_accountant.RdpPrivacyAccountant()
accountant.compose(
    dp_event.SelfComposedDpEvent(
        dp_event.GaussianDpEvent(noise_multiplier=noise_mult),
        count=rounds_total
    )
)
epsilon_consumed = accountant.get_epsilon(target_delta=dp_delta)
```

The task creation endpoint binary-searches for the `noise_mult` that satisfies `epsilon_consumed ≤ dp_epsilon`. This noise multiplier is stored in `fl_tasks.dp_noise_mult` and used every round — no per-round recomputation.

### 5.3 Addition to `src/privacy/helpers.py`

```python
def clip_gradients(weights: np.ndarray, clip_norm: float) -> np.ndarray:
    """Clip weight vector to L2 norm (sensitivity bounding for DP)."""
    norm = np.linalg.norm(weights)
    return weights * min(1.0, clip_norm / norm) if norm > 0 else weights

def add_gaussian_noise_dp(weights: np.ndarray, noise_mult: float, clip_norm: float) -> np.ndarray:
    """Add calibrated Gaussian noise for (ε,δ)-DP after clipping."""
    sigma = noise_mult * clip_norm
    return weights + np.random.normal(0, sigma, size=weights.shape)
```

---

## 6. FL Engine (`src/federated/engine.py`)

### 6.1 Model architectures

Two modes — selected at task creation via `model_arch.type`:

**`tabular_mlp`** — for microbiome / generic CSV datasets:
- Configurable input dim, 2 hidden layers (256, 128), output dim
- Supports classification (CrossEntropy) and regression (MSE)
- Weights serialised as flat numpy array for transport

**`pbpk_param_estimator`** — for PBPK parameter estimation:
- Input: population covariates (age, weight, sex, BMI)
- Output: PBPK parameters (clearance, Vd, absorption rate)
- Feeds directly into existing `PBKFAIRModel.execute()` via the model module
- Training target: minimise residual between ODE-predicted and observed concentration-time data

### 6.2 FedProx local objective

```
min_w F_i(w) + (μ/2) ||w - w_global||²
```

The proximal term `(μ/2)||w - w_global||²` limits how far each client's local model drifts from the global model. μ is stored in `fl_tasks.mu` (default 0.01; setting μ=0 recovers FedAvg).

### 6.3 Simulation mode (Dirichlet non-IID partitioning)

When `simulation=true`, the engine:
1. Loads FL-eligible datasets from the DB
2. Partitions rows across `sim_n_clients` synthetic clients using a **Dirichlet(α)** distribution over class/target labels
   - Low α (e.g. 0.1) = highly non-IID (each client sees few classes)
   - High α (e.g. 100) ≈ IID
3. Runs all FL rounds locally without remote calls
4. Applies DP pipeline identically to real FL (simulation is not exempt from DP)

### 6.4 Convergence monitoring

After each round, compute and store in `fl_rounds`:
- Global loss (evaluated on a held-out validation split)
- Per-client loss before aggregation
- Gradient norm (pre-clip)

Task stops early if `|loss_round_n - loss_round_n-1| < 1e-4` for 3 consecutive rounds.

---

## 7. API Routes (replacing proxy)

Registered in `app.py` at `/fl` prefix (new) and `/federated` (existing, updated internally).

| Method | Route | Auth | Purpose |
|---|---|---|---|
| GET | `/federated/ui` | any role | FL dashboard UI |
| POST | `/fl/tasks` | admin, curator | Create FL task |
| GET | `/fl/tasks/{id}` | any role | Task status + convergence metrics |
| GET | `/fl/tasks/{id}/rounds` | any role | List rounds with ε spent per round |
| POST | `/fl/tasks/{id}/rounds/{n}/gradients` | curator | Submit encrypted client weight update |
| GET | `/fl/tasks/{id}/model` | any role | Latest aggregated weights |
| POST | `/fl/tasks/{id}/export-params` | admin, curator | Export weights as PBPK parameter set |

Legacy `/federated/register`, `/federated/model`, `/federated/update`, `/federated/aggregate`, `/federated/state` are **removed** (were proxy-only stubs).

---

## 8. Cross-Module Integration Points

### 8.1 Privacy module (`src/privacy/helpers.py`)

- Add `clip_gradients()` and `add_gaussian_noise_dp()` (Section 5.3)
- New route `GET /privacy/fl-budget/{dataset_id}` returns remaining ε budget
- `POST /privacy/differential_privacy` form shows warning if dataset is enrolled in FL (DP budget shared)

### 8.2 Data module (`src/data/`)

- After all data generalisation steps complete, expose **"Enroll in FL"** button
- Creates `fl_epsilon_budget` row for the dataset (default budget 10.0 ε)
- Sets `_fd.metadata_tables.fl_eligible = true`
- FL tasks query only `fl_eligible = true` datasets

### 8.3 Model module (`src/model/`)

- `POST /fl/tasks/{id}/export-params` calls `store_parameter_set()` from `src/model/helpers.py`
- Stores FL-aggregated weights as a named parameter set tagged `source = 'federated'`
- `GET /model/parameter-sets` response includes `source` field so UI can badge FL-derived sets
- For `pbpk_param_estimator` tasks: exported parameters feed directly into `run_scenario()`

### 8.4 Admin module (`src/admin/`)

- New page `GET /admin/fl`:
  - Active FL tasks with status, rounds progress, algorithm, ε spent
  - Per-dataset epsilon budget table (total / spent / remaining)
  - FL audit log (task created by, rounds completed, datasets enrolled)
- Admin can reset ε budget for a dataset (requires justification stored in audit log)

### 8.5 Dashboard (`frontend/templates/dashboard/`)

- Dataset cards show **"FL eligible"** badge if `fl_eligible = true`
- Main dashboard card links to `/admin/fl` for admins, `/federated/ui` for others
- FL status widget: active task count, current global round, last ε spend

---

## 9. Security

- Per-task AES-256-GCM key derived from task UUID + app `SECRET_KEY` using HKDF
- Gradient payloads encrypted by client before POST; decrypted server-side in memory only
- `fl_rounds.aggregated_weights` is purged (set NULL) after `export-params` succeeds
- No raw gradient data persists to disk after aggregation

---

## 10. New Dependencies

```
dp-accounting>=0.4.4    # Google RDP accountant
torch>=2.11.0           # already installed, add to requirements.txt
cryptography>=42.0.0    # AES-GCM, HKDF — already likely present via supabase
```

---

## 11. Testing Strategy

- **Unit**: `clip_gradients`, `add_gaussian_noise_dp`, FedProx objective, Dirichlet partitioner
- **DP correctness**: verify RDP accountant output matches expected ε for known (σ, rounds, δ)
- **Integration**: full simulation round-trip — create task → run simulation → export params → run PBPK scenario
- **Budget enforcement**: assert FL round is rejected when `spent ≥ total_budget`
- **Non-IID robustness**: simulation with α=0.1 must still converge within `rounds_total`
- Existing `test_federated_routes.py` updated — mocks replaced with real engine calls
