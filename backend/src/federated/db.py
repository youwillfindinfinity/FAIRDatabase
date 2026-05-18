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
                sim_n_clients: int, model_arch: dict, created_by: Optional[str],
                dataset_id: Optional[str] = None) -> str:
    """Insert a new FL task and return its UUID."""
    task_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO _fd.fl_tasks
                (id, algorithm, rounds_total, mu, dp_epsilon, dp_delta,
                 dp_noise_mult, dp_clip_norm, simulation, sim_alpha,
                 sim_n_clients, model_arch, created_by, dataset_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (task_id, algorithm, rounds_total, mu, dp_epsilon, dp_delta,
             dp_noise_mult, dp_clip_norm, simulation, sim_alpha,
             sim_n_clients, json.dumps(model_arch), created_by, dataset_id),
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


def register_round_submission(
    conn, task_id: str, round_n: int, client_key: str
) -> bool:
    """Record a client's submission for a round.

    Returns ``True`` if this is the client's first submission for the round,
    ``False`` if the client already submitted (UNIQUE conflict) — letting the
    caller reject duplicates so one client cannot inflate the round count.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO _fd.fl_round_submissions (task_id, round_n, client_key)
            VALUES (%s, %s, %s)
            ON CONFLICT (task_id, round_n, client_key) DO NOTHING
            RETURNING id
            """,
            (task_id, round_n, client_key),
        )
        inserted = cur.fetchone() is not None
    conn.commit()
    return inserted


def count_round_submissions(conn, task_id: str, round_n: int) -> int:
    """Number of distinct clients that have submitted for this round."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM _fd.fl_round_submissions "
            "WHERE task_id=%s AND round_n=%s",
            (task_id, round_n),
        )
        return int(cur.fetchone()[0])


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


def consume_epsilon_guarded(conn, dataset_id: str, amount: float) -> bool:
    """Atomically check-and-consume epsilon budget under a row lock.

    Locks the budget row with ``SELECT ... FOR UPDATE`` so concurrent
    submissions for the same dataset cannot both pass the check and overspend
    (the unguarded check-then-act in submit_gradients had a TOCTOU race).

    Returns ``True`` if the amount was consumed (or no budget row exists, i.e.
    enforcement not configured), ``False`` if the budget is exhausted — in
    which case nothing is deducted.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT spent, total_budget FROM _fd.fl_epsilon_budget "
            "WHERE dataset_id = %s FOR UPDATE",
            (dataset_id,),
        )
        row = cur.fetchone()
        if row is None:
            conn.commit()
            return True
        spent, total_budget = row
        if spent >= total_budget:
            conn.commit()
            return False
        cur.execute(
            """
            UPDATE _fd.fl_epsilon_budget
            SET spent = spent + %s, last_updated = NOW()
            WHERE dataset_id = %s
            """,
            (amount, dataset_id),
        )
    conn.commit()
    return True


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
