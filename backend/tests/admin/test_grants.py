"""Grant lifecycle: admin/owner-curator can grant, then revoke; non-owner
curator gets a Forbidden response.

The handler under test (`GrantsHandler`) is exercised against an in-memory
fake DB to avoid coupling these tests to the live schema.
"""

import uuid
import pytest
from unittest.mock import patch

from src.admin import form as admin_form


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._result = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        s = " ".join(sql.lower().split())
        self._result = []
        self.rowcount = 0
        if "from _fd.metadata_tables where id" in s:
            ds = self.store["datasets"].get(params[0])
            self._result = [ds] if ds else []
        elif "from _fd.dataset_grants where dataset_id" in s and "select" in s:
            ds_id = params[0]
            self._result = [
                (uid, by, at)
                for (did, uid, by, at) in self.store["grants"]
                if did == ds_id
            ]
        elif "insert into _fd.dataset_grants" in s:
            ds_id, uid, by = params
            if not any(d == ds_id and u == uid for (d, u, _, _) in self.store["grants"]):
                self.store["grants"].append((ds_id, uid, by, "now"))
        elif "delete from _fd.dataset_grants" in s:
            ds_id, uid = params
            before = len(self.store["grants"])
            self.store["grants"] = [
                row for row in self.store["grants"]
                if not (row[0] == ds_id and row[1] == uid)
            ]
            self.rowcount = before - len(self.store["grants"])
        elif "insert into _fd.grant_audit" in s:
            self.store["audit"].append(params)
        elif "insert into _fd.role_audit" in s:
            self.store["role_audit"].append(params)

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeDB:
    def __init__(self, store):
        self.store = store
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


@pytest.fixture
def fake_session():
    """Patch flask.session and flask.g access used inside the handlers."""
    s = {"user": str(uuid.uuid4()), "email": "actor@test.com"}
    with patch.object(admin_form, "session", s):
        yield s


@pytest.fixture
def fake_g():
    class _G:
        pass
    g = _G()
    with patch.object(admin_form, "g", g):
        yield g


@pytest.fixture
def store(fake_session):
    """Seed an admin-owned dataset and an empty grants table."""
    owner = str(uuid.uuid4())
    return {
        "datasets": {
            1: (1, "tbl_a", "tbl", owner),
            2: (2, "tbl_b", "tbl", str(uuid.uuid4())),
        },
        "grants": [],
        "audit": [],
        "role_audit": [],
        "owner_a": owner,
    }


@pytest.fixture
def fake_db(store, monkeypatch):
    db = FakeDB(store)
    monkeypatch.setattr(admin_form, "get_db", lambda: db)
    monkeypatch.setattr(admin_form, "_list_supabase_users", lambda: [])
    return db


class TestGrantsLifecycle:
    def test_admin_grants_then_revokes(self, fake_db, store, fake_g):
        fake_g.role = "admin"
        fake_g.user = "irrelevant-admin-id"

        target = str(uuid.uuid4())
        ok, _ = admin_form.GrantsHandler(1).grant(target)
        assert ok
        assert any(u == target for (_d, u, _b, _at) in store["grants"])
        assert store["audit"][-1][2] == "granted"

        ok, _ = admin_form.GrantsHandler(1).revoke(target)
        assert ok
        assert not any(u == target for (_d, u, _b, _at) in store["grants"])
        assert store["audit"][-1][2] == "revoked"

    def test_owner_curator_can_grant(self, fake_db, store, fake_g):
        fake_g.role = "curator"
        fake_g.user = store["owner_a"]
        ok, _ = admin_form.GrantsHandler(1).grant(str(uuid.uuid4()))
        assert ok

    def test_non_owner_curator_forbidden(self, fake_db, store, fake_g):
        fake_g.role = "curator"
        fake_g.user = str(uuid.uuid4())  # not owner of dataset 1
        ok, msg = admin_form.GrantsHandler(1).grant(str(uuid.uuid4()))
        assert not ok
        assert "forbidden" in msg.lower()

    def test_visualizer_cannot_grant(self, fake_db, store, fake_g):
        fake_g.role = "visualizer"
        fake_g.user = str(uuid.uuid4())
        ok, _ = admin_form.GrantsHandler(1).grant(str(uuid.uuid4()))
        assert not ok

    def test_revoke_is_idempotent(self, fake_db, store, fake_g):
        fake_g.role = "admin"
        fake_g.user = "admin-id"
        target = str(uuid.uuid4())
        admin_form.GrantsHandler(1).grant(target)
        admin_form.GrantsHandler(1).revoke(target)
        ok, _ = admin_form.GrantsHandler(1).revoke(target)  # already gone
        assert ok  # delete on missing row still commits, no audit row added

    def test_missing_target_user_rejected(self, fake_db, store, fake_g):
        fake_g.role = "admin"
        fake_g.user = "admin-id"
        ok, msg = admin_form.GrantsHandler(1).grant("")
        assert not ok
        assert "missing" in msg.lower()
