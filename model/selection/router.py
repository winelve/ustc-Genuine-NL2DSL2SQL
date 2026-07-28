"""Deterministic, gold-free routing for Direct and DSL SQL candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import sqlglot

from archer_eval.execution import ExecutionResult, execute_sql
from bird.evaluate import rows_match


@dataclass(frozen=True)
class ExecutionSummary:
    ok: bool
    n_rows: int | None
    n_cols: int | None
    error: str | None

    @classmethod
    def from_result(cls, result: ExecutionResult) -> "ExecutionSummary":
        return cls(
            ok=result.ok,
            n_rows=result.n_rows if result.ok else None,
            n_cols=result.n_cols if result.ok else None,
            error=result.error,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RouteDecision:
    route: str
    winner: str | None
    direct: ExecutionSummary | None = None
    dsl: ExecutionSummary | None = None


def normalize_sql(sql: str) -> str:
    """Canonicalize valid SQLite without changing quoted literal values."""
    try:
        return sqlglot.parse_one(sql.strip().rstrip(";"), read="sqlite").sql(
            dialect="sqlite",
            normalize=True,
            pretty=False,
            unsupported_level=sqlglot.ErrorLevel.IGNORE,
        )
    except Exception:
        return " ".join(sql.strip().rstrip(";").split())


def route_candidates(
    direct_sql: str,
    dsl_sql: str,
    db_path: str | Path,
) -> RouteDecision:
    """Choose deterministic cases and reserve real disagreements for a judge."""
    if normalize_sql(direct_sql) == normalize_sql(dsl_sql):
        return RouteDecision(route="same_sql", winner="dsl")

    direct_result = execute_sql(db_path, direct_sql)
    dsl_result = execute_sql(db_path, dsl_sql)
    direct = ExecutionSummary.from_result(direct_result)
    dsl = ExecutionSummary.from_result(dsl_result)

    if direct_result.ok and dsl_result.ok:
        if rows_match(direct_result.rows, dsl_result.rows):
            return RouteDecision("same_result", "dsl", direct, dsl)
        return RouteDecision("pairwise", None, direct, dsl)
    if direct_result.ok:
        return RouteDecision("direct_only_valid", "direct", direct, dsl)
    if dsl_result.ok:
        return RouteDecision("dsl_only_valid", "dsl", direct, dsl)
    return RouteDecision("both_invalid", "dsl", direct, dsl)
