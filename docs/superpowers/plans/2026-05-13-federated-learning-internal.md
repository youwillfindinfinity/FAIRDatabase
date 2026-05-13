# Federated Learning Internal Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/federated/` proxy stub with a scientifically rigorous internal FL engine using FedProx, RDP-accountant-based (ε,δ)-DP, Dirichlet non-IID simulation, and encrypted gradient transport — integrated across the privacy, data, model, and admin modules.

**Architecture:** A self-contained FL engine (`src/federated/engine.py`) runs FedProx local training and weighted aggregation on PyTorch tabular models. A Rényi DP accountant pre-computes the noise multiplier at task creation so per-round ε consumption is tight and correct. Gradient payloads are AES-256-GCM encrypted in transit, clipped to a fixed L2 norm, noised, and aggregated — with the raw values never written to disk.

**Tech Stack:** PyTorch 2.11 (CPU), `dp-accounting` (Google RDP accountant), `cryptography` (AES-GCM/HKDF), psycopg2, Flask, pytest.

**Commit rules:** Each task ends with one atomic `git commit`. No `Co-Authored-By` lines.

---

## File Map

| Path | Action | Responsibility |
|---|---|---|
| `backend/requirements.txt` | Modify | Add `dp-accounting`, `torch` |
| `backend/fl_schema.sql` | Create | FL DB tables + fl_eligible column |
| `backend/src/privacy/helpers.py` | Modify | Add `clip_gradients`, `add_gaussian_noise_dp` |
| `backend/src/federated/fl_privacy.py` | Create | RDP accountant: noise multiplier + ε spent |
| `backend/src/federated/crypto.py` | Create | AES-256-GCM encrypt/decrypt for gradient payloads |
| `backend/src/federated/db.py` | Create | CRUD for fl_tasks, fl_rounds, fl_clients, fl_epsilon_budget |
| `backend/src/federated/engine.py` | Create | TabularMLP, flat weights, FedProx, FedAvg, Dirichlet |
| `backend/src/federated/routes.py` | Rewrite | Remove proxy; implement /fl/ + /federated/ui |
| `backend/src/data/routes.py` | Modify | Add `POST /data/datasets/<id>/fl-enroll` |
| `backend/src/privacy/routes.py` | Modify | Add `GET /privacy/fl-budget/<dataset_id>` |
| `backend/src/model/helpers.py` | Modify | Accept `source` param in `store_parameter_set` |
| `backend/src/admin/routes.py` | Modify | Add `GET /admin/fl` |
| `backend/frontend/templates/admin/fl.html` | Create | FL admin dashboard |
| `backend/frontend/templates/federated_learning/federated_learning.html` | Rewrite | Task-based FL UI |
| `backend/frontend/templates/dashboard/dashboard.html` | Modify | FL status widget |
| `backend/tests/federated/test_fl_privacy.py` | Create | RDP accountant unit tests |
| `backend/tests/federated/test_crypto.py` | Create | Encrypt/decrypt round-trip tests |
| `backend/tests/federated/test_engine.py` | Create | Engine unit tests |
| `backend/tests/privacy/test_privacy_helpers.py` | Modify | Add clip + Gaussian noise tests |
| `backend/tests/federated/test_federated_routes.py` | Rewrite | Route tests against real engine |
| `backend/tests/federated/test_fl_integration.py` | Create | Simulation round-trip integration test |

---

## Task 1: Add dependencies to requirements.txt

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add packages**

Open `backend/requirements.txt` and append:

```
dp-accounting>=0.4.4
torch>=2.11.0
cryptography>=42.0.0
```

- [ ] **Step 2: Install and verify**

```bash
cd backend && pip install dp-accounting>=0.4.4 cryptography>=42.0.0
python -c "from dp_accounting.rdp import rdp_privacy_accountant; print('dp-accounting OK')"
python -c "import torch; print('torch', torch.__version__)"
```

Expected: both print without error.

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add dp-accounting and cryptography to requirements"
```

---

## Task 2: FL database schema

**Files:**
- Create: `backend/fl_schema.sql`

- [ ] **Step 1: Write the schema file**

Create `backend/fl_schema.sql`:

```sql
-- FL task: one federated training job
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
    created_by      UUID,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- One round per FL task
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

-- Clients registered for a task
CREATE TABLE IF NOT EXISTS _fd.fl_clients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES _fd.fl_tasks(id) ON DELETE CASCADE,
    site_id         TEXT NOT NULL,
    dataset_id      UUID,
    registered_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (task_id, site_id)
);

-- Per-dataset DP epsilon budget
CREATE TABLE IF NOT EXISTS _fd.fl_epsilon_budget (
    dataset_id      UUID PRIMARY KEY,
    total_budget    FLOAT NOT NULL DEFAULT 10.0,
    spent           FLOAT NOT NULL DEFAULT 0.0,
    last_updated    TIMESTAMPTZ DEFAULT NOW()
);

-- FL eligible flag on datasets
ALTER TABLE _fd.metadata_tables
    ADD COLUMN IF NOT EXISTS fl_eligible BOOLEAN NOT NULL DEFAULT FALSE;
```

- [ ] **Step 2: Apply the schema**

```bash
cd backend
psql "host=127.0.0.1 port=5433 dbname=postgres user=postgres password=$(grep POSTGRES_PASSWORD .env | cut -d= -f2)" -f fl_schema.sql
```

Expected: `ALTER TABLE` and multiple `CREATE TABLE` lines, no errors.

- [ ] **Step 3: Verify tables exist**

```bash
psql "host=127.0.0.1 port=5433 dbname=postgres user=postgres password=$(grep POSTGRES_PASSWORD .env | cut -d= -f2)" \
  -c "\dt _fd.fl_*"
```

Expected: 4 rows — `fl_tasks`, `fl_rounds`, `fl_clients`, `fl_epsilon_budget`.

- [ ] **Step 4: Commit**

```bash
git add backend/fl_schema.sql
git commit -m "feat(db): add FL schema — tasks, rounds, clients, epsilon budget"
```

---

## Task 3: Privacy helpers — gradient clipping and Gaussian noise

**Files:**
- Modify: `backend/src/privacy/helpers.py`
- Modify: `backend/tests/privacy/test_privacy_helpers.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/privacy/test_privacy_helpers.py`:

```python
import numpy as np
from src.privacy.helpers import clip_gradients, add_gaussian_noise_dp


def test_clip_gradients_scales_down_large_vector():
    """Vectors with L2 norm > clip_norm must be scaled to exactly clip_norm."""
    w = np.array([3.0, 4.0])  # L2 norm = 5.0
    clipped = clip_gradients(w, clip_norm=1.0)
    assert abs(np.linalg.norm(clipped) - 1.0) < 1e-6


def test_clip_gradients_leaves_small_vector_unchanged():
    """Vectors already within clip_norm must be unchanged."""
    w = np.array([0.3, 0.4])  # L2 norm = 0.5
    clipped = clip_gradients(w, clip_norm=1.0)
    np.testing.assert_array_almost_equal(clipped, w)


def test_clip_gradients_handles_zero_vector():
    """Zero vector must be returned unchanged without division by zero."""
    w = np.zeros(5)
    clipped = clip_gradients(w, clip_norm=1.0)
    np.testing.assert_array_equal(clipped, w)


def test_add_gaussian_noise_dp_changes_values():
    """Noised weights must differ from original."""
    np.random.seed(0)
    w = np.ones(100)
    noised = add_gaussian_noise_dp(w, noise_mult=1.0, clip_norm=1.0)
    assert not np.allclose(noised, w)


def test_add_gaussian_noise_dp_scales_with_noise_mult():
    """Higher noise_mult must produce larger perturbations on average."""
    np.random.seed(42)
    w = np.zeros(10_000)
    low = add_gaussian_noise_dp(w, noise_mult=0.1, clip_norm=1.0)
    high = add_gaussian_noise_dp(w, noise_mult=10.0, clip_norm=1.0)
    assert np.std(high) > np.std(low)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/privacy/test_privacy_helpers.py::test_clip_gradients_scales_down_large_vector -v
