"""Immutable runtime types for fixed CHESS-IR selection artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedValue:
    table: str
    column: str
    value: str
    control_value: str
    keyword: str
    edit_similarity: float
    embedding_similarity: float


@dataclass(frozen=True)
class RetrievedContext:
    table: str
    column: str
    description: str
    score: float


@dataclass(frozen=True)
class ValueEvidenceRecord:
    target_key: str
    db_id: str
    question: str
    keywords: tuple[str, ...]
    values: tuple[RetrievedValue, ...]
    contexts: tuple[RetrievedContext, ...]
