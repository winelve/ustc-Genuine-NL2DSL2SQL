"""PipelineContext：单条样本流经全 pipeline 的状态包。

各 stage 只读写这个对象；to_trace() 把它变成可直接 json 落盘的调试记录。
M2 在这里加 DSL 相关字段即可，不动 stage 接口。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Candidate:
    """一个 plan 对应的一条候选 SQL 及其执行摘要。"""

    plan: str
    sql: str = ""
    ok: bool | None = None       # None = 尚未执行
    error: str | None = None
    n_rows: int | None = None


@dataclass
class PipelineContext:
    question: str
    db_path: Path
    schema: str = ""
    plans: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    winner: int | None = None    # 胜出候选的下标
    final_sql: str = ""

    def to_trace(self) -> dict:
        return {
            "question": self.question,
            "plans": self.plans,
            "candidates": [asdict(c) for c in self.candidates],
            "winner": self.winner,
            "final_sql": self.final_sql,
        }
