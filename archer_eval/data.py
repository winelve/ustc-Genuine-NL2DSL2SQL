"""Dataset and prediction file loading.

Dataset files (en_data/*.json, zh_data/*.json) are JSON arrays of objects:
    db_id, query (gold SQL), question, reasoning_type, commonsense_knowledge

Prediction files are JSON arrays aligned with the dataset order, either:
    ["SELECT ...", "SELECT ...", ...]
or
    [{"predicted_sql": "SELECT ..."}, ...]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Sample:
    db_id: str
    query: str
    question: str
    reasoning_type: str = ""
    commonsense_knowledge: str | None = None
    extras: dict = field(default_factory=dict)


def load_dataset(path: str | Path) -> list[Sample]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    samples = []
    for item in raw:
        known = {"db_id", "query", "question", "reasoning_type", "commonsense_knowledge"}
        samples.append(
            Sample(
                db_id=item["db_id"],
                query=item["query"],
                question=item["question"],
                reasoning_type=item.get("reasoning_type", ""),
                commonsense_knowledge=item.get("commonsense_knowledge"),
                extras={k: v for k, v in item.items() if k not in known},
            )
        )
    return samples


def load_predictions(path: str | Path, expected_len: int | None = None) -> list[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Prediction file {path} must be a JSON array")
    preds: list[str] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            preds.append(item)
        elif isinstance(item, dict) and "predicted_sql" in item:
            preds.append(item["predicted_sql"])
        else:
            raise ValueError(
                f"Prediction entry {i} must be a string or an object with "
                f"a 'predicted_sql' key, got: {type(item).__name__}"
            )
    if expected_len is not None and len(preds) != expected_len:
        raise ValueError(
            f"Prediction count ({len(preds)}) does not match dataset size ({expected_len})"
        )
    return preds
