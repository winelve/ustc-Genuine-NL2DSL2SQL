"""Offline entity/context retrieval and deterministic VE-R controls."""

from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import pickle
from typing import Any, Iterable, Mapping, Sequence

from model.fewshot.store import sample_key

from .index import create_minhash, file_sha256
from .store import (
    FORMAT_VERSION,
    STRATEGY_V1,
    SUPPORTED_STRATEGIES,
)


DEFAULT_PARAMETERS: dict[str, int | float] = {
    "signature_size": 100,
    "n_gram": 3,
    "lsh_threshold": 0.01,
    "lsh_top_n": 10,
    "edit_threshold": 0.3,
    "embedding_threshold": 0.6,
    "max_values_per_column": 3,
    "max_values_total": 12,
    "max_context_columns": 8,
}
def keyword_variants(keywords: Iterable[str]) -> list[tuple[str, str]]:
    """Expand CHESS keywords while retaining the originating full phrase."""
    output: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in keywords:
        keyword = raw.strip()
        if not keyword:
            continue
        substrings = [keyword]
        for index, character in enumerate(keyword):
            if character == " ":
                substrings.extend(
                    (keyword[:index].strip(), keyword[index + 1 :].strip())
                )
        if "=" in keyword:
            value = keyword.split("=", 1)[1].strip()
            if value:
                substrings.append(value)
        for substring in substrings:
            if not substring:
                continue
            packet = (keyword, substring)
            if packet not in seen:
                output.append(packet)
                seen.add(packet)
    output.sort(
        key=lambda item: (item[0], len(item[1]), item[1]), reverse=True
    )
    return output


def postprocess_value_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    edit_threshold: float = 0.3,
    embedding_threshold: float = 0.6,
    max_values_per_column: int = 3,
    max_values_total: int = 12,
    preserve_substring_hits: bool = True,
) -> list[dict[str, Any]]:
    """Apply CHESS edit/embedding filters, relative filtering, dedupe and caps."""
    prepared: list[dict[str, Any]] = []
    for raw in candidates:
        value = str(raw["value"])
        substring = str(raw["substring"])
        lowered_value = value.casefold()
        lowered_substring = substring.casefold()
        exact_or_substring = (
            lowered_value == lowered_substring
            or lowered_substring in lowered_value
            or lowered_value in lowered_substring
        )
        edit = SequenceMatcher(None, lowered_substring, lowered_value).ratio()
        embedding = _unit_score(raw.get("embedding_similarity", 0.0))
        if edit < edit_threshold:
            continue
        if embedding < embedding_threshold and not (
            preserve_substring_hits and exact_or_substring
        ):
            continue
        prepared.append(
            {
                "table": str(raw["table"]),
                "column": str(raw["column"]),
                "value": value,
                "keyword": str(raw["keyword"]),
                "substring": substring,
                "lsh_similarity": _unit_score(raw.get("lsh_similarity", 0.0)),
                "edit_similarity": round(edit, 6),
                "embedding_similarity": round(embedding, 6),
                "exact_or_substring": exact_or_substring,
            }
        )

    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in prepared:
        key = (
            item["table"].casefold(),
            item["column"].casefold(),
            item["value"],
        )
        existing = deduped.get(key)
        if existing is None or _candidate_rank(item) > _candidate_rank(existing):
            deduped[key] = item

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in deduped.values():
        grouped.setdefault(
            (item["table"].casefold(), item["column"].casefold()), []
        ).append(item)

    retained: list[dict[str, Any]] = []
    for items in grouped.values():
        max_edit = max(item["edit_similarity"] for item in items)
        edit_relative = [
            item
            for item in items
            if preserve_substring_hits and item["exact_or_substring"]
            or item["edit_similarity"] >= 0.9 * max_edit
        ]
        max_embedding = max(
            item["embedding_similarity"] for item in edit_relative
        )
        relative = [
            item
            for item in edit_relative
            if preserve_substring_hits and item["exact_or_substring"]
            or item["embedding_similarity"] >= 0.9 * max_embedding
        ]
        relative.sort(key=_candidate_rank, reverse=True)
        retained.extend(relative[:max_values_per_column])

    retained.sort(key=_candidate_rank, reverse=True)
    return retained[:max_values_total]


