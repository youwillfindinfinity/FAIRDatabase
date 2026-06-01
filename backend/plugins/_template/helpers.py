"""Pure helpers for the example plugin.

No Flask globals here (no ``g``, no ``request``, no ``session``) — this module
must be unit-testable without an app context. See docs/PLUGIN_GUIDE.md §4.
"""


def serialize_run(row):
    """Turn an (id, label, params, created_at) DB row into a JSON-ready dict."""
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "label": row[1],
        "params": row[2],
        "created_at": row[3].isoformat() if row[3] is not None else None,
    }
