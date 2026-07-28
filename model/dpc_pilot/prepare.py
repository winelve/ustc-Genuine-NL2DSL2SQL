"""Build a fixed DPC pilot and merge its partial decisions into DSL+FS."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import math
from typing import Any, Mapping, Sequence

from archer_eval.data import Sample


def _question_id(sample: Sample, index: int) -> str:
    return str(sample.extras.get("question_id", index))


def _difficulty(sample: Sample) -> str:
    return str(sample.extras.get("difficulty") or "unknown").lower()


def _hash_rank(seed: str, question_id: str) -> str:
    return hashlib.sha256(f"{seed}\0{question_id}".encode("utf-8")).hexdigest()


def _stratified_quotas(
    counts: Mapping[str, int],
    size: int,
) -> dict[str, int]:
    """Allocate proportional quotas while retaining every non-empty stratum."""
    if size <= 0:
        raise ValueError("pilot size must be positive")
    total = sum(counts.values())
    if size > total:
        raise ValueError(
            f"pilot size ({size}) exceeds pairwise disagreements ({total})"
        )

    nonempty = sorted(key for key, value in counts.items() if value)
    ideals = {
        key: size * counts[key] / total
        for key in nonempty
    }
    quotas = {
        key: min(counts[key], math.floor(ideals[key]))
        for key in nonempty
    }
    unassigned = size - sum(quotas.values())

    priority = sorted(
        nonempty,
        key=lambda key: (
            -(ideals[key] - math.floor(ideals[key])),
            key,
        ),
    )
    while unassigned > 0:
        progressed = False
        for key in priority:
            if quotas[key] < counts[key]:
                quotas[key] += 1
                unassigned -= 1
                progressed = True
                if not unassigned:
                    break
        if not progressed:
            raise RuntimeError("unable to allocate pilot strata")

    # Preserve every difficulty when the pilot is large enough. Take the
    # replacement from the most over-represented stratum, deterministically.
    if size >= len(nonempty):
        for empty_key in [key for key in nonempty if quotas[key] == 0]:
            donors = [
                key
                for key in nonempty
                if quotas[key] > 1
            ]
            if not donors:
                break
            donor = max(
                donors,
                key=lambda key: (
                    quotas[key] - ideals[key],
                    quotas[key],
                    key,
                ),
            )
            quotas[donor] -= 1
            quotas[empty_key] = 1
    return quotas


def build_pilot_manifest(
    *,
    samples: Sequence[Sample],
    routes: Sequence[Mapping[str, Any]],
    direct_predictions: Sequence[str],
    dsl_predictions: Sequence[str],
    size: int,
    seed: str,
    sources: Mapping[str, str],
) -> dict[str, Any]:
    """Select fixed pairwise disagreements and put stronger DSL first."""
    lengths = {
        len(samples),
        len(routes),
        len(direct_predictions),
        len(dsl_predictions),
    }
    if len(lengths) != 1:
        raise ValueError("samples, routes, and predictions must align")

    by_difficulty: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, (sample, route, direct_sql, dsl_sql) in enumerate(
        zip(samples, routes, direct_predictions, dsl_predictions)
    ):
        if route.get("route") != "pairwise":
            continue
        qid = _question_id(sample, index)
        difficulty = _difficulty(sample)
        by_difficulty[difficulty].append(
            {
                "index": index,
                "question_id": qid,
                "db_id": sample.db_id,
                "difficulty": difficulty,
                "question": sample.question,
                "evidence": sample.commonsense_knowledge or "",
                # DPC execution clustering uses insertion order for a 1-vs-1
                # tie, so DSL must be first to make fallback conservative.
                "candidates": [dsl_sql, direct_sql],
            }
        )

    counts = {key: len(records) for key, records in by_difficulty.items()}
    quotas = _stratified_quotas(counts, size)
    selected: list[dict[str, Any]] = []
    for difficulty, records in by_difficulty.items():
        records.sort(
            key=lambda record: _hash_rank(seed, record["question_id"])
        )
        selected.extend(records[: quotas[difficulty]])
    selected.sort(key=lambda record: record["index"])

    candidate_map = {
        record["question_id"]: record["candidates"]
        for record in selected
    }
    return {
        "format": "bird-dpc-pilot-v1",
        "seed": seed,
        "size": size,
        "pairwise_total": sum(counts.values()),
        "strata_pairwise": dict(sorted(counts.items())),
        "strata_selected": dict(
            sorted(Counter(r["difficulty"] for r in selected).items())
        ),
        "sources": dict(sources),
        "records": selected,
        "candidate_map": candidate_map,
    }


def merge_dpc_results(
    dsl_baseline: Sequence[str],
    manifest: Mapping[str, Any],
    completed: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Merge completed pilot decisions; missing records safely stay on DSL."""
    merged = list(dsl_baseline)
    for record in manifest["records"]:
        qid = str(record["question_id"])
        result = completed.get(qid)
        if result is None:
            continue
        selected_sql = result.get("selected_sql")
        candidates = record["candidates"]
        if selected_sql not in candidates:
            raise ValueError(
                f"DPC result for question_id={qid} is not one of the fixed "
                "candidates"
            )
        index = int(record["index"])
        if index < 0 or index >= len(merged):
            raise ValueError(f"pilot index out of range: {index}")
        merged[index] = selected_sql
    return merged