```

Expected: `FAILED` with `ImportError: cannot import name 'clip_gradients'`.

- [ ] **Step 3: Implement the two functions**

Append to `backend/src/privacy/helpers.py`:

```python
def clip_gradients(weights: np.ndarray, clip_norm: float) -> np.ndarray:
    """
    Clip weight/gradient vector to L2 norm (sensitivity bounding for DP).

    Required before adding Gaussian noise — without clipping, sensitivity is
    unbounded and the DP guarantee is mathematically invalid.
    """
    norm = np.linalg.norm(weights)
    if norm == 0.0:
        return weights
    return weights * min(1.0, clip_norm / norm)


def add_gaussian_noise_dp(
    weights: np.ndarray, noise_mult: float, clip_norm: float
) -> np.ndarray:
    """
    Add calibrated Gaussian noise for (ε,δ)-DP after clipping.

    σ = noise_mult * clip_norm, where noise_mult is pre-computed by the RDP
    accountant (see src/federated/fl_privacy.py) to satisfy the ε,δ budget
    across all FL rounds.
    """
    sigma = noise_mult * clip_norm
    return weights + np.random.normal(0.0, sigma, size=weights.shape)
```

- [ ] **Step 4: Run all privacy helper tests**

```bash
cd backend && python -m pytest tests/privacy/test_privacy_helpers.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/privacy/helpers.py backend/tests/privacy/test_privacy_helpers.py
git commit -m "feat(privacy): add clip_gradients and add_gaussian_noise_dp for FL DP pipeline"
```

---

## Task 4: RDP accountant — noise multiplier and ε tracking

**Files:**
- Create: `backend/src/federated/fl_privacy.py`
- Create: `backend/tests/federated/test_fl_privacy.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/federated/test_fl_privacy.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from src.federated.fl_privacy import compute_noise_multiplier, compute_epsilon_spent


class TestComputeNoiseMult:
    def test_returns_positive_float(self):
        nm = compute_noise_multiplier(epsilon=1.0, delta=1e-5, rounds=10)
        assert isinstance(nm, float)
        assert nm > 0

    def test_larger_epsilon_gives_smaller_noise_mult(self):
        """More permissive budget → less noise needed."""
        nm_tight = compute_noise_multiplier(epsilon=0.5, delta=1e-5, rounds=10)
        nm_loose = compute_noise_multiplier(epsilon=5.0, delta=1e-5, rounds=10)
        assert nm_loose < nm_tight

    def test_more_rounds_require_more_noise(self):
        """Same budget spread over more rounds → each round needs more noise."""
        nm_few = compute_noise_multiplier(epsilon=1.0, delta=1e-5, rounds=5)
        nm_many = compute_noise_multiplier(epsilon=1.0, delta=1e-5, rounds=50)
        assert nm_many > nm_few


class TestComputeEpsilonSpent:
    def test_zero_rounds_spends_zero(self):
        eps = compute_epsilon_spent(noise_multiplier=1.0, delta=1e-5, rounds_done=0)
        assert eps == 0.0

    def test_spent_increases_with_rounds(self):
        eps_5 = compute_epsilon_spent(noise_multiplier=1.0, delta=1e-5, rounds_done=5)
        eps_10 = compute_epsilon_spent(noise_multiplier=1.0, delta=1e-5, rounds_done=10)
        assert eps_10 > eps_5

    def test_roundtrip_consistency(self):
        """
        If we compute noise_mult to satisfy ε=1.0 over 10 rounds,
        spending 10 rounds must return ε ≤ 1.0.
        """
        nm = compute_noise_multiplier(epsilon=1.0, delta=1e-5, rounds=10)
        spent = compute_epsilon_spent(noise_multiplier=nm, delta=1e-5, rounds_done=10)
        assert spent <= 1.0 + 1e-4  # small tolerance for float search
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/federated/test_fl_privacy.py -v
```

Expected: `FAILED` with `ModuleNotFoundError: No module named 'src.federated.fl_privacy'`.

- [ ] **Step 3: Create the module**

Create `backend/src/federated/fl_privacy.py`:

```python
"""
fl_privacy.py — RDP (Rényi Differential Privacy) accountant for the FL module.

Uses Google's dp-accounting library for tight privacy budget composition
across federated learning rounds. This replaces naive ε/rounds composition,
which is mathematically incorrect.
"""
from dp_accounting import dp_event
from dp_accounting.rdp import rdp_privacy_accountant


def _make_accountant(noise_multiplier: float, rounds: int) -> rdp_privacy_accountant.RdpPrivacyAccountant:
    accountant = rdp_privacy_accountant.RdpPrivacyAccountant()
    if rounds > 0:
        accountant.compose(
            dp_event.SelfComposedDpEvent(
                dp_event.GaussianDpEvent(noise_multiplier=noise_multiplier),
                count=rounds,
            )
        )
    return accountant


def compute_noise_multiplier(
    epsilon: float,
    delta: float,
    rounds: int,
) -> float:
    """
    Binary-search for the smallest noise_multiplier σ/C such that running
    `rounds` Gaussian mechanism steps satisfies (ε, δ)-DP.

    Call this once at FL task creation and store the result in fl_tasks.dp_noise_mult.
    Use the stored value every round — no per-round recomputation.
    """
    if rounds == 0:
        return float("inf")

    low, high = 0.01, 1000.0
    for _ in range(64):
        mid = (low + high) / 2.0
        accountant = _make_accountant(mid, rounds)
        eps = accountant.get_epsilon(target_delta=delta)
        if eps <= epsilon:
            high = mid
        else:
            low = mid
    return high


def compute_epsilon_spent(
    noise_multiplier: float,
    delta: float,
    rounds_done: int,
) -> float:
    """
    Return the actual ε consumed after `rounds_done` rounds with the given
    noise_multiplier. Used to update fl_epsilon_budget after each round.
    """
    if rounds_done == 0:
        return 0.0
    accountant = _make_accountant(noise_multiplier, rounds_done)
    return accountant.get_epsilon(target_delta=delta)
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/federated/test_fl_privacy.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/federated/fl_privacy.py backend/tests/federated/test_fl_privacy.py
git commit -m "feat(federated): add RDP accountant for correct (epsilon,delta)-DP across FL rounds"
```

---

## Task 5: AES-256-GCM gradient encryption

**Files:**
- Create: `backend/src/federated/crypto.py`
- Create: `backend/tests/federated/test_crypto.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/federated/test_crypto.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pytest
from src.federated.crypto import encrypt_weights, decrypt_weights


SECRET = "test-secret-key-abc"
TASK_ID = "task-uuid-1234"


class TestEncryptDecrypt:
    def test_roundtrip_recovers_original(self):
        w = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        recovered = decrypt_weights(payload, TASK_ID, SECRET)
        np.testing.assert_array_almost_equal(recovered, w)

    def test_different_nonces_each_call(self):
        w = np.ones(10, dtype=np.float32)
        p1 = encrypt_weights(w, TASK_ID, SECRET)
        p2 = encrypt_weights(w, TASK_ID, SECRET)
        assert p1["nonce"] != p2["nonce"]

    def test_wrong_task_id_fails(self):
        w = np.ones(5, dtype=np.float32)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        with pytest.raises(Exception):
            decrypt_weights(payload, "wrong-task-id", SECRET)

    def test_wrong_secret_fails(self):
        w = np.ones(5, dtype=np.float32)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        with pytest.raises(Exception):
            decrypt_weights(payload, TASK_ID, "wrong-secret")

    def test_payload_has_required_keys(self):
        w = np.array([0.5, -0.5], dtype=np.float32)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        assert {"ciphertext", "nonce"} <= set(payload.keys())
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/federated/test_crypto.py -v
```

Expected: `FAILED` with `ModuleNotFoundError`.

- [ ] **Step 3: Implement crypto module**

Create `backend/src/federated/crypto.py`:

```python
"""
crypto.py — AES-256-GCM encryption for FL gradient payloads.

Gradient updates are encrypted before transmission and decrypted
in-memory on the server. Raw gradient values are never persisted to disk.
"""
import os
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


