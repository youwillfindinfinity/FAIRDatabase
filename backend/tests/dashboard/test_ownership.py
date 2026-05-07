"""Ownership enforcement: curator A must not be able to mutate curator B's
datasets. Tests the ``filter_owned_tables`` and ``assert_can_modify_table``
helpers directly using an in-memory cursor stub.
"""

import uuid
import pytest

from src.dashboard.helpers import (
    assert_can_modify_table,
    filter_owned_tables,
)


class FakeCursor:
    """Minimal cursor stub that answers queries against an in-memory list of
    ``(table_name, owner_id)`` rows. Supports the two query shapes used by the
    helpers under test.
    """

    def __init__(self, rows):
        self._rows = rows
        self._result = []

    def execute(self, sql, params=()):
        sql_l = sql.lower()
        if "table_name = any" in sql_l:
            owner_id, table_list = params
            self._result = [
                (t,) for (t, oid) in self._rows
                if oid == owner_id and t in table_list
            ]
        elif "limit 1" in sql_l:
            table_name, owner_id = params
            self._result = [
                (1,) for (t, oid) in self._rows
                if t == table_name and oid == owner_id
            ]
        else:
            self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


class TestFilterOwnedTables:
    def setup_method(self):
        self.alice = str(uuid.uuid4())
        self.bob = str(uuid.uuid4())
        self.cur = FakeCursor([
            ("alice_t1", self.alice),
            ("alice_t2", self.alice),
            ("bob_t1", self.bob),
        ])
        self.all_tables = ["alice_t1", "alice_t2", "bob_t1"]

    def test_admin_sees_everything(self):
        out = filter_owned_tables(self.cur, self.all_tables, self.alice, "admin")
        assert sorted(out) == sorted(self.all_tables)

    def test_curator_sees_only_own(self):
        out = filter_owned_tables(self.cur, self.all_tables, self.alice, "curator")
        assert sorted(out) == ["alice_t1", "alice_t2"]

    def test_other_curator_does_not_see_alice_tables(self):
        out = filter_owned_tables(self.cur, self.all_tables, self.bob, "curator")
        assert out == ["bob_t1"]

    def test_visualizer_gets_nothing(self):
        out = filter_owned_tables(self.cur, self.all_tables, self.alice, "visualizer")
        assert out == []

    def test_accessor_gets_nothing(self):
        out = filter_owned_tables(self.cur, self.all_tables, self.alice, "accessor")
        assert out == []

    def test_no_user_id_gets_nothing(self):
        out = filter_owned_tables(self.cur, self.all_tables, None, "curator")
        assert out == []


class TestAssertCanModify:
    def setup_method(self):
        self.alice = str(uuid.uuid4())
        self.bob = str(uuid.uuid4())
        self.cur = FakeCursor([
            ("alice_t1", self.alice),
            ("bob_t1", self.bob),
        ])

    def test_admin_can_modify_anything(self):
        assert_can_modify_table(self.cur, "bob_t1", self.alice, "admin")

    def test_curator_can_modify_own(self):
        assert_can_modify_table(self.cur, "alice_t1", self.alice, "curator")

    def test_curator_cannot_modify_other(self):
        with pytest.raises(PermissionError):
            assert_can_modify_table(self.cur, "bob_t1", self.alice, "curator")

    def test_visualizer_cannot_modify(self):
        with pytest.raises(PermissionError):
            assert_can_modify_table(self.cur, "alice_t1", self.alice, "visualizer")

    def test_accessor_cannot_modify(self):
        with pytest.raises(PermissionError):
            assert_can_modify_table(self.cur, "alice_t1", self.alice, "accessor")
