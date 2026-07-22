"""Execution match check — Algorithm 1 from the Archer paper (Appendix B).

Given the execution results of a predicted SQL (pred) and a gold SQL (gold)
against the same database:

1. pred fails to execute            -> no match (and VA = 0, handled upstream)
2. results exactly equal            -> match
3. row count or col count differ    -> no match
4. gold has an outermost ORDER BY   -> compare the *multiset of columns*
   (row order is fixed by ORDER BY, but column order may be permuted)
5. otherwise                        -> compare element frequencies of every
   row and every column (tolerates both row and column permutations)

`result_similarity` turns that pass/fail verdict into a [0, 1] score, so a
near-miss can be told apart from a wholly wrong answer in the report.
"""

from __future__ import annotations

from collections import Counter

from config import FLOAT_PRECISION

from archer_eval.execution import ExecutionResult


def _norm(value):
    """Normalize a cell value for comparison (round floats to absorb fp noise)."""
    if isinstance(value, float):
        return round(value, FLOAT_PRECISION)
    return value


def _norm_rows(rows: list[tuple]) -> list[tuple]:
    return [tuple(_norm(v) for v in row) for row in rows]


def _columns(rows: list[tuple], n_cols: int) -> list[tuple]:
    return [tuple(row[i] for row in rows) for i in range(n_cols)]


def _signature(vectors: list[tuple]) -> Counter:
    """Multiset of per-vector element frequencies — blind to element order."""
    return Counter(frozenset(Counter(vec).items()) for vec in vectors)


def _jaccard(a: Counter, b: Counter) -> float:
    """Multiset Jaccard: |a & b| / |a | b|; two empty multisets count as equal."""
    union = sum((a | b).values())
    return sum((a & b).values()) / union if union else 1.0


def has_outermost_order_by(sql: str) -> bool:
    """True if `sql` has an ORDER BY clause at parenthesis depth 0.

    String literals are skipped so an ORDER BY inside a quoted string or a
    subquery does not count; one after a top-level UNION/INTERSECT does.
    """
    tokens = []
    depth = 0
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"', "`"):
            quote = c
            i += 1
            while i < n:
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:  # escaped '' inside string
                        i += 2
                        continue
                    break
                i += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and (c.isalpha() or c == "_"):
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            tokens.append(sql[i:j].lower())
            i = j
            continue
        i += 1

    return any(a == "order" and b == "by" for a, b in zip(tokens, tokens[1:]))


def execution_match(pred: ExecutionResult, gold: ExecutionResult, gold_sql: str) -> bool:
    if not pred.ok or not gold.ok:
        return False

    pred_rows = _norm_rows(pred.rows)
    gold_rows = _norm_rows(gold.rows)

    if pred_rows == gold_rows and pred.n_cols == gold.n_cols:
        return True

    if pred.n_rows != gold.n_rows or pred.n_cols != gold.n_cols:
        return False

    if has_outermost_order_by(gold_sql):
        pred_cols = Counter(_columns(pred_rows, pred.n_cols))
        gold_cols = Counter(_columns(gold_rows, gold.n_cols))
        return pred_cols == gold_cols

    rows_match = _signature(pred_rows) == _signature(gold_rows)
    cols_match = _signature(_columns(pred_rows, pred.n_cols)) == _signature(
        _columns(gold_rows, gold.n_cols)
    )
    return rows_match and cols_match


def result_similarity(pred: ExecutionResult, gold: ExecutionResult) -> tuple[float, float]:
    """How close pred's result set is to gold's, as (row_sim, col_sim) in [0, 1].

    Continuous counterpart of `execution_match`, built on the same frequency
    signatures, so the two agree: a match always scores 1.0 on both. The
    converse holds except when gold has an outermost ORDER BY — that branch
    compares exact columns, which is stricter than the signature.

    Either side failing to execute scores 0.0; differing shapes need no special
    case, the Jaccard drops on its own.
    """
    if not pred.ok or not gold.ok:
        return 0.0, 0.0

    pred_rows = _norm_rows(pred.rows)
    gold_rows = _norm_rows(gold.rows)
    row_sim = _jaccard(_signature(pred_rows), _signature(gold_rows))
    col_sim = _jaccard(
        _signature(_columns(pred_rows, pred.n_cols)),
        _signature(_columns(gold_rows, gold.n_cols)),
    )
    return round(row_sim, 4), round(col_sim, 4)
