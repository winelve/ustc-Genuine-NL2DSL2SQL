"""Shared few-shot trace serialization for Direct and pipeline models."""

from __future__ import annotations

from typing import Any

from .store import SelectionStore
from .types import SelectionRecord


def fewshot_trace(
    *,
    selection: str,
    record: SelectionRecord,
    store: SelectionStore,
) -> dict[str, Any]:
    """Serialize retrieval provenance while preserving the legacy RSL shape."""
    trace: dict[str, Any] = {
        "selection": selection,
        "corpus": record.corpus,
        "corpus_sha256": store.corpus_sha256,
        "encoder": record.encoder,
        "k": record.k,
        "source_ids": [
            selected.example.source_id for selected in record.examples
        ],
        "distances": [selected.distance for selected in record.examples],
    }
    if store.retrieval:
        trace.update(
            {
                "retrieval": dict(store.retrieval),
                "semantic_ranks": [
                    selected.semantic_rank for selected in record.examples
                ],
                "structure_ranks": [
                    selected.structure_rank for selected in record.examples
                ],
                "structure_similarities": [
                    selected.structure_similarity for selected in record.examples
                ],
                "fusion_scores": [
                    selected.fusion_score for selected in record.examples
                ],
            }
        )
    return trace
