"""BIRD 官方口径 EX 的**本项目实现**——快、只读、零依赖、出逐题明细。

判分逻辑与官方 `evaluation.py` 逐字同义：

    判对 = set(pred_rows) == set(gold_rows)

即行序无关、列序有关、重复行折叠；任何异常或超时一律判 0（官方不区分 VA）。

> **报数以官方脚本为准**：`python -m bird eval --official` 跑的是原样 vendor 的
> 官方脚本（`bird/official_eval/`）。本模块是日常用的那一份——它多给逐题结果、
> by_db 明细，且不需要 `func_timeout`。两者必须给出相同的数，靠
> `python -m bird eval --cross-check` 实测验证，不靠"我们声称等价"。

**与官方脚本的偏离，逐条声明（同样写进每份报告的 `meta.deviations`）：**

1. **只读连接**——官方用可写 `sqlite3.connect`，本项目铁律是数据库只读。
   差异只可能出现在写操作预测上，而那本来就该判 0。
2. **超时机制**——官方用 `func_timeout` 起线程，这里复用 `archer_eval.execution`
   的 progress handler，不引新依赖。**预算口径已对齐**：官方那 30s 罩着
   "跑预测 + 跑 gold"两条，所以这里也让两条共享同一个 30s，而不是各给 30s。
3. **空预测**——官方会把空串交给 sqlite（返回空结果集，可能与空 gold 意外相等），
   这里直接判 0。生成失败不该有机会蒙对。

本模块与 `archer_eval` 的 VA/EX/SIM 是**两套独立口径**，数字不可直接并排——
Archer 侧继续用 `python -m archer_eval`，BIRD 侧用 `python -m bird eval`。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path

from archer_eval.data import Sample
from archer_eval.evaluate import find_db_file
from archer_eval.execution import execute_sql
from archer_eval.progress import Progress
from config import DEFAULT_TIMEOUT_S

DEVIATIONS = [
    "read-only connection (official uses a writable one; write predictions score 0 either way)",
    "timeout via sqlite progress handler (official uses func_timeout); the limit is shared by "
    "the prediction and the gold query, matching the official single func_timeout call",
    "empty prediction scores 0 up front (official hands it to sqlite, which may return an "
    "empty result set and accidentally match an empty gold)",
]

# 报告里难度档的固定顺序（官方表格顺序），未知难度垫底
_DIFFICULTY_ORDER = {"simple": 0, "moderate": 1, "challenging": 2}


@dataclass
class BirdResult:
    index: int
    question_id: int | None
    db_id: str
    difficulty: str
    match: bool = False
    error: str | None = None


def rows_match(pred_rows, gold_rows) -> bool:
    """官方判定：`set(pred) == set(gold)`。"""
    return set(pred_rows) == set(gold_rows)


def evaluate_bird_sample(
    sample: Sample,
    pred_sql: str,
    db_dir: str | Path,
    index: int = 0,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> BirdResult:
    result = BirdResult(
        index=index,
        question_id=sample.extras.get("question_id"),
        db_id=sample.db_id,
        difficulty=sample.extras.get("difficulty", ""),
    )
    if not pred_sql.strip():
        result.error = "empty prediction"
        return result

    try:
        db_path = find_db_file(db_dir, sample.db_id)
    except FileNotFoundError as e:
        result.error = str(e)
        return result

    # 一个预算罩住两条查询（对齐官方那一次 func_timeout）
    deadline = time.monotonic() + timeout_s

    pred = execute_sql(db_path, pred_sql, timeout_s=timeout_s)
    if not pred.ok:
        result.error = pred.error
        return result

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        result.error = "timeout: prediction used the whole budget"
        return result

    gold = execute_sql(db_path, sample.query, timeout_s=remaining)
    if not gold.ok:
        # gold 自己跑不出来（#518/#701 两题如此）——官方口径下该题恒为 0
        result.error = f"gold: {gold.error}"
        return result

    result.match = rows_match(pred.rows, gold.rows)
    return result


def _metrics(results: list[BirdResult]) -> dict:
    n = len(results)
    n_match = sum(r.match for r in results)
    return {
        "n": n,
        "n_match": n_match,
        "EX": round(n_match / n, 4) if n else 0.0,
        "EX_pct": round(100 * n_match / n, 2) if n else 0.0,
    }


def evaluate_bird(
    samples: list[Sample],
    predictions: list[str],
    db_dir: str | Path,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    progress: bool = False,
) -> dict:
    if len(samples) != len(predictions):
        raise ValueError(f"{len(samples)} samples but {len(predictions)} predictions")

    bar = Progress(len(samples), "bird-eval", enabled=progress)
    results: list[BirdResult] = []
    for i, (sample, pred) in enumerate(zip(samples, predictions)):
        results.append(evaluate_bird_sample(sample, pred, db_dir, index=i, timeout_s=timeout_s))
        bar.step()

    def breakdown(key_fn) -> dict:
        groups: dict[str, list[BirdResult]] = {}
        for r in results:
            groups.setdefault(key_fn(r), []).append(r)
        return {k: _metrics(v) for k, v in sorted(groups.items())}

    by_difficulty = dict(sorted(
        breakdown(lambda r: r.difficulty or "unknown").items(),
        key=lambda kv: _DIFFICULTY_ORDER.get(kv[0], 99),
    ))

    return {
        "meta": {
            "protocol": "bird-official",
            "deviations": DEVIATIONS,
            "timeout_s": timeout_s,
            "db_dir": str(db_dir),
        },
        "summary": _metrics(results),
        "by_difficulty": by_difficulty,
        "by_db": breakdown(lambda r: r.db_id),
        "samples": [asdict(r) for r in results],
    }
