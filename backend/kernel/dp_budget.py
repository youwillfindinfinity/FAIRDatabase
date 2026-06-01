"""DP epsilon-budget ledger. See ``docs/PLUGIN_GUIDE.md`` §2.

A per-dataset differential-privacy budget: how much ε a dataset may spend
across all DP operations, and how much it has spent so far.

This is **kernel**, not FL-plugin code: it is consumed both by core routes
(``src/privacy`` exposes the remaining budget, ``src/data`` enrols datasets)
and by FL plugins, and ``enroll_dataset`` writes ``_fd.metadata_tables`` —
a core table no plugin may touch. Relocated from ``src/federated/db.py`` in
migration plan Phase 5.

Every function takes a psycopg2 connection and operates within the caller's
transaction. Backed by ``_fd.fl_epsilon_budget`` (kernel/sql/002_dp_budget.sql).
"""
from typing import Optional

__all__ = [
    "get_epsilon_budget",
    "consume_epsilon",
    "consume_epsilon_guarded",
    "enroll_dataset",
    "list_fl_eligible_datasets",
]


def get_epsilon_budget(conn, dataset_id: str) -> Optional[dict]:
    """Return the budget row for ``dataset_id`` as a dict, or None."""
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
    """Deduct ``amount`` from the budget and update the timestamp."""
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
    submissions for the same dataset cannot both pass the check and overspend.

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
    """Return all datasets flagged ``fl_eligible``."""
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