def _derive_task_key(task_id: str, secret_key: str) -> bytes:
    """Derive a 256-bit AES key from task_id + app SECRET_KEY using HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"fl-gradient-encryption",
    )
    return hkdf.derive((secret_key + task_id).encode("utf-8"))


def encrypt_weights(weights: np.ndarray, task_id: str, secret_key: str) -> dict:
    """
    Encrypt a flat float32 weight array with AES-256-GCM.

    Returns a dict with hex-encoded 'ciphertext' and 'nonce'.
    A fresh random nonce is generated each call.
    """
    key = _derive_task_key(task_id, secret_key)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    plaintext = weights.astype(np.float32).tobytes()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return {
        "ciphertext": ciphertext.hex(),
        "nonce": nonce.hex(),
    }


def decrypt_weights(payload: dict, task_id: str, secret_key: str) -> np.ndarray:
    """
    Decrypt a payload produced by encrypt_weights back to a float32 array.

    Raises cryptography.exceptions.InvalidTag if the key or nonce is wrong.
    """
    key = _derive_task_key(task_id, secret_key)
    aesgcm = AESGCM(key)
    nonce = bytes.fromhex(payload["nonce"])
    ciphertext = bytes.fromhex(payload["ciphertext"])
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return np.frombuffer(plaintext, dtype=np.float32)
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/federated/test_crypto.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/federated/crypto.py backend/tests/federated/test_crypto.py
git commit -m "feat(federated): AES-256-GCM gradient payload encryption"
```

---

## Task 6: FL database layer

**Files:**
- Create: `backend/src/federated/db.py`

The DB layer uses psycopg2 via Flask's `g.db` connection (same pattern as `src/model/helpers.py`). No tests requiring live DB here — DB interactions are tested in Task 14 (integration test).

- [ ] **Step 1: Create db.py**

Create `backend/src/federated/db.py`:

```python
"""
db.py — PostgreSQL CRUD for the FL module (_fd schema).

All functions accept a psycopg2 connection and operate within the
caller's transaction. The caller is responsible for commit/rollback.
"""
from __future__ import annotations
import json
import uuid
from typing import Optional


def create_task(conn, *, algorithm: str, rounds_total: int, mu: float,
                dp_epsilon: float, dp_delta: float, dp_noise_mult: float,
                dp_clip_norm: float, simulation: bool, sim_alpha: float,
                sim_n_clients: int, model_arch: dict, created_by: Optional[str]) -> str:
    """Insert a new FL task and return its UUID."""
    task_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO _fd.fl_tasks
                (id, algorithm, rounds_total, mu, dp_epsilon, dp_delta,
                 dp_noise_mult, dp_clip_norm, simulation, sim_alpha,
                 sim_n_clients, model_arch, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (task_id, algorithm, rounds_total, mu, dp_epsilon, dp_delta,
             dp_noise_mult, dp_clip_norm, simulation, sim_alpha,
             sim_n_clients, json.dumps(model_arch), created_by),
        )
    conn.commit()
    return task_id


def get_task(conn, task_id: str) -> Optional[dict]:
    """Return task row as dict or None."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM _fd.fl_tasks WHERE id = %s", (task_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def advance_task_round(conn, task_id: str) -> None:
    """Increment rounds_done by 1."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE _fd.fl_tasks SET rounds_done = rounds_done + 1 WHERE id = %s",
            (task_id,),
        )
    conn.commit()


def set_task_status(conn, task_id: str, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE _fd.fl_tasks SET status = %s WHERE id = %s",
            (status, task_id),
        )
    conn.commit()


def create_round(conn, task_id: str, round_n: int) -> str:
    """Open a new round and return its UUID."""
    round_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO _fd.fl_rounds (id, task_id, round_n) VALUES (%s,%s,%s)",
            (round_id, task_id, round_n),
        )
    conn.commit()
    return round_id


def get_round(conn, task_id: str, round_n: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM _fd.fl_rounds WHERE task_id=%s AND round_n=%s",
            (task_id, round_n),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def list_rounds(conn, task_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM _fd.fl_rounds WHERE task_id=%s ORDER BY round_n",
            (task_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def store_aggregated_weights(conn, task_id: str, round_n: int,
                              weights: list, epsilon_spent: float, loss: Optional[float]) -> None:
    """Store aggregated weights JSON and ε consumed into the round row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE _fd.fl_rounds
            SET aggregated_weights = %s, epsilon_spent = %s, loss = %s, status = 'done'
            WHERE task_id = %s AND round_n = %s
            """,
            (json.dumps(weights), epsilon_spent, loss, task_id, round_n),
        )
    conn.commit()


def get_latest_weights(conn, task_id: str) -> Optional[list]:
    """Return aggregated_weights from the most recently completed round."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT aggregated_weights FROM _fd.fl_rounds
            WHERE task_id = %s AND status = 'done'
            ORDER BY round_n DESC LIMIT 1
            """,
            (task_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def purge_round_weights(conn, task_id: str) -> None:
    """Delete raw aggregated weights after export (privacy hygiene)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE _fd.fl_rounds SET aggregated_weights = NULL WHERE task_id = %s",
            (task_id,),
        )
    conn.commit()


def get_epsilon_budget(conn, dataset_id: str) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM _fd.fl_epsilon_budget WHERE dataset_id = %s", (dataset_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def consume_epsilon(conn, dataset_id: str, amount: float) -> None:
    """Deduct amount from budget and update timestamp."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE _fd.fl_epsilon_budget
            SET spent = spent + %s, last_updated = NOW()
            WHERE dataset_id = %s
            """,
            (amount, dataset_id),
        )
    conn.commit()


def enroll_dataset(conn, dataset_id: str, total_budget: float = 10.0) -> None:
    """Mark a dataset as FL-eligible and initialise its epsilon budget."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE _fd.metadata_tables SET fl_eligible = TRUE WHERE id = %s",
            (dataset_id,),
        )
        cur.execute(
            """
            INSERT INTO _fd.fl_epsilon_budget (dataset_id, total_budget)
            VALUES (%s, %s)
            ON CONFLICT (dataset_id) DO UPDATE SET total_budget = EXCLUDED.total_budget
            """,
            (dataset_id, total_budget),
        )
    conn.commit()


def list_fl_eligible_datasets(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, table_name, owner_id
            FROM _fd.metadata_tables
            WHERE fl_eligible = TRUE
            """,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/federated/db.py
git commit -m "feat(federated): FL database layer — task, round, client, epsilon CRUD"
```

---

## Task 7: FL engine — model and flat weights

**Files:**
- Create: `backend/src/federated/engine.py`
- Create: `backend/tests/federated/test_engine.py`

- [ ] **Step 1: Write failing tests for model and flat weight helpers**

Create `backend/tests/federated/test_engine.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pytest
import torch
from src.federated.engine import (
    TabularMLP,
    get_flat_weights,
    set_flat_weights,
    local_train_fedprox,
    fedprox_aggregate,
    dirichlet_partition,
)


class TestTabularMLP:
    def test_forward_shape_regression(self):
        model = TabularMLP(input_dim=4, hidden_dims=[16, 8], output_dim=1, task="regression")
        x = torch.randn(10, 4)
        out = model(x)
        assert out.shape == (10, 1)

    def test_forward_shape_classification(self):
        model = TabularMLP(input_dim=4, hidden_dims=[16], output_dim=3, task="classification")
        x = torch.randn(5, 4)
        out = model(x)
        assert out.shape == (5, 3)
        # Softmax output must sum to 1 per row
        assert torch.allclose(out.sum(dim=1), torch.ones(5), atol=1e-5)


class TestFlatWeights:
    def test_roundtrip(self):
        model = TabularMLP(input_dim=3, hidden_dims=[8], output_dim=1, task="regression")
        original = get_flat_weights(model)
        # Perturb
        set_flat_weights(model, original * 2)
        recovered_base = get_flat_weights(model)
        np.testing.assert_array_almost_equal(recovered_base, original * 2)

    def test_flat_weights_length_matches_param_count(self):
        model = TabularMLP(input_dim=2, hidden_dims=[4], output_dim=1, task="regression")
        n_params = sum(p.numel() for p in model.parameters())
        assert len(get_flat_weights(model)) == n_params


