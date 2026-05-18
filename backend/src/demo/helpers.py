"""Demo-specific data helpers."""

from contextlib import contextmanager
from psycopg2 import sql
from flask import g


@contextmanager
def get_db_cursor():
    """Yield a cursor on the per-request connection (``g.db``).

    Uses the same request-scoped connection as the rest of the app instead of
    opening a private psycopg2 connection. Demo endpoints are read-only, so no
    commit is issued; an aborted transaction is rolled back so a later handler
    on the same request keeps a clean connection. Closing is handled by the
    app-wide ``teardown_db``.
    """
    cur = g.db.cursor()
    try:
        yield cur
    except Exception:
        g.db.rollback()
        raise
    finally:
        cur.close()


def get_demo_datasets():
    """Fetch list of demo datasets with metadata."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, name, organ, cohort, sample_count, created_at
            FROM _demo.datasets
            ORDER BY created_at DESC
        """)
        return [
            {
                "id": row[0],
                "name": row[1],
                "organ": row[2],
                "cohort": row[3],
                "sample_count": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
            }
            for row in cur.fetchall()
        ]


def get_demo_query_results(dataset, group_by, measure):
    """Execute demo query with strict parameter validation."""
    allowed_datasets = ["gut_microbiome", "oral_microbiome", "skin_microbiome"]
    allowed_group_by = ["organism", "taxonomy_id", "sample_type"]
    allowed_measures = ["abundance", "diversity", "richness"]

    if dataset not in allowed_datasets:
        raise ValueError(f"Invalid dataset: {dataset}")
    if group_by not in allowed_group_by:
        raise ValueError(f"Invalid group_by: {group_by}")
    if measure not in allowed_measures:
        raise ValueError(f"Invalid measure: {measure}")

    # Identifiers are allow-listed above (defense in depth); compose them with
    # psycopg2.sql.Identifier so they are always safely quoted and can never
    # be string-interpolated into the statement, even if the allow-lists are
    # later widened or this helper is copied for another module.
    query = sql.SQL(
        """
        SELECT {group_by}, {measure}
        FROM _demo.query_results
        WHERE dataset = %s
        ORDER BY {group_by}
        """
    ).format(
        group_by=sql.Identifier(group_by),
        measure=sql.Identifier(measure),
    )

    with get_db_cursor() as cur:
        cur.execute(query, (dataset,))
        return [{"group": row[0], "value": row[1]} for row in cur.fetchall()]