"""Build deterministic, RSL-compatible few-shot selections offline.

Heavy retrieval dependencies are deliberately imported inside the functions
that use them.  Importing the online ``model`` package therefore does not
require Torch, Sentence Transformers, NumPy, or PyArrow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Mapping, Sequence

from .store import FORMAT_VERSION, sample_key
from .structure import multiset_jaccard, rank_fusion, sql_structure_features
from .types import FewShotExample


# With BIRD's 9,428-row corpus this makes the largest pairwise matrix
# 256 * 9,428 float64 values (about 18.4 MiB), rather than materialising a
# target * corpus * embedding-dimension tensor.
TARGET_BLOCK_SIZE = 256


def select_top_k(
    target_embeddings: Any,
    corpus_embeddings: Any,
    *,
    k: int,
    excluded: set[int] | Sequence[set[int]] | Mapping[int, set[int]],
) -> list[list[tuple[int, float]]]:
    """Return each target's nearest corpus indices using Euclidean distance.

    ``excluded`` may be one set applied to every target, a sequence containing
    one set per target, or a mapping from target row to excluded corpus rows.
    Stable sorting makes equal-distance results deterministic by corpus order.
    """
    try:
        import numpy as np
    except ModuleNotFoundError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "offline few-shot selection requires NumPy; install requirements-fewshot.txt"
        ) from exc

    # float64 keeps the norm/dot-product identity numerically reliable while
    # remaining small: the full BIRD corpus embedding is about 55 MiB.
    targets = np.asarray(target_embeddings, dtype=np.float64)
    corpus = np.asarray(corpus_embeddings, dtype=np.float64)
    if targets.ndim != 2 or corpus.ndim != 2:
        raise ValueError("target_embeddings and corpus_embeddings must be 2-D")
    if targets.shape[1] != corpus.shape[1]:
        raise ValueError("target and corpus embedding dimensions must match")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")

    excluded_by_target = _normalise_exclusions(excluded, len(targets))

    rows: list[list[tuple[int, float]]] = []
    if TARGET_BLOCK_SIZE <= 0:
        raise ValueError("TARGET_BLOCK_SIZE must be positive")
    for block_start in range(0, len(targets), TARGET_BLOCK_SIZE):
        block_end = min(block_start + TARGET_BLOCK_SIZE, len(targets))
        distances = _euclidean_distance_block(
            targets[block_start:block_end],
            corpus,
        )
        for local_index, corpus_indices in enumerate(
            excluded_by_target[block_start:block_end]
        ):
            for corpus_index in corpus_indices:
                if corpus_index < 0 or corpus_index >= len(corpus):
                    raise ValueError(
                        f"excluded corpus index out of range: {corpus_index}"
                    )
                distances[local_index, corpus_index] = np.inf

        for row in distances:
            ordered = np.argsort(row, kind="stable")
            selected = [
                (int(index), float(row[index]))
                for index in ordered
                if np.isfinite(row[index])
            ][:k]
            rows.append(selected)
    return rows


def _euclidean_distance_block(target_block: Any, corpus_embeddings: Any) -> Any:
    """Compute one exact Euclidean distance block without a 3-D broadcast."""
    try:
        import numpy as np
    except ModuleNotFoundError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "offline few-shot selection requires NumPy; install requirements-fewshot.txt"
        ) from exc

    targets = np.asarray(target_block, dtype=np.float64)
    corpus = np.asarray(corpus_embeddings, dtype=np.float64)
    target_squared_norms = np.einsum("ij,ij->i", targets, targets)[:, None]
    corpus_squared_norms = np.einsum("ij,ij->i", corpus, corpus)[None, :]
    squared_distances = targets @ corpus.T
    squared_distances *= -2.0
    squared_distances += target_squared_norms
    squared_distances += corpus_squared_norms
    # The algebraic result is non-negative, but floating-point cancellation can
    # leave a tiny negative value for identical or near-identical embeddings.
    np.maximum(squared_distances, 0.0, out=squared_distances)
    np.sqrt(squared_distances, out=squared_distances)
    return squared_distances


def _normalise_exclusions(
    excluded: set[int] | Sequence[set[int]] | Mapping[int, set[int]],
    target_count: int,
) -> list[set[int]]:
    if isinstance(excluded, set):
        return [set(excluded) for _ in range(target_count)]
    if isinstance(excluded, Mapping):
        return [set(excluded.get(index, set())) for index in range(target_count)]
    if len(excluded) != target_count:
        raise ValueError("excluded must contain one set per target")
    return [set(indices) for indices in excluded]


def build_corpus(
    *,
    input_path: Path,
    input_format: str,
    name: str,
    output_path: Path,
) -> dict[str, Any]:
    """Convert an Archer JSON or RSL/BIRD Parquet file to the stable corpus JSON."""
    if not name.strip():
        raise ValueError("corpus name must be non-empty")
    if input_format == "archer-json":
        rows = _read_archer_rows(input_path)
        source_prefix = name.removeprefix("archer_")
        sql_column = "query"
    elif input_format == "bird-parquet":
        rows = _read_bird_parquet_rows(input_path)
        source_prefix = name
        sql_column = "SQL"
    else:
        raise ValueError(f"unsupported corpus format: {input_format}")

    examples: list[dict[str, str]] = []
    seen_source_ids: set[str] = set()
    for index, row in enumerate(rows):
        context = f"row {index}"
        source_id = row.get("source_id", f"{source_prefix}:{index}")
        example = FewShotExample(
            source_id=_required_string(source_id, "source_id", context),
            db_id=_required_string(row.get("db_id"), "db_id", context),
            question=_required_string(row.get("question"), "question", context),
            sql=_required_string(row.get(sql_column), sql_column, context),
        )
        if example.source_id in seen_source_ids:
            raise ValueError(f"duplicate source_id: {example.source_id}")
        seen_source_ids.add(example.source_id)
        examples.append(
            {
                "source_id": example.source_id,
                "db_id": example.db_id,
                "question": example.question,
                "sql": example.sql,
            }
        )

    payload: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "name": name,
        "examples": examples,
    }
    _write_json(output_path, payload)
    return payload


def _read_archer_rows(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise ValueError("Archer JSON must contain a list")
    required = {"db_id", "question", "query"}
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"row {index} must be an object")
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"row {index} missing required columns: {', '.join(missing)}")
        rows.append(row)
    return rows


def _read_bird_parquet_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as parquet
    except ModuleNotFoundError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "BIRD Parquet conversion requires PyArrow; "
            "install requirements-fewshot.txt in Python 3.11/3.12"
        ) from exc

    table = parquet.read_table(path)
    required = {"db_id", "question", "SQL"}
    missing = sorted(required - set(table.column_names))
    if missing:
        raise ValueError(f"BIRD Parquet missing required columns: {', '.join(missing)}")
    return table.select(["db_id", "question", "SQL"]).to_pylist()


def encode_texts(texts: Sequence[str], encoder: str) -> Any:
    """Encode questions on CPU with the local Sentence Transformer model."""
    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "embedding requires Torch and Sentence Transformers; "
            "install requirements-fewshot.txt in Python 3.11/3.12"
        ) from exc

    # Import Torch explicitly here as part of the optional offline dependency
    # boundary.  RSL used CPU, so keep that device even when CUDA is available.
    _ = torch
    model = SentenceTransformer(encoder, device="cpu")
    return model.encode(
        list(texts),
        convert_to_numpy=True,
        show_progress_bar=True,
    )


def build_selection(
    *,
    corpus_path: Path,
    targets_path: Path,
    target_format: str,
    encoder: str,
    k: int,
    output_path: Path,
) -> dict[str, Any]:
    """Embed questions and write a deterministic, leakage-safe selection file."""
    corpus_path = Path(corpus_path)
    targets_path = Path(targets_path)
    output_path = Path(output_path)
    same_file = corpus_path.resolve() == targets_path.resolve()
    if same_file:
        raw_targets = _target_rows_from_payload(_read_json(targets_path))
        if any(not _optional_source_id(row) for row in raw_targets):
            raise ValueError(
                "corpus and targets are the same file but targets have no source_id"
            )

    corpus_payload = _read_json(corpus_path)
    corpus_name, corpus_examples = _parse_corpus(corpus_payload)
    target_rows = _read_target_rows(targets_path, target_format)
    if not target_rows:
        raise ValueError("targets file contains no records")

    target_identities: dict[str, tuple[str, str]] = {}
    targets: list[dict[str, str | None]] = []
    for index, row in enumerate(target_rows):
        context = f"target row {index}"
        db_id = _required_string(row.get("db_id"), "db_id", context)
        question = _required_string(row.get("question"), "question", context)
        target_source_id = _optional_source_id(row)
        key = sample_key(db_id, question)
        identity = _target_identity(db_id, question)
        existing_identity = target_identities.get(key)
        if existing_identity is not None:
            if existing_identity != identity:
                raise ValueError(
                    f"target_key collision at target row {index}: "
                    "different normalized targets produced the same hash"
                )
            # Identical targets intentionally share the first SelectionRecord.
            continue
        target_identities[key] = identity
        targets.append(
            {
                "db_id": identity[0],
                "question": identity[1],
                "source_id": target_source_id,
                "target_key": key,
            }
        )

    all_questions = [example.question for example in corpus_examples] + [
        str(target["question"]) for target in targets
    ]
    embeddings = encode_texts(all_questions, encoder)
    corpus_count = len(corpus_examples)
    corpus_embeddings = embeddings[:corpus_count]
    target_embeddings = embeddings[corpus_count:]

    corpus_indices_by_source = {
        example.source_id: index for index, example in enumerate(corpus_examples)
    }
    excluded: list[set[int]] = []
    for target in targets:
        source_id = target["source_id"]
        excluded.append(
            {corpus_indices_by_source[source_id]}
            if source_id in corpus_indices_by_source
            else set()
        )
    selected_rows = select_top_k(
        target_embeddings,
        corpus_embeddings,
        k=k,
        excluded=excluded,
    )

    records: list[dict[str, Any]] = []
    for target, selected in zip(targets, selected_rows, strict=True):
        if len(selected) != k:
            raise ValueError(
                f"target {target['target_key']} has only {len(selected)} eligible "
                f"corpus examples, fewer than k={k}"
            )
        record: dict[str, Any] = {
            "target_key": target["target_key"],
            "examples": [],
        }
        if target["source_id"] is not None:
            record["target_source_id"] = target["source_id"]
        for corpus_index, distance in selected:
            example = corpus_examples[corpus_index]
            record["examples"].append(
                {
                    "source_id": example.source_id,
                    "db_id": example.db_id,
                    "question": example.question,
                    "sql": example.sql,
                    "distance": distance,
                }
            )
        records.append(record)

    payload = {
        "format_version": FORMAT_VERSION,
        "corpus": corpus_name,
        "corpus_sha256": _sha256(corpus_path),
        "encoder": encoder,
        "k": k,
        "records": records,
    }
    _write_json(output_path, payload)
    return payload


def build_sfs_selection(
    *,
    semantic_selection_path: Path,
    targets_path: Path,
    draft_predictions_path: Path,
    output_path: Path,
    candidate_k: int = 30,
    k: int = 3,
) -> dict[str, Any]:
    """Rerank a semantic candidate pool with frozen draft-SQL structure."""
    if (
        isinstance(candidate_k, bool)
        or not isinstance(candidate_k, int)
        or candidate_k <= 0
    ):
        raise ValueError("candidate_k must be a positive integer")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    if k > candidate_k:
        raise ValueError("k must not exceed candidate_k")

    semantic_selection_path = Path(semantic_selection_path)
    targets_path = Path(targets_path)
    draft_predictions_path = Path(draft_predictions_path)
    output_path = Path(output_path)

    semantic_payload = _read_json(semantic_selection_path)
    if not isinstance(semantic_payload, dict):
        raise ValueError("semantic selection JSON must contain an object")
    format_version = semantic_payload.get("format_version")
    if (
        isinstance(format_version, bool)
        or not isinstance(format_version, int)
        or format_version != FORMAT_VERSION
    ):
        raise ValueError("unsupported semantic selection format_version")
    corpus = _required_string(
        semantic_payload.get("corpus"), "corpus", "semantic selection"
    )
    corpus_sha256 = _required_string(
        semantic_payload.get("corpus_sha256"),
        "corpus_sha256",
        "semantic selection",
    )
    encoder = _required_string(
        semantic_payload.get("encoder"), "encoder", "semantic selection"
    )
    raw_records = semantic_payload.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("semantic selection records must be a list")
    records_by_key: dict[str, dict[str, Any]] = {}
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, dict):
            raise ValueError(f"semantic selection record {index} must be an object")
        target_key = _required_string(
            raw_record.get("target_key"),
            "target_key",
            f"semantic selection record {index}",
        )
        if target_key in records_by_key:
            raise ValueError(f"duplicate semantic target_key: {target_key}")
        records_by_key[target_key] = raw_record

    target_rows = _read_target_rows(targets_path, "archer-json")
    predictions = _read_prediction_sqls(draft_predictions_path)
    if len(predictions) != len(target_rows):
        raise ValueError(
            f"prediction count ({len(predictions)}) does not match "
            f"target count ({len(target_rows)})"
        )

    drafts_by_key: dict[str, str] = {}
    target_order: list[str] = []
    for index, (target, draft_sql) in enumerate(
        zip(target_rows, predictions, strict=True)
    ):
        context = f"target row {index}"
        db_id = _required_string(target.get("db_id"), "db_id", context)
        question = _required_string(target.get("question"), "question", context)
        target_key = sample_key(db_id, question)
        normalized_draft = _normalize_sql_text(draft_sql)
        previous = drafts_by_key.get(target_key)
        if previous is not None:
            if previous != normalized_draft:
                raise ValueError(
                    f"conflicting draft SQL for duplicate target_key: {target_key}"
                )
            continue
        drafts_by_key[target_key] = normalized_draft
        target_order.append(target_key)

    fallback_count = 0
    semantic_top_k_similarities: list[float] = []
    sfs_top_k_similarities: list[float] = []
    output_records: list[dict[str, Any]] = []
    feature_cache: dict[tuple[str, str], Mapping[str, int]] = {}
    for target_key in target_order:
        raw_record = records_by_key.get(target_key)
        if raw_record is None:
            raise ValueError(
                f"semantic selection is missing target_key: {target_key}"
            )
        raw_examples = raw_record.get("examples")
        if not isinstance(raw_examples, list):
            raise ValueError(
                f"semantic selection target {target_key} examples must be a list"
            )
        if len(raw_examples) < candidate_k:
            raise ValueError(
                f"semantic selection target {target_key} has {len(raw_examples)} "
                f"examples, fewer than candidate_k={candidate_k}"
            )

        candidates: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        for index, raw_example in enumerate(raw_examples[:candidate_k]):
            context = f"semantic target {target_key} example {index}"
            if not isinstance(raw_example, dict):
                raise ValueError(f"{context} must be an object")
            source_id = _required_string(
                raw_example.get("source_id"), "source_id", context
            )
            if source_id in seen_source_ids:
                raise ValueError(f"{context} has duplicate source_id: {source_id}")
            seen_source_ids.add(source_id)
            candidate = {
                "source_id": source_id,
                "db_id": _required_string(
                    raw_example.get("db_id"), "db_id", context
                ),
                "question": _required_string(
                    raw_example.get("question"), "question", context
                ),
                "sql": _required_string(raw_example.get("sql"), "sql", context),
                "distance": _required_finite_number(
                    raw_example.get("distance"), "distance", context
                ),
            }
            candidates.append(candidate)

        target_features = sql_structure_features(drafts_by_key[target_key])
        if not target_features:
            fallback_count += 1
        structure_scores: dict[str, float] = {}
        for candidate in candidates:
            cache_key = (candidate["source_id"], candidate["sql"])
            candidate_features = feature_cache.get(cache_key)
            if candidate_features is None:
                candidate_features = sql_structure_features(candidate["sql"])
                feature_cache[cache_key] = candidate_features
            structure_scores[candidate["source_id"]] = multiset_jaccard(
                target_features, candidate_features
            )

        semantic_order = tuple(candidate["source_id"] for candidate in candidates)
        fused = rank_fusion(semantic_order, structure_scores)
        semantic_top_k_similarities.extend(
            structure_scores[source_id] for source_id in semantic_order[:k]
        )
        sfs_top_k_similarities.extend(
            candidate.structure_similarity for candidate in fused[:k]
        )
        candidates_by_id = {
            candidate["source_id"]: candidate for candidate in candidates
        }
        output_examples: list[dict[str, Any]] = []
        for fused_candidate in fused[:k]:
            output_example = dict(candidates_by_id[fused_candidate.source_id])
            output_example.update(
                {
                    "semantic_rank": fused_candidate.semantic_rank,
                    "structure_rank": fused_candidate.structure_rank,
                    "structure_similarity": fused_candidate.structure_similarity,
                    "fusion_score": fused_candidate.fusion_score,
                }
            )
            output_examples.append(output_example)

        output_record: dict[str, Any] = {
            "target_key": target_key,
            "examples": output_examples,
        }
        if "target_source_id" in raw_record:
            output_record["target_source_id"] = raw_record["target_source_id"]
        output_records.append(output_record)

    payload = {
        "format_version": FORMAT_VERSION,
        "corpus": corpus,
        "corpus_sha256": corpus_sha256,
        "encoder": encoder,
        "k": k,
        "retrieval": {
            "strategy": "sfs-v1",
            "structure_features": "sqlglot-multiset-v1",
            "semantic_selection_sha256": _sha256(semantic_selection_path),
            "draft_predictions_sha256": _sha256(draft_predictions_path),
            "targets_sha256": _sha256(targets_path),
            "candidate_k": candidate_k,
            "semantic_weight": 0.5,
            "structure_weight": 0.5,
            "fallback_count": fallback_count,
            "mean_structure_similarity_semantic_top_k": statistics.fmean(
                semantic_top_k_similarities
            ),
            "mean_structure_similarity_sfs_top_k": statistics.fmean(
                sfs_top_k_similarities
            ),
        },
        "records": output_records,
    }
    _write_json(output_path, payload)
    return payload


def _read_prediction_sqls(path: Path) -> list[str]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise ValueError("draft prediction JSON must contain a list")
    predictions: list[str] = []
    for index, item in enumerate(payload):
        if isinstance(item, str):
            predictions.append(item)
        elif isinstance(item, dict) and isinstance(item.get("predicted_sql"), str):
            predictions.append(item["predicted_sql"])
        else:
            raise ValueError(
                f"draft prediction entry {index} must be a string or contain "
                "string predicted_sql"
            )
    return predictions


def _normalize_sql_text(sql: str) -> str:
    return sql.replace("\r\n", "\n").replace("\r", "\n").strip()


def _required_finite_number(value: Any, field: str, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} requires numeric {field}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{context} requires finite {field}")
    return number


def _parse_corpus(payload: Any) -> tuple[str, list[FewShotExample]]:
    if not isinstance(payload, dict):
        raise ValueError("corpus JSON must contain an object")
    format_version = payload.get("format_version")
    if (
        isinstance(format_version, bool)
        or not isinstance(format_version, int)
        or format_version != FORMAT_VERSION
    ):
        raise ValueError("unsupported corpus format_version")
    name = _required_string(payload.get("name"), "name", "corpus")
    raw_examples = payload.get("examples")
    if not isinstance(raw_examples, list):
        raise ValueError("corpus examples must be a list")
    if not raw_examples:
        raise ValueError("corpus contains no examples")

    examples: list[FewShotExample] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_examples):
        context = f"corpus example {index}"
        if not isinstance(raw, dict):
            raise ValueError(f"{context} must be an object")
        example = FewShotExample(
            source_id=_required_string(raw.get("source_id"), "source_id", context),
            db_id=_required_string(raw.get("db_id"), "db_id", context),
            question=_required_string(raw.get("question"), "question", context),
            sql=_required_string(raw.get("sql"), "sql", context),
        )
        if example.source_id in seen:
            raise ValueError(f"duplicate source_id: {example.source_id}")
        seen.add(example.source_id)
        examples.append(example)
    return name, examples


def _read_target_rows(path: Path, target_format: str) -> list[dict[str, Any]]:
    if target_format not in {"archer-json", "bird-json"}:
        raise ValueError(f"unsupported target format: {target_format}")
    rows = _target_rows_from_payload(_read_json(path))
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"target row {index} must be an object")
        missing = sorted({"db_id", "question"} - row.keys())
        if missing:
            raise ValueError(
                f"target row {index} missing required columns: {', '.join(missing)}"
            )
    return rows


def _target_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("examples"), list):
        return payload["examples"]
    raise ValueError("target JSON must contain a list")


def audit_selection(selection_path: Path) -> dict[str, Any]:
    """Print and return deterministic diagnostics for a selection artifact."""
    payload = _read_json(Path(selection_path))
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("selection JSON must contain a records list")
    records = payload["records"]

    fewer = sum(
        1 for record in records if len(_record_examples(record)) < 3
    )
    more = sum(
        1 for record in records if len(_record_examples(record)) > 3
    )
    duplicate_count = 0
    self_selection_count = 0
    distances: list[float] = []
    structure_similarities: list[float] = []
    for record in records:
        examples = _record_examples(record)
        source_ids = [
            example.get("source_id")
            for example in examples
            if isinstance(example, dict)
        ]
        duplicate_count += len(source_ids) - len(set(source_ids))
        target_source_id = record.get("target_source_id")
        if target_source_id is not None:
            self_selection_count += source_ids.count(target_source_id)
        for example in examples:
            if isinstance(example, dict):
                distance = example.get("distance")
                if isinstance(distance, (int, float)) and not isinstance(distance, bool):
                    distances.append(float(distance))
                structure_similarity = example.get("structure_similarity")
                if (
                    isinstance(structure_similarity, (int, float))
                    and not isinstance(structure_similarity, bool)
                ):
                    structure_similarities.append(float(structure_similarity))

    if distances:
        distance_summary: dict[str, float | None] = {
            "minimum": min(distances),
            "median": statistics.median(distances),
            "maximum": max(distances),
        }
    else:
        distance_summary = {"minimum": None, "median": None, "maximum": None}
    if structure_similarities:
        structure_summary: dict[str, float | None] = {
            "minimum": min(structure_similarities),
            "median": statistics.median(structure_similarities),
            "maximum": max(structure_similarities),
        }
    else:
        structure_summary = {"minimum": None, "median": None, "maximum": None}
    samples = sorted(
        records,
        key=lambda record: str(record.get("target_key", "")),
    )[:10]
    report = {
        "record_count": len(records),
        "fewer_than_3": fewer,
        "more_than_3": more,
        "duplicated_source_ids": duplicate_count,
        "self_selection_count": self_selection_count,
        "distance": distance_summary,
        "sample_selections": samples,
    }
    retrieval = payload.get("retrieval")
    if isinstance(retrieval, dict):
        report["retrieval"] = retrieval
        report["structure_similarity"] = structure_summary

    print(f"record count: {report['record_count']}")
    print(f"records with fewer than 3 examples: {fewer}")
    print(f"records with more than 3 examples: {more}")
    print(f"duplicated source IDs: {duplicate_count}")
    print(f"self-selection count: {self_selection_count}")
    print(
        "distance min/median/max: "
        f"{distance_summary['minimum']} / {distance_summary['median']} / "
        f"{distance_summary['maximum']}"
    )
    if isinstance(retrieval, dict):
        print(f"retrieval strategy: {retrieval.get('strategy')}")
        if "mean_structure_similarity_semantic_top_k" in retrieval:
            print(
                "mean structure similarity semantic/SFS top-k: "
                f"{retrieval['mean_structure_similarity_semantic_top_k']} / "
                f"{retrieval['mean_structure_similarity_sfs_top_k']}"
            )
        print(
            "structure similarity min/median/max: "
            f"{structure_summary['minimum']} / {structure_summary['median']} / "
            f"{structure_summary['maximum']}"
        )
    print("deterministic sample selections:")
    print(json.dumps(samples, ensure_ascii=False, indent=2, sort_keys=True))
    return report


def _record_examples(record: Any) -> list[Any]:
    if not isinstance(record, dict) or not isinstance(record.get("examples"), list):
        return []
    return record["examples"]


def _optional_source_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("source_id")
    if value is None:
        return None
    return _required_string(value, "source_id", "target")


def _target_identity(db_id: str, question: str) -> tuple[str, str]:
    """Return the normalized pair whose digest is produced by ``sample_key``."""
    return (
        db_id.replace("\r\n", "\n").replace("\r", "\n").strip(),
        question.replace("\r\n", "\n").replace("\r", "\n").strip(),
    )


def _required_string(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires non-empty {field}")
    return value.strip()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {path}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_fewshot",
        description="Build deterministic RSL-compatible few-shot selections.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    corpus = commands.add_parser("corpus", help="convert a training corpus")
    corpus.add_argument("--input", type=Path, required=True)
    corpus.add_argument(
        "--format",
        dest="input_format",
        choices=("archer-json", "bird-parquet"),
        required=True,
    )
    corpus.add_argument("--name", required=True)
    corpus.add_argument("--output", type=Path, required=True)

    select = commands.add_parser("select", help="embed and select top-k examples")
    select.add_argument("--corpus", type=Path, required=True)
    select.add_argument("--targets", type=Path, required=True)
    select.add_argument(
        "--target-format",
        choices=("archer-json", "bird-json"),
        required=True,
    )
    select.add_argument("--encoder", required=True)
    select.add_argument("--k", type=int, default=3)
    select.add_argument("--output", type=Path, required=True)

    rerank_sfs = commands.add_parser(
        "rerank-sfs",
        help="rerank a semantic candidate pool by draft SQL structure",
    )
    rerank_sfs.add_argument("--selection", type=Path, required=True)
    rerank_sfs.add_argument("--targets", type=Path, required=True)
    rerank_sfs.add_argument("--draft-predictions", type=Path, required=True)
    rerank_sfs.add_argument("--candidate-k", type=int, default=30)
    rerank_sfs.add_argument("--k", type=int, default=3)
    rerank_sfs.add_argument("--output", type=Path, required=True)

    audit = commands.add_parser("audit", help="audit a selection artifact")
    audit.add_argument("--selection", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "corpus":
        payload = build_corpus(
            input_path=args.input,
            input_format=args.input_format,
            name=args.name,
            output_path=args.output,
        )
        print(f"wrote {args.output} ({len(payload['examples'])} examples)")
    elif args.command == "select":
        payload = build_selection(
            corpus_path=args.corpus,
            targets_path=args.targets,
            target_format=args.target_format,
            encoder=args.encoder,
            k=args.k,
            output_path=args.output,
        )
        print(
            f"wrote {args.output} "
            f"({len(payload['records'])} unique records, k={args.k})"
        )
    elif args.command == "rerank-sfs":
        payload = build_sfs_selection(
            semantic_selection_path=args.selection,
            targets_path=args.targets,
            draft_predictions_path=args.draft_predictions,
            output_path=args.output,
            candidate_k=args.candidate_k,
            k=args.k,
        )
        retrieval = payload["retrieval"]
        print(
            f"wrote {args.output} "
            f"({len(payload['records'])} unique records, k={args.k}, "
            f"fallbacks={retrieval['fallback_count']})"
        )
        print(
            "semantic selection sha256: "
            f"{retrieval['semantic_selection_sha256']}"
        )
        print(
            "draft predictions sha256: "
            f"{retrieval['draft_predictions_sha256']}"
        )
        print(f"targets sha256: {retrieval['targets_sha256']}")
        print(
            "mean structure similarity semantic/SFS top-k: "
            f"{retrieval['mean_structure_similarity_semantic_top_k']} / "
            f"{retrieval['mean_structure_similarity_sfs_top_k']}"
        )
    else:
        audit_selection(args.selection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