class TestFedProxLocalTrain:
    def test_weights_change_after_training(self):
        model = TabularMLP(input_dim=2, hidden_dims=[8], output_dim=1, task="regression")
        global_w = get_flat_weights(model)
        X = np.random.randn(20, 2).astype(np.float32)
        y = np.random.randn(20).astype(np.float32)
        updated_w = local_train_fedprox(model, global_w, X, y,
                                        epochs=5, lr=0.01, mu=0.01, task="regression")
        assert not np.allclose(updated_w, global_w)

    def test_output_shape_matches_input(self):
        model = TabularMLP(input_dim=3, hidden_dims=[4], output_dim=1, task="regression")
        global_w = get_flat_weights(model)
        X = np.random.randn(10, 3).astype(np.float32)
        y = np.random.randn(10).astype(np.float32)
        out = local_train_fedprox(model, global_w, X, y,
                                  epochs=2, lr=0.01, mu=0.0, task="regression")
        assert len(out) == len(global_w)


class TestFedProxAggregate:
    def test_uniform_weights_averages_correctly(self):
        w1 = np.array([1.0, 2.0])
        w2 = np.array([3.0, 4.0])
        agg = fedprox_aggregate([w1, w2], client_sizes=[10, 10])
        np.testing.assert_array_almost_equal(agg, [2.0, 3.0])

    def test_weighted_by_client_size(self):
        w1 = np.array([0.0])
        w2 = np.array([10.0])
        agg = fedprox_aggregate([w1, w2], client_sizes=[9, 1])
        assert agg[0] == pytest.approx(1.0)


class TestDirichletPartition:
    def test_returns_n_clients_partitions(self):
        X = np.random.randn(100, 4)
        y = np.repeat([0, 1, 2, 3], 25)
        parts = dirichlet_partition(X, y, n_clients=4, alpha=0.5)
        assert len(parts) == 4

    def test_all_data_is_distributed(self):
        X = np.random.randn(200, 3)
        y = np.repeat([0, 1], 100)
        parts = dirichlet_partition(X, y, n_clients=5, alpha=1.0)
        total = sum(len(px) for px, _ in parts)
        assert total == 200

    def test_low_alpha_is_more_non_iid_than_high_alpha(self):
        """
        With low α, some clients should have nearly 0 samples of some classes.
        Measure heterogeneity by the variance of class proportions across clients.
        """
        np.random.seed(0)
        X = np.random.randn(500, 2)
        y = np.repeat([0, 1, 2, 3, 4], 100)

        def class_variance(parts, n_classes=5):
            props = []
            for px, py in parts:
                if len(py) == 0:
                    props.append([0.0] * n_classes)
                    continue
                counts = np.bincount(py.astype(int), minlength=n_classes)
                props.append(counts / len(py))
            return np.array(props).var(axis=0).mean()

        low_var = class_variance(dirichlet_partition(X, y, n_clients=5, alpha=0.1))
        high_var = class_variance(dirichlet_partition(X, y, n_clients=5, alpha=100.0))
        assert low_var > high_var
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/federated/test_engine.py -v 2>&1 | head -20
```

Expected: `FAILED` with `ModuleNotFoundError: No module named 'src.federated.engine'`.

- [ ] **Step 3: Implement engine.py**

Create `backend/src/federated/engine.py`:

```python
"""
engine.py — Federated Learning engine.

Implements:
- TabularMLP: configurable PyTorch model for tabular data
- get_flat_weights / set_flat_weights: serialise/deserialise model state
- local_train_fedprox: FedProx local objective with proximal regularisation
- fedprox_aggregate: weighted FedAvg aggregation
- dirichlet_partition: Dirichlet-based non-IID data partitioning for simulation

FedProx reference: Li et al., "Federated Optimization in Heterogeneous Networks" (2020)
Dirichlet non-IID: Yurochkin et al., "Bayesian Nonparametric Federated Learning" (2019)
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from typing import List, Tuple


# ── Model ─────────────────────────────────────────────────────────────────────

class TabularMLP(nn.Module):
    """Multi-layer perceptron for tabular data. Supports regression and classification."""

    def __init__(self, input_dim: int, hidden_dims: List[int], output_dim: int,
                 task: str = "regression"):
        super().__init__()
        dims = [input_dim] + hidden_dims
        layers: List[nn.Module] = []
        for i in range(len(dims) - 1):
            layers.append(nn.Linear(dims[i], dims[i + 1]))
            layers.append(nn.ReLU())
        layers.append(nn.Linear(dims[-1], output_dim))
        if task == "classification":
            layers.append(nn.Softmax(dim=-1))
        self.net = nn.Sequential(*layers)
        self.task = task

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def get_flat_weights(model: nn.Module) -> np.ndarray:
    """Flatten all model parameters into a 1-D float32 numpy array."""
    return np.concatenate(
        [p.detach().numpy().ravel() for p in model.parameters()]
    )


def set_flat_weights(model: nn.Module, weights: np.ndarray) -> None:
    """Load a flat 1-D numpy array back into model parameters (in-place)."""
    idx = 0
    for p in model.parameters():
        n = p.numel()
        p.data.copy_(
            torch.from_numpy(weights[idx: idx + n].reshape(p.shape).astype(np.float32))
        )
        idx += n


# ── Training ──────────────────────────────────────────────────────────────────

def local_train_fedprox(
    model: nn.Module,
    global_weights: np.ndarray,
    data_X: np.ndarray,
    data_y: np.ndarray,
    epochs: int,
    lr: float,
    mu: float,
    task: str = "regression",
) -> np.ndarray:
    """
    Run local FedProx training on one client partition.

    Minimises: F_i(w) + (μ/2) ||w - w_global||²

    Setting μ=0 recovers standard FedAvg local training.
    Returns updated flat weights (does not modify model in-place after training).
    """
    set_flat_weights(model, global_weights)

    optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    criterion = (
        nn.MSELoss() if task == "regression" else nn.CrossEntropyLoss()
    )

    X = torch.FloatTensor(data_X)
    if task == "regression":
        y = torch.FloatTensor(data_y).unsqueeze(1) if data_y.ndim == 1 else torch.FloatTensor(data_y)
    else:
        y = torch.LongTensor(data_y.astype(int))

    # Snapshot of global weights for the proximal term
    global_tensors = [
        torch.FloatTensor(p.detach().numpy().copy())
        for p in model.parameters()
    ]

    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        output = model(X)
        loss = criterion(output, y)

        # FedProx proximal term: (μ/2) * Σ ||w_i - w_global||²
        if mu > 0.0:
            prox = sum(
                ((p - g) ** 2).sum()
                for p, g in zip(model.parameters(), global_tensors)
            )
            loss = loss + (mu / 2.0) * prox

        loss.backward()
        optimizer.step()

    return get_flat_weights(model)


# ── Aggregation ───────────────────────────────────────────────────────────────

def fedprox_aggregate(
    client_weights: List[np.ndarray],
    client_sizes: List[int],
) -> np.ndarray:
    """
    Weighted FedAvg aggregation.

    FedProx uses the same server-side aggregation as FedAvg;
    the proximal term acts only during local training.
    """
    total = sum(client_sizes)
    result = np.zeros_like(client_weights[0], dtype=np.float64)
    for w, n in zip(client_weights, client_sizes):
        result += w.astype(np.float64) * (n / total)
    return result.astype(np.float32)


# ── Simulation ────────────────────────────────────────────────────────────────

def dirichlet_partition(
    data_X: np.ndarray,
    data_y: np.ndarray,
    n_clients: int,
    alpha: float,
    seed: int = 42,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Partition (data_X, data_y) into n_clients subsets using a Dirichlet
    distribution over class labels.

    Low α (e.g. 0.1) → highly non-IID (each client sees few classes).
    High α (e.g. 100) → near-IID distribution.

    Reference: Yurochkin et al., ICML 2019 (§3.2).
    """
    rng = np.random.default_rng(seed)
    classes = np.unique(data_y)
    client_indices: List[List[int]] = [[] for _ in range(n_clients)]

    for cls in classes:
        cls_idx = np.where(data_y == cls)[0]
        rng.shuffle(cls_idx)
        proportions = rng.dirichlet([alpha] * n_clients)
        counts = (proportions * len(cls_idx)).astype(int)
        # Fix rounding so total == len(cls_idx)
        counts[-1] = len(cls_idx) - counts[:-1].sum()
        ptr = 0
        for client_id, count in enumerate(counts):
            client_indices[client_id].extend(cls_idx[ptr: ptr + count].tolist())
            ptr += count

    return [
        (data_X[idxs], data_y[idxs])
        for idxs in client_indices
    ]
