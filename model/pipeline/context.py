"""PipelineContext：单条样本流经全 pipeline 的状态包。

各 stage 只读写这个对象；to_trace() 把它变成可直接 json 落盘的调试记录。
新增字段直接加在这里，不动 stage 接口。
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
    checks: dict | None = None   # 声明层校验记录：{"passed", "rounds", "declarations"}


@dataclass
class PipelineContext:
    question: str
    db_path: Path
    schema: str = ""
    evidence: str = ""           # 题目自带的外部知识（BIRD 有，Archer 官方设定不用）
    fewshot_block: str = ""       # 固定检索例的 prompt 前缀；仅显式 FS 档位非空
    fewshot_trace: dict | None = None
    value_evidence_trace: dict | None = None
    plans: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    winner: int | None = None    # 胜出候选的下标
    final_sql: str = ""

    def to_trace(self) -> dict:
        return {
            "question": self.question,
            "evidence": self.evidence,
            "fewshot": self.fewshot_trace,
            "value_evidence": self.value_evidence_trace,
            "plans": self.plans,
            "candidates": [asdict(c) for c in self.candidates],
            "winner": self.winner,
            "final_sql": self.final_sql,
        }
