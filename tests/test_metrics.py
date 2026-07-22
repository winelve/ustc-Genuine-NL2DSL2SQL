"""Unit tests for Algorithm 1 (execution match) and SQL execution."""

import sqlite3

import pytest

from archer_eval.execution import ExecutionResult, execute_sql
from archer_eval.metrics import execution_match, has_outermost_order_by, result_similarity


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


class TestResultSimilarity:
    def test_identical(self):
        assert result_similarity(res([(1, "a"), (2, "b")]), res([(1, "a"), (2, "b")])) == (1.0, 1.0)

    def test_permutations_are_free(self):
        assert result_similarity(res([("a", 1), ("b", 2)]), res([(1, "a"), (2, "b")])) == (1.0, 1.0)

    def test_nothing_in_common(self):
        assert result_similarity(res([(1,)]), res([(2,)])) == (0.0, 0.0)

    def test_partial_row_overlap(self):
        row_sim, _ = result_similarity(res([(1,), (2,)]), res([(1,), (3,)]))
        assert row_sim == pytest.approx(1 / 3, abs=1e-4)  # 1 shared row out of 3

    def test_extra_row_lowers_score_without_a_shape_special_case(self):
        row_sim, col_sim = result_similarity(res([(1,), (2,), (3,)]), res([(1,), (2,)]))
        assert row_sim == pytest.approx(2 / 3, abs=1e-4)
        assert col_sim == 0.0  # the single column differs as a whole

    def test_float_tolerance(self):
        assert result_similarity(res([(0.30000000000000004,)]), res([(0.3,)])) == (1.0, 1.0)

    def test_failed_execution_scores_zero(self):
        bad = ExecutionResult(ok=False, error="syntax error")
        assert result_similarity(bad, res([(1,)])) == (0.0, 0.0)

    def test_empty_results_are_identical(self):
        assert result_similarity(res([], 1), res([], 1)) == (1.0, 1.0)

    @pytest.mark.parametrize(
        "pred, gold, gold_sql",
        [
            (res([(1, "a"), (2, "b")]), res([(1, "a"), (2, "b")]), NO_ORDER),
            (res([(2, "b"), (1, "a")]), res([(1, "a"), (2, "b")]), NO_ORDER),
            (res([("a", 1), ("b", 2)]), res([(1, "a"), (2, "b")]), NO_ORDER),
            (res([("a", 1), ("b", 2)]), res([(1, "a"), (2, "b")]), WITH_ORDER),
        ],
    )
    def test_a_match_always_scores_one(self, pred, gold, gold_sql):
        """相似度与 Algorithm 1 同源：判 match 的一定满分。"""
        assert execution_match(pred, gold, gold_sql)
        assert result_similarity(pred, gold) == (1.0, 1.0)


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
