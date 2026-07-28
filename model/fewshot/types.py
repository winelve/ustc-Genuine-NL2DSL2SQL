"""Few-shot 离线检索层使用的稳定数据契约。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FewShotExample:
    source_id: str
    db_id: str
    question: str
    sql: str


@dataclass(frozen=True)
class SelectedExample:
    example: FewShotExample
    distance: float
    semantic_rank: int | None = None
    structure_rank: int | None = None
    structure_similarity: float | None = None
    fusion_score: float | None = None


@dataclass(frozen=True)
class SelectionRecord:
    target_key: str
    corpus: str
    encoder: str
    k: int
    examples: tuple[SelectedExample, ...]
