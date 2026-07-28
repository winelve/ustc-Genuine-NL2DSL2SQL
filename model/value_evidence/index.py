"""Offline CHESS-compatible database value and catalog indexing."""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
from typing import Any, Iterable, Mapping

from archer_eval.execution import connect_ro


INDEX_FORMAT_VERSION = 1
_SKIP_COLUMN_PARTS = (
    "_id",
    " id",
    "url",
    "email",
    "web",
    "time",
    "phone",
    "date",
    "address",
)


def extract_unique_text_values(
    db_path: str | Path,
) -> dict[str, dict[str, list[str]]]:
    """Extract CHESS-indexable distinct TEXT values using a read-only DB."""
    conn = connect_ro(db_path)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        ).fetchall()
        output: dict[str, dict[str, list[str]]] = {}
        for (table,) in tables:
            columns = conn.execute(
                f"PRAGMA table_info({_quote_literal(table)})"
            ).fetchall()
            table_values: dict[str, list[str]] = {}
            for column in columns:
                column_name = str(column[1])
                declared_type = str(column[2] or "")
                is_primary_key = bool(column[5])
                if is_primary_key or "TEXT" not in declared_type.upper():
                    continue
                if _skip_column_name(column_name):
                    continue
                quoted_table = _quote_identifier(table)
                quoted_column = _quote_identifier(column_name)
                sum_lengths, distinct_count = conn.execute(
                    "SELECT SUM(LENGTH(unique_value)), COUNT(unique_value) "
                    "FROM ("
                    f"SELECT DISTINCT {quoted_column} AS unique_value "
                    f"FROM {quoted_table} WHERE {quoted_column} IS NOT NULL"
                    ")"
                ).fetchone()
                if sum_lengths is None or not distinct_count:
                    continue
                average_length = float(sum_lengths) / int(distinct_count)
                include = (
                    ("name" in column_name.casefold() and sum_lengths < 5_000_000)
                    or (sum_lengths < 2_000_000 and average_length < 25)
                    or distinct_count < 100
                )
                if not include:
                    continue
                rows = conn.execute(
                    f"SELECT DISTINCT {quoted_column} FROM {quoted_table} "
                    f"WHERE {quoted_column} IS NOT NULL "
                    f"ORDER BY {quoted_column} COLLATE BINARY"
                ).fetchall()
                table_values[column_name] = [str(row[0]) for row in rows]
            output[str(table)] = table_values
        return output
    finally:
        conn.close()


def character_ngrams(value: str, n_gram: int) -> tuple[str, ...]:
    if isinstance(n_gram, bool) or not isinstance(n_gram, int) or n_gram <= 0:
        raise ValueError("n_gram must be a positive integer")
    if not value:
        return ("",)
    if len(value) < n_gram:
        return (value,)
    return tuple(
        value[index : index + n_gram]
        for index in range(len(value) - n_gram + 1)
    )


def normalise_lsh_text(value: str) -> str:
    """Make LSH recall case-insensitive before the irreversible hash step."""
    return value.casefold()


def create_minhash(value: str, *, signature_size: int, n_gram: int):
    try:
        from datasketch import MinHash
    except ModuleNotFoundError as exc:  # pragma: no cover - offline environment
        raise RuntimeError(
            "value indexing requires datasketch; install "
            "requirements-fewshot.txt in the offline environment"
        ) from exc
    minhash = MinHash(num_perm=signature_size)
    for gram in character_ngrams(normalise_lsh_text(value), n_gram):
        minhash.update(gram.encode("utf-8"))
    return minhash


def build_lsh(
    unique_values: Mapping[str, Mapping[str, Iterable[str]]],
    *,
    signature_size: int = 100,
    n_gram: int = 3,
    threshold: float = 0.01,
):
    try:
        from datasketch import MinHashLSH
    except ModuleNotFoundError as exc:  # pragma: no cover - offline environment
        raise RuntimeError(
            "value indexing requires datasketch; install "
            "requirements-fewshot.txt in the offline environment"
        ) from exc
    lsh = MinHashLSH(threshold=threshold, num_perm=signature_size)
    entries: dict[str, tuple[Any, str, str, str]] = {}
    index = 0
    for table, columns in unique_values.items():
        for column, values in columns.items():
            for value in values:
                key = f"v{index:09d}"
                minhash = create_minhash(
                    value, signature_size=signature_size, n_gram=n_gram
                )
                entries[key] = (minhash, table, column, value)
                lsh.insert(key, minhash)
                index += 1
    return lsh, entries


def build_index_metadata(
    db_path: str | Path,
    *,
    unique_values: Mapping[str, Mapping[str, Iterable[str]]],
    signature_size: int,
    n_gram: int,
    lsh_threshold: float,
) -> dict[str, Any]:
    path = Path(db_path)
    value_count = sum(
        len(list(values))
        for columns in unique_values.values()
        for values in columns.values()
    )
    return {
        "format_version": INDEX_FORMAT_VERSION,
        "db_id": path.stem,
        "database_sha256": file_sha256(path),
        "signature_size": signature_size,
        "n_gram": n_gram,
        "lsh_threshold": lsh_threshold,
        "value_count": value_count,
        "column_count": sum(len(columns) for columns in unique_values.values()),
    }


def build_database_index(
    db_path: str | Path,
    output_dir: str | Path,
    *,
    column_docs: Iterable[Mapping[str, str]] = (),
    encoder: Any | None = None,
    encoder_name: str = "",
    encoder_sha256: str = "",
    signature_size: int = 100,
    n_gram: int = 3,
    lsh_threshold: float = 0.01,
) -> dict[str, Any]:
    """Build all database-level files used by the offline selector."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    unique_values = extract_unique_text_values(db_path)
    lsh, entries = build_lsh(
        unique_values,
        signature_size=signature_size,
        n_gram=n_gram,
        threshold=lsh_threshold,
    )
    metadata = build_index_metadata(
        db_path,
        unique_values=unique_values,
        signature_size=signature_size,
        n_gram=n_gram,
        lsh_threshold=lsh_threshold,
    )

    (output / "unique_values.json").write_text(
        json.dumps(unique_values, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    with (output / "lsh.pkl").open("wb") as file:
        pickle.dump({"lsh": lsh, "entries": entries}, file)

    docs = [dict(item) for item in column_docs]
    metadata["contexts_sha256"] = hashlib.sha256(
        json.dumps(
            docs, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    metadata["context_encoder"] = encoder_name if docs else ""
    metadata["context_encoder_sha256"] = encoder_sha256 if docs else ""
    (output / "contexts.json").write_text(
        json.dumps(docs, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    if docs:
        if encoder is None:
            raise ValueError("encoder is required when column_docs are provided")
        if not encoder_name or not encoder_sha256:
            raise ValueError(
                "encoder_name and encoder_sha256 are required with column_docs"
            )
        try:
            import numpy as np
        except ModuleNotFoundError as exc:  # pragma: no cover - offline environment
            raise RuntimeError(
                "context indexing requires NumPy; install "
                "requirements-fewshot.txt in the offline environment"
            ) from exc
        embeddings = encoder.encode(
            [item["text"] for item in docs],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        np.save(output / "context_embeddings.npy", embeddings)

    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metadata


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skip_column_name(column_name: str) -> bool:
    lower = column_name.casefold()
    return (
        lower in {"id", "uuid", "guid"}
        or lower.endswith(("_ids", " ids", "_uuid", " uuid", "_guid", " guid"))
        or any(part in lower for part in _SKIP_COLUMN_PARTS)
        or column_name.endswith(("Id", "ID", "Ids", "IDs"))
    )


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
