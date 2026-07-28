"""Strict, dependency-light reader for fixed CHESS-IR selection JSON."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from model.fewshot.store import sample_key

from .types import RetrievedContext, RetrievedValue, ValueEvidenceRecord


FORMAT_VERSION = 1
STRATEGY_V1 = "chess-ir-mpnet-v1"
STRATEGY_V2 = "chess-ir-mpnet-v2"
SUPPORTED_STRATEGIES = frozenset({STRATEGY_V1, STRATEGY_V2})
# Backward-compatible name used by v1 callers and existing tests/artifacts.
STRATEGY = STRATEGY_V1
_PARAMETER_TYPES = {
    "signature_size": int,
    "n_gram": int,
    "lsh_threshold": float,
    "lsh_top_n": int,
    "edit_threshold": float,
    "embedding_threshold": float,
    "max_values_per_column": int,
    "max_values_total": int,
    "max_context_columns": int,
}


@dataclass(frozen=True)
class ValueEvidenceStore:
    records: Mapping[str, ValueEvidenceRecord]
    dataset: str
    dataset_sha256: str
    keywords_sha256: str
    encoder: str
    encoder_sha256: str
    parameters: Mapping[str, int | float] = field(default_factory=dict)
    strategy: str = STRATEGY
    artifact_sha256: str = ""

    @classmethod
    def from_path(cls, path: Path) -> "ValueEvidenceStore":
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid value evidence JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError("value evidence artifact must be a JSON object")

        version = payload.get("format_version")
        if isinstance(version, bool) or version != FORMAT_VERSION:
            raise ValueError(
                f"unsupported value evidence format_version: {version!r}"
            )
        strategy = _required_string(payload, "strategy", "metadata")
        if strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(f"unsupported value evidence strategy: {strategy!r}")

        parameters = _parse_parameters(payload.get("parameters"))
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("value evidence metadata records must be a list")

        records: dict[str, ValueEvidenceRecord] = {}
        for index, item in enumerate(raw_records):
            record = _parse_record(item, index)
            if record.target_key in records:
                raise ValueError(f"duplicate target_key: {record.target_key}")
            records[record.target_key] = record

        return cls(
            records=MappingProxyType(records),
            dataset=_required_string(payload, "dataset", "metadata"),
            dataset_sha256=_required_sha256(payload, "dataset_sha256", "metadata"),
            keywords_sha256=_required_sha256(
                payload, "keywords_sha256", "metadata"
            ),
            encoder=_required_string(payload, "encoder", "metadata"),
            encoder_sha256=_required_sha256(payload, "encoder_sha256", "metadata"),
            parameters=MappingProxyType(parameters),
            strategy=strategy,
            artifact_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def for_sample(
        self, db_id: str, question: str
    ) -> ValueEvidenceRecord | None:
        return self.records.get(sample_key(db_id, question))


def _parse_record(value: Any, index: int) -> ValueEvidenceRecord:
    context = f"record {index}"
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    target_key = _required_sha256(value, "target_key", context)
    db_id = _required_string(value, "db_id", context)
    question = _required_string(value, "question", context)
    if target_key != sample_key(db_id, question):
        raise ValueError(f"{context} target_key does not match db_id/question")

    raw_keywords = value.get("keywords")
    if not isinstance(raw_keywords, list):
        raise ValueError(f"{context} keywords must be a list")
    keywords: list[str] = []
    for keyword_index, keyword in enumerate(raw_keywords):
        parsed = _nonempty_string(keyword, f"{context} keyword {keyword_index}")
        if parsed not in keywords:
            keywords.append(parsed)

    raw_values = value.get("values")
    if not isinstance(raw_values, list):
        raise ValueError(f"{context} values must be a list")
    values: list[RetrievedValue] = []
    seen_values: set[tuple[str, str, str]] = set()
    for value_index, item in enumerate(raw_values):
        item_context = f"{context} value {value_index}"
        if not isinstance(item, dict):
            raise ValueError(f"{item_context} must be an object")
        table = _required_string(item, "table", item_context)
        column = _required_string(item, "column", item_context)
        cell = _required_string(item, "value", item_context)
        value_key = (table.casefold(), column.casefold(), cell)
        if value_key in seen_values:
            raise ValueError(f"{item_context} has duplicate retrieved value")
        seen_values.add(value_key)
        control_value = _required_string(
            item, "control_value", item_context
        )
        if control_value == cell:
            raise ValueError(
                f"{item_context} control_value must differ from value"
            )
        values.append(
            RetrievedValue(
                table=table,
                column=column,
                value=cell,
                control_value=control_value,
                keyword=_required_string(item, "keyword", item_context),
                edit_similarity=_required_unit_float(
                    item, "edit_similarity", item_context
                ),
                embedding_similarity=_required_unit_float(
                    item, "embedding_similarity", item_context
                ),
            )
        )

    raw_contexts = value.get("contexts")
    if not isinstance(raw_contexts, list):
        raise ValueError(f"{context} contexts must be a list")
    contexts: list[RetrievedContext] = []
    seen_contexts: set[tuple[str, str]] = set()
    for context_index, item in enumerate(raw_contexts):
        item_context = f"{context} context {context_index}"
        if not isinstance(item, dict):
            raise ValueError(f"{item_context} must be an object")
        table = _required_string(item, "table", item_context)
        column = _required_string(item, "column", item_context)
        context_key = (table.casefold(), column.casefold())
        if context_key in seen_contexts:
            raise ValueError(f"{item_context} has duplicate retrieved context")
        seen_contexts.add(context_key)
        contexts.append(
            RetrievedContext(
                table=table,
                column=column,
                description=_required_string(
                    item, "description", item_context
                ),
                score=_required_unit_float(item, "score", item_context),
            )
        )

    return ValueEvidenceRecord(
        target_key=target_key,
        db_id=db_id,
        question=question,
        keywords=tuple(keywords),
        values=tuple(values),
        contexts=tuple(contexts),
    )


def _parse_parameters(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        raise ValueError("value evidence metadata parameters must be an object")
    parsed: dict[str, int | float] = {}
    for key, expected in _PARAMETER_TYPES.items():
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"value evidence parameters requires numeric {key}")
        number: int | float
        if expected is int:
            if not isinstance(raw, int) or raw <= 0:
                raise ValueError(
                    f"value evidence parameters requires positive integer {key}"
                )
            number = raw
        else:
            number = float(raw)
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(
                    f"value evidence parameters requires {key} within [0, 1]"
                )
        parsed[key] = number
    return parsed


def _nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def _required_string(
    payload: Mapping[str, Any], key: str, context: str
) -> str:
    return _nonempty_string(payload.get(key), f"{context} {key}")


def _required_sha256(
    payload: Mapping[str, Any], key: str, context: str
) -> str:
    value = _required_string(payload, key, context)
    if len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError(
            f"{context} requires 64-character hexadecimal {key}"
        )
    return value.lower()


def _required_unit_float(
    payload: Mapping[str, Any], key: str, context: str
) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} requires numeric {key}")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{context} requires {key} within [0, 1]")
    return number
