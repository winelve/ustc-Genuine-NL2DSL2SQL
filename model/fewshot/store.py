"""固定 few-shot 选择文件的纯数据读取器。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .types import FewShotExample, SelectedExample, SelectionRecord


FORMAT_VERSION = 1


def _normalise_key_part(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def sample_key(db_id: str, question: str) -> str:
    """Return the stable lookup key for a target database/question pair.

    The normalisation deliberately leaves internal whitespace untouched: it only
    canonicalises line endings and removes surrounding whitespace, so a stored
    selection cannot silently match a materially different question.
    """
    text = "\n".join(
        (
            _normalise_key_part(db_id, name="db_id"),
            _normalise_key_part(question, name="question"),
        )
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SelectionStore:
    """An immutable index of precomputed selections, keyed by target hash."""

    records: Mapping[str, SelectionRecord]
    corpus_sha256: str = ""

    @classmethod
    def from_path(cls, path: Path) -> "SelectionStore":
        """Load and validate a format-version-1 selection JSON file."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid selection JSON: {path}") from exc

        if not isinstance(payload, dict):
            raise ValueError("selection file must contain a JSON object")
        format_version = payload.get("format_version")
        if (
            isinstance(format_version, bool)
            or not isinstance(format_version, int)
            or format_version != FORMAT_VERSION
        ):
            raise ValueError(f"unsupported selection format_version: {format_version!r}")

        corpus = _required_string(payload, "corpus", context="selection metadata")
        corpus_sha256 = _required_string(
            payload, "corpus_sha256", context="selection metadata"
        )
        encoder = _required_string(payload, "encoder", context="selection metadata")
        k = _required_positive_int(payload, "k", context="selection metadata")
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("selection metadata records must be a list")

        records: dict[str, SelectionRecord] = {}
        for index, raw_record in enumerate(raw_records):
            context = f"record {index}"
            if not isinstance(raw_record, dict):
                raise ValueError(f"{context} must be an object")
            target_key = _required_string(raw_record, "target_key", context=context)
            if target_key in records:
                raise ValueError(f"duplicate target_key: {target_key}")
            raw_examples = raw_record.get("examples")
            if not isinstance(raw_examples, list):
                raise ValueError(f"{context} examples must be a list")
            if len(raw_examples) != k:
                raise ValueError(f"{context} must contain exactly k examples")

            seen_source_ids: set[str] = set()
            examples: list[SelectedExample] = []
            for example_index, raw_example in enumerate(raw_examples):
                example_context = f"{context} example {example_index}"
                if not isinstance(raw_example, dict):
                    raise ValueError(f"{example_context} must be an object")
                source_id = _required_string(raw_example, "source_id", context=example_context)
                if source_id in seen_source_ids:
                    raise ValueError(f"{example_context} has duplicate source_id: {source_id}")
                seen_source_ids.add(source_id)
                example = FewShotExample(
                    source_id=source_id,
                    db_id=_required_string(raw_example, "db_id", context=example_context),
                    question=_required_string(raw_example, "question", context=example_context),
                    sql=_required_string(raw_example, "sql", context=example_context),
                )
                distance = _required_distance(raw_example, context=example_context)
                examples.append(SelectedExample(example=example, distance=distance))

            records[target_key] = SelectionRecord(
                target_key=target_key,
                corpus=corpus,
                encoder=encoder,
                k=k,
                examples=tuple(examples),
            )

        return cls(
            records=MappingProxyType(records),
            corpus_sha256=corpus_sha256,
        )

    def for_sample(self, db_id: str, question: str) -> SelectionRecord | None:
        """Return a target's fixed examples, or ``None`` when it was not selected."""
        return self.records.get(sample_key(db_id, question))


def _required_string(payload: Mapping[str, Any], key: str, *, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires non-empty {key}")
    return value


def _required_positive_int(payload: Mapping[str, Any], key: str, *, context: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{context} requires positive integer {key}")
    return value


def _required_distance(payload: Mapping[str, Any], *, context: str) -> float:
    value = payload.get("distance")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} requires numeric distance")
    distance = float(value)
    if not math.isfinite(distance):
        raise ValueError(f"{context} requires finite distance")
    return distance
