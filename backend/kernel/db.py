"""Database access helpers for plugins. See ``docs/PLUGIN_GUIDE.md`` §2.

A plugin gets its request-scoped connection from ``g.db`` directly. This
module adds safe-quoting and dataset-lookup helpers on top.
"""
import pandas as pd
from flask import g
from psycopg2 import sql

from src.dashboard.helpers import _clean_identifier as clean_identifier

__all__ = ["clean_identifier", "sql", "metadata_table_id", "read_dataset"]


def metadata_table_id(table_name):
    """Return the ``_fd.metadata_tables.id`` for ``table_name``, or ``None``.

    Resolves a user-facing dataset name to its catalog id — typically the step
    before an RBAC check. Reads ``g.db``.
    """
    with g.db.cursor() as cur:
        cur.execute(
            "SELECT id FROM _fd.metadata_tables WHERE table_name = %s LIMIT 1",
            (table_name,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def read_dataset(table_name):
    """Return the rows of dataset ``table_name`` as a pandas DataFrame.

    Reads the physical data table in the ``_fd`` schema. This performs **no**
    authorization — you MUST call ``kernel.rbac.assert_can_read_table`` (or
    ``filter_readable_tables``) first. See ``docs/PLUGIN_GUIDE.md`` §3.
    """
    table_ident = sql.Identifier("_fd", clean_identifier(table_name))
    query = sql.SQL("SELECT * FROM {}").format(table_ident)
    with g.db.cursor() as cur:
        cur.execute(query)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)