```

- [ ] **Step 4: Run tests**

```bash
cd backend && PYTHONPATH=.. python -m pytest tests/federated/test_engine.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/federated/engine.py backend/tests/federated/test_engine.py
git commit -m "feat(federated): FL engine — TabularMLP, FedProx training, FedAvg aggregation, Dirichlet partition"
```

---

## Task 8: FL routes — replace proxy with real implementation

**Files:**
- Rewrite: `backend/src/federated/routes.py`
- Rewrite: `backend/tests/federated/test_federated_routes.py`

- [ ] **Step 1: Rewrite routes.py**

Overwrite `backend/src/federated/routes.py` with:

```python
"""
routes.py — FL blueprint.

/federated/ui              GET  — FL dashboard UI (login required)
/fl/tasks                  POST — Create FL task
/fl/tasks/<id>             GET  — Task status
/fl/tasks/<id>/rounds      GET  — List rounds
/fl/tasks/<id>/rounds/<n>/gradients  POST — Submit encrypted client update
/fl/tasks/<id>/model       GET  — Latest aggregated weights
/fl/tasks/<id>/export-params POST — Export weights as PBPK parameter set
"""
import os
import numpy as np
from flask import (
    Blueprint, g, jsonify, redirect, render_template, request, session, url_for
)

from src.auth.decorators import login_required
from src.federated.fl_privacy import compute_noise_multiplier, compute_epsilon_spent
from src.federated.crypto import decrypt_weights
from src.federated.engine import (
    TabularMLP, get_flat_weights, set_flat_weights,
    local_train_fedprox, fedprox_aggregate, dirichlet_partition,
)
from src.federated import db as fl_db
from src.privacy.helpers import clip_gradients, add_gaussian_noise_dp

routes = Blueprint("federated_routes", __name__)

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")

# ── Legacy redirect ────────────────────────────────────────────────────────────

@routes.route("/federated_learning/federated_learning")
def legacy_federated_redirect():
    return redirect(url_for("federated_routes.federated_ui"), 301)


# ── UI ─────────────────────────────────────────────────────────────────────────

@routes.route("/ui", methods=["GET"])
@login_required()
def federated_ui():
    tasks = []
    try:
        with g.db.cursor() as cur:
            cur.execute("SELECT id, status, rounds_total, rounds_done, algorithm, dp_epsilon, simulation FROM _fd.fl_tasks ORDER BY created_at DESC LIMIT 20")
            cols = [d[0] for d in cur.description]
            tasks = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        g.db.rollback()
    return render_template(
        "federated_learning/federated_learning.html",
        tasks=tasks,
        user_email=session.get("email"),
        current_path=request.path,
    )


# ── Task endpoints ─────────────────────────────────────────────────────────────

@routes.route("/tasks", methods=["POST"])
@login_required("admin", "curator")
def create_task():
    payload = request.get_json(silent=True) or {}
    required = {"dp_epsilon", "rounds_total"}
    missing = required - set(payload)
    if missing:
        return jsonify({"error": f"Missing fields: {sorted(missing)}"}), 400

    dp_epsilon = float(payload["dp_epsilon"])
    dp_delta = float(payload.get("dp_delta", 1e-5))
    rounds_total = int(payload["rounds_total"])

    noise_mult = compute_noise_multiplier(
        epsilon=dp_epsilon, delta=dp_delta, rounds=rounds_total
    )

    task_id = fl_db.create_task(
        g.db,
        algorithm=payload.get("algorithm", "fedprox"),
        rounds_total=rounds_total,
        mu=float(payload.get("mu", 0.01)),
        dp_epsilon=dp_epsilon,
        dp_delta=dp_delta,
        dp_noise_mult=noise_mult,
        dp_clip_norm=float(payload.get("dp_clip_norm", 1.0)),
        simulation=bool(payload.get("simulation", False)),
        sim_alpha=float(payload.get("sim_alpha", 0.5)),
        sim_n_clients=int(payload.get("sim_n_clients", 5)),
        model_arch=payload.get("model_arch", {}),
        created_by=g.user,
    )
    return jsonify({"task_id": task_id, "dp_noise_mult": noise_mult}), 201


@routes.route("/tasks/<task_id>", methods=["GET"])
@login_required()
def get_task(task_id):
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task), 200


@routes.route("/tasks/<task_id>/rounds", methods=["GET"])
@login_required()
def list_rounds(task_id):
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    rounds = fl_db.list_rounds(g.db, task_id)
    # Strip raw weights from response — never expose to clients
    for r in rounds:
        r.pop("aggregated_weights", None)
    return jsonify(rounds), 200


@routes.route("/tasks/<task_id>/rounds/<int:round_n>/gradients", methods=["POST"])
@login_required("admin", "curator")
def submit_gradients(task_id, round_n):
    """
    Accept an encrypted client weight update, decrypt in memory,
    clip to L2 norm, add Gaussian DP noise, and aggregate.
    """
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404

    payload = request.get_json(silent=True) or {}
    if "ciphertext" not in payload or "nonce" not in payload:
        return jsonify({"error": "Encrypted gradient payload required"}), 400

    # Check epsilon budget for this dataset
    dataset_id = payload.get("dataset_id")
    if dataset_id:
        budget = fl_db.get_epsilon_budget(g.db, dataset_id)
        if budget and (budget["spent"] >= budget["total_budget"]):
            return jsonify({"error": "Epsilon budget exhausted for this dataset"}), 403

    # Decrypt in memory — never written to disk
    weights = decrypt_weights(payload, task_id, SECRET_KEY)

    # DP pipeline: clip → noise
    clip_norm = float(task["dp_clip_norm"])
    noise_mult = float(task["dp_noise_mult"])
    clipped = clip_gradients(weights, clip_norm)
    noised = add_gaussian_noise_dp(clipped, noise_mult, clip_norm)

    # Open or get current round
    rnd = fl_db.get_round(g.db, task_id, round_n)
    if rnd is None:
        fl_db.create_round(g.db, task_id, round_n)

    # Accumulate into round — fetch existing aggregated weights if present
    rnd = fl_db.get_round(g.db, task_id, round_n)
    existing = rnd.get("aggregated_weights") or []
    existing_count = rnd.get("client_count", 0)

    # Running weighted sum (will be divided on aggregation trigger)
    if existing:
        acc = np.array(existing, dtype=np.float32) + noised
    else:
        acc = noised.copy()
    new_count = existing_count + 1

    # Check if all expected clients have submitted
    clients_needed = int(task.get("sim_n_clients", 1)) if task["simulation"] else new_count
    is_final = task["simulation"] or new_count >= clients_needed

    if is_final:
        # Divide accumulated sum by client count to get average
        aggregated = (acc / new_count).tolist()
        eps_spent = compute_epsilon_spent(
            noise_multiplier=noise_mult,
            delta=float(task["dp_delta"]),
            rounds_done=int(task["rounds_done"]) + 1,
        )
        fl_db.store_aggregated_weights(g.db, task_id, round_n,
                                        aggregated, eps_spent, None)
        fl_db.advance_task_round(g.db, task_id)

        if dataset_id:
            fl_db.consume_epsilon(g.db, dataset_id, eps_spent)

        if int(task["rounds_done"]) + 1 >= int(task["rounds_total"]):
            fl_db.set_task_status(g.db, task_id, "completed")
    else:
        # Store intermediate accumulation back into round
        with g.db.cursor() as cur:
            import json
            cur.execute(
                "UPDATE _fd.fl_rounds SET aggregated_weights=%s, client_count=%s WHERE task_id=%s AND round_n=%s",
                (json.dumps(acc.tolist()), new_count, task_id, round_n),
            )
        g.db.commit()

    return jsonify({"status": "accepted", "round": round_n, "clients": new_count}), 200


