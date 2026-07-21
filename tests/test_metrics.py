"""Unit tests for Algorithm 1 (execution match) and SQL execution."""

import sqlite3

import pytest

from archer_eval.execution import ExecutionResult, execute_sql
from archer_eval.metrics import execution_match, has_outermost_order_by


def res(rows, n_cols=None):
    rows = [tuple(r) for r in rows]
    if n_cols is None:
        n_cols = len(rows[0]) if rows else 0
    return ExecutionResult(ok=True, rows=rows, n_cols=n_cols)


NO_ORDER = "SELECT a, b FROM t"
WITH_ORDER = "SELECT a, b FROM t ORDER BY a"


class TestOutermostOrderBy:
    def test_plain(self):
        assert has_outermost_order_by("SELECT * FROM t ORDER BY x")

    def test_absent(self):
        assert not has_outermost_order_by("SELECT * FROM t")

    def test_only_in_subquery(self):
        sql = "SELECT * FROM (SELECT * FROM t ORDER BY x) sub"
        assert not has_outermost_order_by(sql)

    def test_in_string_literal(self):
        assert not has_outermost_order_by("SELECT * FROM t WHERE name = 'ORDER BY x'")

    def test_after_union(self):
        assert has_outermost_order_by("SELECT a FROM t UNION SELECT a FROM u ORDER BY a")

    def test_case_insensitive(self):
        assert has_outermost_order_by("select * from t order   by x")


class TestExecutionMatch:
    def test_exact_match(self):
        assert execution_match(res([(1, "a"), (2, "b")]), res([(1, "a"), (2, "b")]), NO_ORDER)

    def test_different_values(self):
        assert not execution_match(res([(1, "a")]), res([(1, "b")]), NO_ORDER)

    def test_shape_mismatch(self):
        assert not execution_match(res([(1,)]), res([(1,), (2,)]), NO_ORDER)
        assert not execution_match(res([(1,)]), res([(1, 2)]), NO_ORDER)

    def test_row_permutation_without_order_by(self):
        assert execution_match(res([(2, "b"), (1, "a")]), res([(1, "a"), (2, "b")]), NO_ORDER)

    def test_column_permutation_without_order_by(self):
        assert execution_match(res([("a", 1), ("b", 2)]), res([(1, "a"), (2, "b")]), NO_ORDER)

    def test_row_permutation_with_order_by_fails(self):
        assert not execution_match(res([(2, "b"), (1, "a")]), res([(1, "a"), (2, "b")]), WITH_ORDER)

    def test_column_permutation_with_order_by_ok(self):
        assert execution_match(res([("a", 1), ("b", 2)]), res([(1, "a"), (2, "b")]), WITH_ORDER)

    def test_float_tolerance(self):
        assert execution_match(res([(0.30000000000000004,)]), res([(0.3,)]), NO_ORDER)

    def test_failed_execution_never_matches(self):
        bad = ExecutionResult(ok=False, error="syntax error")
        assert not execution_match(bad, res([(1,)]), NO_ORDER)

    def test_empty_results_match(self):
        assert execution_match(res([], 1), res([], 1), NO_ORDER)


class TestExecuteSql:
    @pytest.fixture()
    def db(self, tmp_path):
        path = tmp_path / "test.sqlite"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)", [(1, "x"), (2, "y")])
        conn.commit()
        conn.close()
        return path

    def test_select(self, db):
        r = execute_sql(db, "SELECT a, b FROM t ORDER BY a")
        assert r.ok and r.rows == [(1, "x"), (2, "y")] and r.n_cols == 2

    def test_invalid_sql(self, db):
        r = execute_sql(db, "SELEC nonsense")
        assert not r.ok and r.error

    def test_write_rejected_readonly(self, db):
        r = execute_sql(db, "DROP TABLE t")
        assert not r.ok
        # table must still exist afterwards
        assert execute_sql(db, "SELECT count(*) FROM t").ok

    def test_missing_db(self, tmp_path):
        r = execute_sql(tmp_path / "nope.sqlite", "SELECT 1")
        assert not r.ok
