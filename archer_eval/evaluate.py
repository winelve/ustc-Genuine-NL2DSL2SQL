"""Evaluation orchestration: compute VA / EX over a dataset + predictions."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

from archer_eval.data import Sample
from archer_eval.execution import execute_sql
from archer_eval.metrics import execution_match, result_similarity
from archer_eval.progress import Progress


@dataclass
class SampleResult:
    """One evaluated sample — self-describing, so the report is a plain dump."""

    index: int
    db_id: str
    question: str
    reasoning_type: str  # raw dataset label, e.g. "- + C H"
    gold_sql: str
    pred_sql: str
    valid: bool = False  # VA: predicted SQL executed successfully
    match: bool = False  # EX: execution results equivalent to gold
    similarity: float = 0.0  # mean of sim_row / sim_col
    sim_row: float = 0.0
    sim_col: float = 0.0
    pred_shape: list[int] | None = None  # [n_rows, n_cols]
    gold_shape: list[int] | None = None
    pred_error: str | None = None
    gold_error: str | None = None


def find_db_file(db_dir: str | Path, db_id: str) -> Path:
    db_dir = Path(db_dir)
    for candidate in (db_dir / db_id / f"{db_id}.sqlite", db_dir / db_id / f"{db_id}.db"):
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    raise FileNotFoundError(f"no usable database file for db_id={db_id!r} under {db_dir}")


def evaluate_sample(
    sample: Sample, pred_sql: str, db_dir: str | Path, index: int = 0, timeout_s: float = 30.0
) -> SampleResult:
    db_path = find_db_file(db_dir, sample.db_id)
    result = SampleResult(
        index=index,
        db_id=sample.db_id,
        question=sample.question,
        reasoning_type=sample.reasoning_type,
        gold_sql=sample.query,
        pred_sql=pred_sql,
    )

    if not pred_sql.strip():
        # 空串是"生成失败"的约定值（§3.1），但 SQLite 把空语句当合法 no-op，
        # 直接执行会误判 VA=1，所以在这里拦下。
        result.pred_error = "empty prediction"
        return result

    pred_res = execute_sql(db_path, pred_sql, timeout_s=timeout_s)
    if not pred_res.ok:
        result.pred_error = pred_res.error
        return result  # gold is left unrun, so gold_shape stays None
    result.valid = True
    result.pred_shape = [pred_res.n_rows, pred_res.n_cols]

    gold_res = execute_sql(db_path, sample.query, timeout_s=timeout_s)
    if not gold_res.ok:
        # Gold failing indicates a data problem; VA still holds, EX cannot.
        result.gold_error = gold_res.error
        return result
    result.gold_shape = [gold_res.n_rows, gold_res.n_cols]

    result.match = execution_match(pred_res, gold_res, sample.query)
    result.sim_row, result.sim_col = result_similarity(pred_res, gold_res)
    result.similarity = round((result.sim_row + result.sim_col) / 2, 4)
    return result


def _rate(results: list[SampleResult], attr: str) -> float:
    """Mean of a numeric or boolean attribute across results."""
    return sum(getattr(r, attr) for r in results) / len(results) if results else 0.0


def _metrics(results: list[SampleResult]) -> dict:
    return {
        "n": len(results),
        "VA": round(_rate(results, "valid"), 4),
        "EX": round(_rate(results, "match"), 4),
        "SIM": round(_rate(results, "similarity"), 4),
    }


def coarse_reasoning_type(reasoning_type: str) -> str:
    """Map raw labels like '- + C H' to the paper's Table 3 groups.

    A = arithmetic (all Archer samples), +C = commonsense, +H = hypothetical.
    """
    if not reasoning_type:
        return "unknown"
    label = "A"
    if "C" in reasoning_type:
        label += "+C"
    if "H" in reasoning_type:
        label += "+H"
    return label


def evaluate(
    samples: list[Sample],
    predictions: list[str],
    db_dir: str | Path,
    timeout_s: float = 30.0,
    progress: bool = False,
) -> dict:
    if len(samples) != len(predictions):
        raise ValueError(f"{len(samples)} samples but {len(predictions)} predictions")

    bar = Progress(len(samples), "evaluate", enabled=progress)
    results: list[SampleResult] = []
    for i, (sample, pred_sql) in enumerate(zip(samples, predictions)):
        results.append(evaluate_sample(sample, pred_sql, db_dir, index=i, timeout_s=timeout_s))
        bar.step()

    def breakdown(key_fn) -> dict:
        groups: dict[str, list[SampleResult]] = {}
        for s, r in zip(samples, results):
            groups.setdefault(key_fn(s), []).append(r)
        return {k: _metrics(v) for k, v in sorted(groups.items())}

    return {
        "summary": {
            "n": len(results),
            "n_valid": sum(r.valid for r in results),
            "n_match": sum(r.match for r in results),
            "VA": round(_rate(results, "valid"), 4),
            "EX": round(_rate(results, "match"), 4),
            "SIM": round(_rate(results, "similarity"), 4),
        },
        "by_db": breakdown(lambda s: s.db_id),
        "by_reasoning_type": breakdown(lambda s: coarse_reasoning_type(s.reasoning_type)),
        "samples": [asdict(r) for r in results],
    }