def merge_context_candidates(
    candidates: Iterable[Mapping[str, Any]], *, max_columns: int = 8
) -> list[dict[str, Any]]:
    """Keep one highest-scoring description for each table/column."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in candidates:
        item = {
            "table": str(raw["table"]),
            "column": str(raw["column"]),
            "description": str(raw["description"]).strip(),
            "score": round(_unit_score(raw["score"]), 6),
        }
        if not item["description"]:
            continue
        key = (item["table"].casefold(), item["column"].casefold())
        if key not in best or item["score"] > best[key]["score"]:
            best[key] = item
    return sorted(
        best.values(),
        key=lambda item: (
            -item["score"],
            item["table"].casefold(),
            item["column"].casefold(),
        ),
    )[:max_columns]


def choose_control_value(
    unique_values: Mapping[str, Mapping[str, Sequence[str]]],
    *,
    table: str,
    column: str,
    relevant_value: str,
    target_key: str,
    slot: int,
) -> str:
    """Choose a stable pseudo-random closest-length value in the same column."""
    try:
        choices = unique_values[table][column]
    except KeyError as exc:
        raise KeyError(f"missing indexed values for {table}.{column}") from exc
    alternatives = [str(value) for value in choices if str(value) != relevant_value]
    if not alternatives:
        raise ValueError(
            f"no distinct control value is available for {table}.{column}"
        )
    best_distance = min(abs(len(value) - len(relevant_value)) for value in alternatives)
    closest = [
        value
        for value in alternatives
        if abs(len(value) - len(relevant_value)) == best_distance
    ]
    return min(
        closest,
        key=lambda value: hashlib.sha256(
            f"{target_key}\n{slot}\n{table}\n{column}\n{value}".encode("utf-8")
        ).hexdigest(),
    )


class DatabaseIndex:
    """Heavy offline adapter around one serialized database index."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.metadata = json.loads(
            (self.path / "metadata.json").read_text(encoding="utf-8")
        )
        self.unique_values = json.loads(
            (self.path / "unique_values.json").read_text(encoding="utf-8")
        )
        with (self.path / "lsh.pkl").open("rb") as file:
            packet = pickle.load(file)
        self.lsh = packet["lsh"]
        self.entries = packet["entries"]
        contexts_path = self.path / "contexts.json"
        self.contexts = (
            json.loads(contexts_path.read_text(encoding="utf-8"))
            if contexts_path.exists()
            else []
        )
        embeddings_path = self.path / "context_embeddings.npy"
        if embeddings_path.exists():
            import numpy as np

            self.context_embeddings = np.load(embeddings_path)
        else:
            self.context_embeddings = None

    def raw_value_candidates(
        self, keywords: Iterable[str], *, lsh_top_n: int
    ) -> list[dict[str, Any]]:
        signature_size = int(self.metadata["signature_size"])
        n_gram = int(self.metadata["n_gram"])
        output: list[dict[str, Any]] = []
        for keyword, substring in keyword_variants(keywords):
            query = create_minhash(
                substring, signature_size=signature_size, n_gram=n_gram
            )
            keys = self.lsh.query(query)
            ranked = sorted(
                keys,
                key=lambda key: (
                    -float(query.jaccard(self.entries[key][0])),
                    key,
                ),
            )[:lsh_top_n]
            for key in ranked:
                minhash, table, column, value = self.entries[key]
                output.append(
                    {
                        "table": table,
                        "column": column,
                        "value": value,
                        "keyword": keyword,
                        "substring": substring,
                        "lsh_similarity": float(query.jaccard(minhash)),
                    }
                )
        return output


def retrieve_record(
    keyword_record: Mapping[str, Any],
    database_index: DatabaseIndex,
    encoder: Any,
    *,
    parameters: Mapping[str, int | float] = DEFAULT_PARAMETERS,
    strategy: str = STRATEGY_V1,
) -> dict[str, Any]:
    """Retrieve one fixed runtime record from a keyword record and DB index."""
    raw = database_index.raw_value_candidates(
        keyword_record["keywords"], lsh_top_n=int(parameters["lsh_top_n"])
    )
    if raw:
        texts = []
        for item in raw:
            texts.extend((item["substring"], item["value"]))
        vectors = encoder.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        for index, item in enumerate(raw):
            score = float(vectors[2 * index] @ vectors[2 * index + 1])
            item["embedding_similarity"] = max(0.0, min(1.0, score))
    selected = postprocess_value_candidates(
        raw,
        edit_threshold=float(parameters["edit_threshold"]),
        embedding_threshold=float(parameters["embedding_threshold"]),
        max_values_per_column=int(parameters["max_values_per_column"]),
        max_values_total=int(parameters["max_values_total"]),
        preserve_substring_hits=strategy == STRATEGY_V1,
    )

    target_key = str(keyword_record["target_key"])
    values = []
    for slot, item in enumerate(selected):
        try:
            control_value = choose_control_value(
                database_index.unique_values,
                table=item["table"],
                column=item["column"],
                relevant_value=item["value"],
                target_key=target_key,
                slot=slot,
            )
        except ValueError:
            # Drop this slot from both VE and VE-R instead of creating a fake
            # control that is byte-identical to the relevant value.
            continue
        values.append(
            {
                "table": item["table"],
                "column": item["column"],
                "value": item["value"],
                "control_value": control_value,
                "keyword": item["keyword"],
                "edit_similarity": item["edit_similarity"],
                "embedding_similarity": item["embedding_similarity"],
            }
        )
    contexts = _retrieve_contexts(
        keyword_record, database_index, encoder, int(parameters["max_context_columns"])
    )
    return {
        "target_key": target_key,
        "db_id": keyword_record["db_id"],
        "question": keyword_record["question"],
        "keywords": list(keyword_record["keywords"]),
        "values": values,
        "contexts": contexts,
    }