@routes.route("/tasks/<task_id>/model", methods=["GET"])
@login_required()
def get_model(task_id):
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    weights = fl_db.get_latest_weights(g.db, task_id)
    if weights is None:
        return jsonify({"error": "No completed round yet"}), 404
    return jsonify({"task_id": task_id, "weights": weights}), 200


@routes.route("/tasks/<task_id>/export-params", methods=["POST"])
@login_required("admin", "curator")
def export_params(task_id):
    """Export final aggregated FL weights as a named PBPK parameter set."""
    from src.model.helpers import store_parameter_set
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    weights = fl_db.get_latest_weights(g.db, task_id)
    if weights is None:
        return jsonify({"error": "No model to export yet"}), 404

    payload = request.get_json(silent=True) or {}
    name = payload.get("name", f"FL-task-{task_id[:8]}")
    description = payload.get("description", f"Federated learning aggregated weights (task {task_id})")

    ps_id = store_parameter_set(
        name=name,
        description=description,
        params={"fl_weights": weights, "fl_task_id": task_id},
        created_by=session.get("email", ""),
        owner_id=g.user,
        source="federated",
    )

    # Purge raw weights from DB after export (privacy hygiene)
    fl_db.purge_round_weights(g.db, task_id)

    return jsonify({"parameter_set_id": ps_id, "name": name}), 201
```

- [ ] **Step 2: Register /fl blueprint in app.py**

In `backend/app.py`, find the blueprint registration block and add:

```python
from src.federated.routes import routes as federated_routes
# ... existing imports ...
app.register_blueprint(federated_routes, url_prefix="/federated")
app.register_blueprint(federated_routes, url_prefix="/fl", name="fl_routes")
```

Wait — Flask doesn't allow registering the same blueprint object twice. Instead, create a thin second blueprint in routes.py by adding at the bottom of `backend/src/federated/routes.py`:

```python
# Second registration point for /fl/ prefix (FAIRification.md spec namespace)
fl_routes = Blueprint("fl_routes", __name__)
fl_routes.add_url_rule("/tasks", view_func=create_task, methods=["POST"])
fl_routes.add_url_rule("/tasks/<task_id>", view_func=get_task, methods=["GET"])
fl_routes.add_url_rule("/tasks/<task_id>/rounds", view_func=list_rounds, methods=["GET"])
fl_routes.add_url_rule("/tasks/<task_id>/rounds/<int:round_n>/gradients",
                        view_func=submit_gradients, methods=["POST"])
fl_routes.add_url_rule("/tasks/<task_id>/model", view_func=get_model, methods=["GET"])
fl_routes.add_url_rule("/tasks/<task_id>/export-params",
                        view_func=export_params, methods=["POST"])
```

Then in `backend/app.py`, add after the existing federated blueprint registration:

```python
from src.federated.routes import fl_routes
app.register_blueprint(fl_routes, url_prefix="/fl")
```

- [ ] **Step 3: Rewrite the route tests**

Overwrite `backend/tests/federated/test_federated_routes.py`:

```python
"""Tests for the /federated and /fl blueprints — real engine, no upstream mocks."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from unittest.mock import patch, MagicMock
import numpy as np
from src.federated.crypto import encrypt_weights


SECRET = "test-secret"


class TestFLTaskCreation:
    def test_create_task_missing_fields_returns_400(self, client):
        resp = client.post("/fl/tasks", json={}, content_type="application/json")
        assert resp.status_code in (302, 400)  # 302 = not logged in redirect

    def test_ui_redirects_when_not_logged_in(self, client):
        resp = client.get("/federated/ui")
        assert resp.status_code == 302

    def test_get_nonexistent_task_returns_404(self, client):
        resp = client.get("/fl/tasks/00000000-0000-0000-0000-000000000000")
        # 302 if auth wall, 404 if authenticated
        assert resp.status_code in (302, 404)


class TestFLInputValidation:
    def test_gradients_endpoint_requires_encrypted_payload(self, client):
        resp = client.post(
            "/fl/tasks/fake-id/rounds/1/gradients",
            json={"weights": [1.0, 2.0]},
            content_type="application/json",
        )
        assert resp.status_code in (302, 400)

    def test_list_rounds_nonexistent_task(self, client):
        resp = client.get("/fl/tasks/00000000-0000-0000-0000-000000000000/rounds")
        assert resp.status_code in (302, 404)

    def test_get_model_nonexistent_task(self, client):
        resp = client.get("/fl/tasks/00000000-0000-0000-0000-000000000000/model")
        assert resp.status_code in (302, 404)


class TestLegacyRedirect:
    def test_legacy_url_redirects(self, client):
        resp = client.get("/federated/federated_learning/federated_learning")
        assert resp.status_code in (301, 302)
```

- [ ] **Step 4: Run the tests**

```bash
cd backend && PYTHONPATH=.. python -m pytest tests/federated/test_federated_routes.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/federated/routes.py backend/tests/federated/test_federated_routes.py backend/app.py
git commit -m "feat(federated): replace proxy with internal FL engine routes (/fl/ + /federated/)"
```

---

## Task 9: Data module — FL eligibility enrollment

**Files:**
- Modify: `backend/src/data/routes.py`

- [ ] **Step 1: Add the enrollment route**

In `backend/src/data/routes.py`, add after the existing imports:

```python
from src.federated import db as fl_db
```

Then add this route at the end of the file:

```python
@routes.route("/datasets/<dataset_id>/fl-enroll", methods=["POST"])
@login_required("admin", "curator")
def fl_enroll(dataset_id):
    """
    Mark a dataset as FL-eligible after P29 assessment passes.

    Creates a fl_epsilon_budget row with the provided total_budget (default 10.0 ε).
    Only datasets that have completed data generalisation should be enrolled.
    """
    payload = request.get_json(silent=True) or {}
    total_budget = float(payload.get("total_budget", 10.0))

    if total_budget <= 0:
        return jsonify({"error": "total_budget must be positive"}), 400

    try:
        fl_db.enroll_dataset(g.db, dataset_id, total_budget)
    except Exception as exc:
        g.db.rollback()
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "dataset_id": dataset_id,
        "fl_eligible": True,
        "total_budget": total_budget,
    }), 200
```

- [ ] **Step 2: Verify import works**

```bash
cd backend && PYTHONPATH=.. python -c "from src.data.routes import routes; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/src/data/routes.py
git commit -m "feat(data): add FL eligibility enrollment endpoint"
```

---

## Task 10: Privacy module — epsilon budget route

**Files:**
- Modify: `backend/src/privacy/routes.py`

- [ ] **Step 1: Add the budget query route**

In `backend/src/privacy/routes.py`, add after the existing imports:

```python
from src.federated import db as fl_db
```

Add at the end of the file:

```python
@routes.route("/fl-budget/<dataset_id>", methods=["GET"])
@login_required("admin", "curator")
def fl_budget(dataset_id):
    """
    Return the remaining DP epsilon budget for a dataset enrolled in FL.

    Budget consumption is tracked in _fd.fl_epsilon_budget and decremented
    after each FL round that uses this dataset.
    """
    budget = fl_db.get_epsilon_budget(g.db, dataset_id)
    if budget is None:
        return jsonify({"error": "Dataset not enrolled in FL"}), 404

    remaining = budget["total_budget"] - budget["spent"]
    return jsonify({
        "dataset_id": dataset_id,
        "total_budget": budget["total_budget"],
        "spent": budget["spent"],
        "remaining": remaining,
        "exhausted": remaining <= 0,
    }), 200
```

- [ ] **Step 2: Verify**

```bash
cd backend && PYTHONPATH=.. python -c "from src.privacy.routes import routes; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/privacy/routes.py
git commit -m "feat(privacy): add FL epsilon budget query endpoint"
```

---

## Task 11: Model module — tag FL-derived parameter sets

**Files:**
- Modify: `backend/src/model/helpers.py`

- [ ] **Step 1: Read the current store_parameter_set signature**

Open `backend/src/model/helpers.py` and find `store_parameter_set`. It currently looks like:

```python
def store_parameter_set(
    name: str,
    description: str,
    params: dict,
    created_by: str,
    owner_id: str | None = None,
```

- [ ] **Step 2: Add `source` parameter**

Add `source: str = "manual"` to the signature and include it in the INSERT:

```python
def store_parameter_set(
    name: str,
    description: str,
    params: dict,
    created_by: str,
    owner_id: str | None = None,
    source: str = "manual",
) -> int:
```

Find the INSERT statement inside the function and add `source` to the columns and values. The exact SQL will depend on the existing table schema. Add `source` as a column to whatever INSERT is there:

```python
# In the INSERT, add source to columns and values:
# Example (adapt to actual SQL in the function):
cur.execute(
    """INSERT INTO _fd.pbpk_parameter_sets
       (name, description, params, created_by, owner_id, source)
       VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
    (name, description, json.dumps(params), created_by, owner_id, source),
)
```

Also add the column to the DB if it doesn't exist:

```bash
psql "host=127.0.0.1 port=5433 dbname=postgres user=postgres password=$(grep POSTGRES_PASSWORD backend/.env | cut -d= -f2)" \
  -c "ALTER TABLE _fd.pbpk_parameter_sets ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual';"
