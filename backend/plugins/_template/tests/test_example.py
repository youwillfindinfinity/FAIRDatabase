"""Tests for the example plugin — the four coverages required by
docs/PLUGIN_GUIDE.md §8. Picked up by the project pytest.

These are skeletons: they document the required shape. Replace the bodies and
drop ``@pytest.mark.skip`` once your plugin has tables and an app fixture.
Anything that takes > 1s must be marked ``@pytest.mark.slow``.
"""
import pytest

ROLES = ("admin", "curator", "accessor", "visualizer")

# Roles that a 2xx is expected for, per route. Mirrors the @login_required
# decorators in routes.py. Keep in sync.
ALLOWED = {
    "create_run": {"admin", "curator"},
    "get_run": set(ROLES),
    "list_runs": set(ROLES),
    "delete_run": {"admin", "curator"},
}


@pytest.mark.skip(reason="template skeleton — implement against your app fixture")
@pytest.mark.parametrize("role", ROLES)
def test_rbac_matrix(role):
    """1. RBAC matrix — each route hit as each role; only declared roles get
    2xx, every other role gets 403."""
    # for route, allowed in ALLOWED.items():
    #     resp = call_route_as(role, route)
    #     assert (resp.status_code < 300) == (role in allowed)
    raise NotImplementedError


@pytest.mark.skip(reason="template skeleton — implement against your app fixture")
def test_mutation_writes_audit_row():
    """2. Audit — every mutation produces a row in _fd.plugin_audit."""
    # create a run, then assert one _fd.plugin_audit row with action='create'
    raise NotImplementedError


@pytest.mark.skip(reason="template skeleton — implement against your app fixture")
def test_schema_migration_is_idempotent():
    """3. Schema idempotency — applying sql/001_schema.sql twice is a no-op."""
    # apply the file twice in one connection; second pass must not error
    raise NotImplementedError


@pytest.mark.skip(reason="template skeleton — implement against your app fixture")
def test_delete_path_removes_row_and_blob():
    """4. Delete path — deleting a resource removes the row (and any blob)."""
    # create a run, DELETE it, assert the row is gone (and bucket object too,
    # if the plugin uploads artifacts)
    raise NotImplementedError