def build_selection_artifact(
    keyword_path: str | Path,
    index_root: str | Path,
    output_path: str | Path,
    encoder: Any,
    *,
    encoder_name: str,
    encoder_path: str | Path,
    parameters: Mapping[str, int | float] = DEFAULT_PARAMETERS,
    strategy: str = STRATEGY_V1,
) -> dict[str, Any]:
    """Build the strict fixed artifact consumed by all Direct/DSL arms."""
    if strategy not in SUPPORTED_STRATEGIES:
        raise ValueError(f"unsupported value evidence strategy: {strategy!r}")
    keyword_file = Path(keyword_path)
    keyword_payload = json.loads(keyword_file.read_text(encoding="utf-8"))
    root = Path(index_root)
    indexes: dict[str, DatabaseIndex] = {}
    records = []
    selected_encoder_sha256 = encoder_checksum(encoder_path)
    for keyword_record in keyword_payload["records"]:
        db_id = keyword_record["db_id"]
        if db_id not in indexes:
            indexes[db_id] = DatabaseIndex(root / db_id)
        index = indexes[db_id]
        indexed_encoder = index.metadata.get("context_encoder_sha256", "")
        if index.contexts and indexed_encoder != selected_encoder_sha256:
            raise ValueError(
                f"context encoder checksum mismatch for database {db_id}"
            )
        records.append(
            retrieve_record(
                keyword_record,
                index,
                encoder,
                parameters=parameters,
                strategy=strategy,
            )
        )
    payload = {
        "format_version": FORMAT_VERSION,
        "strategy": strategy,
        "dataset": keyword_payload["dataset"],
        "dataset_sha256": keyword_payload["dataset_sha256"],
        "keywords_sha256": file_sha256(keyword_file),
        "encoder": encoder_name,
        "encoder_sha256": selected_encoder_sha256,
        "parameters": dict(parameters),
        "records": records,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def encoder_checksum(path_or_name: str | Path) -> str:
    path = Path(path_or_name)
    digest = hashlib.sha256()
    if path.exists() and path.is_dir():
        for file in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(file.relative_to(path).as_posix().encode("utf-8"))
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    elif path.exists():
        return file_sha256(path)
    else:
        digest.update(str(path_or_name).encode("utf-8"))
    return digest.hexdigest()


def _retrieve_contexts(
    keyword_record: Mapping[str, Any],
    database_index: DatabaseIndex,
    encoder: Any,
    max_columns: int,
) -> list[dict[str, Any]]:
    if not database_index.contexts or database_index.context_embeddings is None:
        return []
    query_texts = context_query_texts(keyword_record)
    vectors = encoder.encode(
        query_texts, normalize_embeddings=True, show_progress_bar=False
    )
    candidates = []
    for index, doc in enumerate(database_index.contexts):
        score = max(float(vector @ database_index.context_embeddings[index]) for vector in vectors)
        candidates.append(
            {
                "table": doc["table"],
                "column": doc["column"],
                "description": doc["text"],
                "score": max(0.0, min(1.0, score)),
            }
        )
    return merge_context_candidates(candidates, max_columns=max_columns)


def context_query_texts(keyword_record: Mapping[str, Any]) -> list[str]:
    """Build the approved question/evidence + keyword context queries."""
    question = str(keyword_record["question"]).strip()
    evidence = str(keyword_record.get("evidence") or "").strip()
    keywords = [
        str(value).strip()
        for value in keyword_record["keywords"]
        if str(value).strip()
    ]
    if not keywords:
        return [value for value in (question, evidence) if value]
    output = []
    for keyword in keywords:
        if question:
            output.append(f"{question} {keyword}")
        if evidence:
            output.append(f"{evidence} {keyword}")
    return output


def _candidate_rank(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        bool(item["exact_or_substring"]),
        float(item["edit_similarity"]),
        float(item["embedding_similarity"]),
        float(item["lsh_similarity"]),
        str(item["table"]).casefold(),
        str(item["column"]).casefold(),
        str(item["value"]),
    )


def _unit_score(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("similarity score must be finite")
    return max(0.0, min(1.0, number))
