"""Demo-specific data helpers."""

import os
from contextlib import contextmanager
import psycopg2
from flask import current_app


def get_db_connection():
    """Create a connection to the demo database."""
    return psycopg2.connect(
        host=current_app.config["POSTGRES_HOST"],
        port=current_app.config["POSTGRES_PORT"],
        user=current_app.config["POSTGRES_USER"],
        password=current_app.config["POSTGRES_SECRET"],
        database=current_app.config["POSTGRES_DB_NAME"],
    )


@contextmanager
def get_db_cursor():
    """Context manager for database cursor."""
    conn = get_db_connection()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()


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

    with get_db_cursor() as cur:
        cur.execute("""
            SELECT {group_by}, {measure}
            FROM _demo.query_results
            WHERE dataset = %s
            ORDER BY {group_by}
        """.format(group_by=group_by, measure=measure), (dataset,))

        return [{"group": row[0], "value": row[1]} for row in cur.fetchall()]