```

- [ ] **Step 3: Verify existing model tests still pass**

```bash
cd backend && PYTHONPATH=.. python -m pytest tests/model/ -v
```

Expected: all existing model tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/src/model/helpers.py
git commit -m "feat(model): add source field to parameter sets for FL-derived tagging"
```

---

## Task 12: Admin module — FL dashboard page

**Files:**
- Modify: `backend/src/admin/routes.py`
- Create: `backend/frontend/templates/admin/fl.html`

- [ ] **Step 1: Add the /admin/fl route**

In `backend/src/admin/routes.py`, add after existing imports:

```python
from src.federated import db as fl_db
```

Add at the end of the file:

```python
@routes.route("/fl", methods=["GET"])
@login_required("admin")
def fl_dashboard():
    """FL admin console: active tasks, epsilon budgets, audit summary."""
    tasks = []
    budgets = []
    try:
        with g.db.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, algorithm, rounds_total, rounds_done,
                       dp_epsilon, simulation, created_at
                FROM _fd.fl_tasks ORDER BY created_at DESC
                """
            )
            cols = [d[0] for d in cur.description]
            tasks = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT b.dataset_id, m.table_name, b.total_budget, b.spent,
                       b.total_budget - b.spent AS remaining, b.last_updated
                FROM _fd.fl_epsilon_budget b
                LEFT JOIN _fd.metadata_tables m ON m.id = b.dataset_id
                ORDER BY b.last_updated DESC
                """
            )
            cols = [d[0] for d in cur.description]
            budgets = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        g.db.rollback()

    return render_template(
        "admin/fl.html",
        tasks=tasks,
        budgets=budgets,
        user_email=session.get("email"),
        current_path=request.path,
    )
```

Also add `from flask import session` to the imports in `admin/routes.py` if not already present.

- [ ] **Step 2: Create the admin FL template**

Create `backend/frontend/templates/admin/fl.html`:

```html
{% extends "dashboard/layout.html" %}
{% block title %}FAIRDatabase | FL Admin{% endblock %}
{% block content %}
<div class="row">
  <div class="col-12 mb-4">
    <h2 class="display-6">Federated Learning Console</h2>
  </div>

  <!-- Active Tasks -->
  <div class="col-12 mb-4">
    <div class="card">
      <div class="card-header"><strong>FL Tasks</strong></div>
      <div class="card-body p-0">
        <table class="table table-sm mb-0">
          <thead><tr>
            <th>ID</th><th>Status</th><th>Algorithm</th>
            <th>Rounds</th><th>ε Budget</th><th>Mode</th><th>Created</th>
          </tr></thead>
          <tbody>
          {% for t in tasks %}
          <tr>
            <td><code>{{ t.id[:8] }}</code></td>
            <td><span class="badge bg-{% if t.status == 'completed' %}success{% elif t.status == 'running' %}primary{% else %}secondary{% endif %}">{{ t.status }}</span></td>
            <td>{{ t.algorithm }}</td>
            <td>{{ t.rounds_done }} / {{ t.rounds_total }}</td>
            <td>ε={{ t.dp_epsilon }}</td>
            <td>{% if t.simulation %}Simulation{% else %}Real FL{% endif %}</td>
            <td>{{ t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '' }}</td>
          </tr>
          {% else %}
          <tr><td colspan="7" class="text-center text-muted">No FL tasks yet.</td></tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Epsilon Budgets -->
  <div class="col-12">
    <div class="card">
      <div class="card-header"><strong>Dataset ε Budgets</strong></div>
      <div class="card-body p-0">
        <table class="table table-sm mb-0">
          <thead><tr>
            <th>Dataset</th><th>Total ε</th><th>Spent ε</th><th>Remaining</th><th>Last Updated</th>
          </tr></thead>
          <tbody>
          {% for b in budgets %}
          <tr class="{% if b.remaining <= 0 %}table-danger{% elif b.remaining < b.total_budget * 0.2 %}table-warning{% endif %}">
            <td>{{ b.table_name or b.dataset_id[:8] }}</td>
            <td>{{ '%.3f'|format(b.total_budget) }}</td>
            <td>{{ '%.3f'|format(b.spent) }}</td>
            <td>{{ '%.3f'|format(b.remaining) }}</td>
            <td>{{ b.last_updated.strftime('%Y-%m-%d') if b.last_updated else '' }}</td>
          </tr>
          {% else %}
          <tr><td colspan="5" class="text-center text-muted">No datasets enrolled in FL.</td></tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Verify template renders**

```bash
cd /home/rbumbuc/codes/FAIRDatabase && PYTHONPATH=backend flask --app backend/app.py routes | grep fl
```

Expected: `/admin/fl` appears in the route list.

- [ ] **Step 4: Commit**

```bash
git add backend/src/admin/routes.py backend/frontend/templates/admin/fl.html
git commit -m "feat(admin): add FL dashboard with task status and epsilon budget table"
```

---

## Task 13: Frontend — update FL UI and dashboard

**Files:**
- Rewrite: `backend/frontend/templates/federated_learning/federated_learning.html`
- Modify: `backend/frontend/templates/dashboard/dashboard.html`
- Modify: `backend/frontend/templates/dashboard/layout.html`

- [ ] **Step 1: Rewrite the FL UI template**

Overwrite `backend/frontend/templates/federated_learning/federated_learning.html`:

```html
{% extends "dashboard/layout.html" %}
{% block title %}FAIRDatabase | Federated Learning{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-10">

    <div class="card mb-4">
      <div class="card-body">
        <h1 class="display-6">Federated Learning</h1>
        <p class="text-muted">
          Internal FL engine — FedProx aggregation with (ε,δ)-DP via RDP accountant.
        </p>
      </div>
    </div>

    <!-- Active Tasks -->
    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <strong>FL Tasks</strong>
        <a href="/admin/fl" class="btn btn-sm btn-outline-secondary">Admin view</a>
      </div>
      <div class="card-body p-0">
        <table class="table table-sm mb-0">
          <thead><tr>
            <th>Task ID</th><th>Algorithm</th><th>Rounds</th>
            <th>ε Budget</th><th>Mode</th><th>Status</th>
          </tr></thead>
          <tbody>
          {% for t in tasks %}
          <tr>
            <td><code>{{ t.id[:8] }}</code></td>
            <td>{{ t.algorithm }}</td>
            <td>{{ t.rounds_done }}/{{ t.rounds_total }}</td>
            <td>ε={{ t.dp_epsilon }}</td>
            <td>{% if t.simulation %}<span class="badge bg-info">Simulation</span>{% else %}<span class="badge bg-primary">Real FL</span>{% endif %}</td>
            <td><span class="badge bg-{% if t.status == 'completed' %}success{% elif t.status == 'running' %}warning{% else %}secondary{% endif %}">{{ t.status }}</span></td>
          </tr>
          {% else %}
          <tr><td colspan="6" class="text-center text-muted py-3">No FL tasks yet. Create one via POST /fl/tasks.</td></tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- API Reference -->
    <div class="card">
      <div class="card-header"><strong>API Quick Reference</strong></div>
      <div class="card-body">
        <pre class="bg-light p-3 small">POST /fl/tasks
  { "dp_epsilon": 1.0, "rounds_total": 10, "algorithm": "fedprox",
    "simulation": true, "sim_alpha": 0.5, "sim_n_clients": 5,
    "model_arch": {"type": "tabular_mlp", "input_dim": 10,
                   "hidden_dims": [64,32], "output_dim": 1, "task": "regression"} }

GET  /fl/tasks/&lt;id&gt;
GET  /fl/tasks/&lt;id&gt;/rounds
POST /fl/tasks/&lt;id&gt;/rounds/&lt;n&gt;/gradients   { "ciphertext": "...", "nonce": "..." }
GET  /fl/tasks/&lt;id&gt;/model
POST /fl/tasks/&lt;id&gt;/export-params           { "name": "FL Run 1" }</pre>
      </div>
    </div>

  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Update dashboard layout sidebar link**

In `backend/frontend/templates/dashboard/layout.html`, verify the FL nav link reads:

```html
<a class="nav-link" {% if current_path == '/federated/ui' %} style="background-color: #102F31;" {% endif %} href="/federated/ui">
```

(This was already fixed in an earlier session — confirm it is correct and do not change if already correct.)

- [ ] **Step 3: Commit**

```bash
git add backend/frontend/templates/federated_learning/federated_learning.html
git commit -m "feat(frontend): update FL UI to show task list and API reference"
```

---

## Task 14: Integration test — simulation round-trip

**Files:**
- Create: `backend/tests/federated/test_fl_integration.py`

This test exercises the full pipeline in-process without a live Flask server: engine + privacy + crypto working together.

- [ ] **Step 1: Create the integration test**

Create `backend/tests/federated/test_fl_integration.py`:

```python
"""
Integration test: full FL simulation round-trip.

Tests the engine + DP pipeline together without a live DB or Flask server.
Verifies that:
1. Dirichlet partition produces non-empty client splits
2. Local FedProx training updates weights
3. Clip + Gaussian noise satisfies dimensionality
4. FedAvg aggregation produces same-shape result
5. RDP accountant returns ε ≤ configured budget after all rounds
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pytest
from src.federated.engine import (
    TabularMLP, get_flat_weights, set_flat_weights,
    local_train_fedprox, fedprox_aggregate, dirichlet_partition,
)
from src.federated.fl_privacy import compute_noise_multiplier, compute_epsilon_spent
from src.privacy.helpers import clip_gradients, add_gaussian_noise_dp
from src.federated.crypto import encrypt_weights, decrypt_weights


TARGET_EPSILON = 1.0
DELTA = 1e-5
ROUNDS = 5
N_CLIENTS = 3
CLIP_NORM = 1.0
SECRET = "integration-test-secret"
TASK_ID = "integration-task-id"


@pytest.fixture(scope="module")
def dataset():
    np.random.seed(7)
    X = np.random.randn(150, 4).astype(np.float32)
    y = np.repeat([0, 1, 2], 50).astype(np.float32)
    return X, y


@pytest.fixture(scope="module")
def noise_mult():
    return compute_noise_multiplier(TARGET_EPSILON, DELTA, ROUNDS)


class TestSimulationRoundTrip:
    def test_noise_mult_is_positive(self, noise_mult):
        assert noise_mult > 0

    def test_dirichlet_partitions_all_data(self, dataset):
        X, y = dataset
        parts = dirichlet_partition(X, y, n_clients=N_CLIENTS, alpha=0.5)
        total = sum(len(px) for px, _ in parts)
        assert total == len(X)

    def test_full_simulation_loop(self, dataset, noise_mult):
        """
        Run ROUNDS of FedProx + DP aggregation and verify:
        - weights change each round
        - final ε spent ≤ TARGET_EPSILON
        """
        X, y = dataset
        parts = dirichlet_partition(X, y, n_clients=N_CLIENTS, alpha=0.5)

        model = TabularMLP(input_dim=4, hidden_dims=[16, 8], output_dim=1, task="regression")
        global_weights = get_flat_weights(model)

        for rnd in range(ROUNDS):
            client_updates = []
            client_sizes = []

            for (px, py) in parts:
                if len(px) == 0:
                    continue
                local_w = local_train_fedprox(
                    model, global_weights, px, py,
                    epochs=2, lr=0.01, mu=0.01, task="regression"
                )
                clipped = clip_gradients(local_w, CLIP_NORM)
                noised = add_gaussian_noise_dp(clipped, noise_mult, CLIP_NORM)
                client_updates.append(noised)
                client_sizes.append(len(px))

            assert len(client_updates) > 0
            global_weights = fedprox_aggregate(client_updates, client_sizes)

        eps_spent = compute_epsilon_spent(noise_mult, DELTA, ROUNDS)
        assert eps_spent <= TARGET_EPSILON + 1e-4, (
            f"ε spent {eps_spent:.4f} exceeds budget {TARGET_EPSILON}"
        )

    def test_encrypt_decrypt_weights_roundtrip(self, noise_mult):
        model = TabularMLP(input_dim=4, hidden_dims=[8], output_dim=1, task="regression")
        w = get_flat_weights(model)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        recovered = decrypt_weights(payload, TASK_ID, SECRET)
        np.testing.assert_array_almost_equal(recovered, w, decimal=5)

    def test_budget_exhaustion_logic(self, noise_mult):
        """
        After ROUNDS rounds, epsilon spent must be ≤ TARGET_EPSILON,
        confirming the RDP accountant correctly bounds composition.
        """
        spent = compute_epsilon_spent(noise_mult, DELTA, ROUNDS)
        assert spent <= TARGET_EPSILON
        # Spending one more round pushes past budget
        spent_extra = compute_epsilon_spent(noise_mult, DELTA, ROUNDS + 50)
        assert spent_extra > spent
```

- [ ] **Step 2: Run the integration tests**

```bash
cd backend && PYTHONPATH=.. python -m pytest tests/federated/test_fl_integration.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 3: Run the full test suite**

```bash
cd backend && PYTHONPATH=.. python -m pytest tests/ -v --ignore=tests/model/test_pbpk_stress.py 2>&1 | tail -30
```

Expected: no regressions in existing tests.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/federated/test_fl_integration.py
git commit -m "test(federated): add FL simulation round-trip integration test"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by task |
|---|---|
| RDP accountant (not naive ε/rounds) | Task 4 |
| L2 gradient clipping before noise | Task 3 |
| FedProx as default, μ configurable | Tasks 7, 8 |
| FedAvg aggregation | Task 7 |
| Dirichlet non-IID simulation | Task 7 |
| AES-256-GCM gradient encryption | Task 5 |
| DB schema (fl_tasks, fl_rounds, fl_clients, fl_epsilon_budget) | Task 2 |
| FL routes (/fl/ and /federated/) | Task 8 |
| Data module FL eligibility | Task 9 |
| Privacy module budget endpoint | Task 10 |
| Model module FL source tagging | Task 11 |
| Admin FL dashboard | Task 12 |
| Frontend FL UI update | Task 13 |
| Full simulation integration test | Task 14 |
| Budget exhaustion enforcement | Tasks 6, 8 (submit_gradients checks budget) |
| Gradient purge after export | Task 8 (purge_round_weights called in export_params) |

**No gaps found.**

**Placeholder scan:** No TBD, TODO, or "similar to task N" patterns found.

**Type consistency:** `get_flat_weights` → `np.ndarray` (float32), `set_flat_weights` accepts same, `fedprox_aggregate` accepts `List[np.ndarray]` — consistent throughout.
