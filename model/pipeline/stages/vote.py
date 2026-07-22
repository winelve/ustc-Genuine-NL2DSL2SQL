"""执行淘汰 + 多数投票：候选 SQL 只读执行，按结果分组，最大组胜出。

结果相等的口径与评测器同源（archer_eval.metrics 的单元格规范化）：
行序不敏感、浮点按 FLOAT_PRECISION 归一。列序视为有意义——同一意图的
候选列序几乎总一致，不值得为此放宽。
"""

from __future__ import annotations

from collections import Counter

from archer_eval.execution import ExecutionResult, execute_sql
from archer_eval.metrics import _norm_rows
from model.pipeline.context import PipelineContext


def _result_key(result: ExecutionResult):
    """执行结果的分组键：列数 + 规范化行的多重集（行序不敏感）。"""
    return result.n_cols, frozenset(Counter(_norm_rows(result.rows)).items())


def pick_winner(results: list[ExecutionResult]) -> int:
    """返回胜出候选的下标。

    只有执行成功的候选参与投票；同结果为一组，最大组获胜，平票取最早出现
    的组；组内取最早的候选。全部失败时返回最后一条候选的下标（返回它的 SQL
    比返回空串信息量大，VA 反正都是 0）。
    """
    groups: dict = {}  # key -> [候选下标...]
    for i, result in enumerate(results):
        if result.ok:
            groups.setdefault(_result_key(result), []).append(i)
    if not groups:
        return len(results) - 1
    best = max(groups.values(), key=lambda idx: (len(idx), -idx[0]))
    return best[0]


class VoteStage:
    def run(self, ctx: PipelineContext) -> None:
        if not ctx.candidates:
            return
        results = [execute_sql(ctx.db_path, c.sql) for c in ctx.candidates]
        for candidate, result in zip(ctx.candidates, results):
            candidate.ok = result.ok
            candidate.error = result.error
            candidate.n_rows = result.n_rows if result.ok else None
        ctx.winner = pick_winner(results)
        ctx.final_sql = ctx.candidates[ctx.winner].sql
