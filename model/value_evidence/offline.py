"""Command-line preparation of fixed CHESS-IR value-evidence artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

import config
from archer_eval.data import load_dataset, resolve_dataset
from archer_eval.evaluate import find_db_file
from model.fewshot.store import sample_key

from .index import build_database_index, file_sha256
from .keywords import DeepSeekKeywordExtractor, build_keyword_artifact
from .retrieve import (
    DEFAULT_PARAMETERS,
    build_selection_artifact,
    encoder_checksum,
)
from .store import ValueEvidenceStore
from .store import STRATEGY_V1, STRATEGY_V2


DEFAULT_ENCODER = (
    config.FEWSHOT_DIR / "models" / "all-mpnet-base-v2"
)


def _load_encoder(path: str | Path):
    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:  # pragma: no cover - offline environment
        raise RuntimeError(
            "CHESS-IR offline embedding requires requirements-fewshot.txt "
            "in a Python 3.11/3.12 environment"
        ) from exc
    return SentenceTransformer(str(path), device="cpu")


def _value_root() -> Path:
    return getattr(config, "VALUE_EVIDENCE_DIR", config.DATA_DIR / "value_evidence")


def _dataset_parts(name: str):
    path = resolve_dataset(name)
    return path, load_dataset(path), config.db_dir_for(name)


def _column_docs(db_id: str, db_root: Path) -> list[dict[str, str]]:
    from bird.extras import load_column_docs

    nested = load_column_docs(db_id, db_root)
    output = []
    for columns in nested.values():
        for doc in columns.values():
            parts = [
                value
                for value in (
                    doc.nl_name,
                    doc.description,
                    doc.data_format,
                    doc.value_description,
                )
                if value
            ]
            if parts:
                output.append(
                    {
                        "table": doc.table,
                        "column": doc.column,
                        "text": ". ".join(" ".join(value.split()) for value in parts),
                    }
                )
    return output


def command_index(args) -> None:
    _, samples, db_root = _dataset_parts(args.data)
    db_ids = list(dict.fromkeys(sample.db_id for sample in samples))
    docs_by_db = {
        db_id: _column_docs(db_id, db_root)
        if args.data.startswith("bird")
        else []
        for db_id in db_ids
    }
    encoder = (
        _load_encoder(args.encoder)
        if any(docs_by_db.values())
        else None
    )
    encoder_sha256 = (
        encoder_checksum(args.encoder) if encoder is not None else ""
    )
    root = _value_root() / "indexes" / args.data
    for number, db_id in enumerate(db_ids, 1):
        db_path = find_db_file(db_root, db_id)
        metadata = build_database_index(
            db_path,
            root / db_id,
            column_docs=docs_by_db[db_id],
            encoder=encoder,
            encoder_name="sentence-transformers/all-mpnet-base-v2",
            encoder_sha256=encoder_sha256,
        )
        print(
            f"index {number}/{len(db_ids)} {db_id}: "
            f"{metadata['value_count']} values, "
            f"{len(docs_by_db[db_id])} descriptions"
        )


def command_keywords(args) -> None:
    path, samples, _ = _dataset_parts(args.data)
    output = _value_root() / "keywords" / f"{args.data}.json"
    payload = build_keyword_artifact(
        samples,
        output_path=output,
        dataset=args.data,
        dataset_sha256=file_sha256(path),
        extractor=DeepSeekKeywordExtractor(),
        chunk=args.chunk,
        concurrency=args.concurrency,
    )
    print(
        f"wrote {output} ({len(payload['records'])} records, "
        f"{payload['usage']['total_tokens']} tokens)"
    )


def command_select(args) -> None:
    encoder = _load_encoder(args.encoder)
    suffix = "_v2" if args.strategy == STRATEGY_V2 else ""
    output_name = args.output or (
        f"bird_dev_chess_ir{suffix}.json"
        if args.data.startswith("bird")
        else f"archer_{args.data}_chess_ir{suffix}.json"
    )
    output = _value_root() / "selections" / output_name
    payload = build_selection_artifact(
        _value_root() / "keywords" / f"{args.data}.json",
        _value_root() / "indexes" / args.data,
        output,
        encoder,
        encoder_name="sentence-transformers/all-mpnet-base-v2",
        encoder_path=args.encoder,
        parameters=DEFAULT_PARAMETERS,
        strategy=args.strategy,
    )
    values = sum(len(record["values"]) for record in payload["records"])
    contexts = sum(len(record["contexts"]) for record in payload["records"])
    print(
        f"wrote {output} ({len(payload['records'])} records, "
        f"{values} values, {contexts} contexts)"
    )


def command_audit(args) -> None:
    store = ValueEvidenceStore.from_path(Path(args.path))
    dataset_path, samples, _ = _dataset_parts(args.data)
    expected_keys = {
        sample_key(sample.db_id, sample.question) for sample in samples
    }
    audit_selection(
        store,
        dataset=args.data,
        dataset_sha256=file_sha256(dataset_path),
        expected_target_keys=expected_keys,
        expected_strategy=args.strategy,
    )
    records = list(store.records.values())
    missing_values = sum(not record.values for record in records)
    print(
        f"valid {store.strategy}: {len(records)} records; "
        f"{sum(len(record.values) for record in records)} values; "
        f"{sum(len(record.contexts) for record in records)} contexts; "
        f"{missing_values} records without values"
    )


def audit_selection(
    store: ValueEvidenceStore,
    *,
    dataset: str,
    dataset_sha256: str,
    expected_target_keys: set[str],
    expected_strategy: str | None = None,
) -> dict[str, int]:
    """Verify metadata plus exact unique-target coverage before online use."""
    if store.dataset != dataset:
        raise ValueError(
            f"artifact dataset {store.dataset!r} does not match {dataset!r}"
        )
    if store.dataset_sha256 != dataset_sha256:
        raise ValueError("artifact dataset checksum does not match target data")
    if expected_strategy is not None and store.strategy != expected_strategy:
        raise ValueError(
            f"artifact strategy {store.strategy!r} does not match "
            f"{expected_strategy!r}"
        )
    if store.strategy == STRATEGY_V2:
        expected_threshold = float(DEFAULT_PARAMETERS["embedding_threshold"])
        actual_threshold = float(store.parameters["embedding_threshold"])
        if actual_threshold != expected_threshold:
            raise ValueError(
                "v2 embedding_threshold must be "
                f"{expected_threshold}, got {actual_threshold}"
            )
        below = sum(
            value.embedding_similarity < expected_threshold
            for record in store.records.values()
            for value in record.values
        )
        if below:
            raise ValueError(
                f"v2 artifact has {below} values below embedding_threshold"
            )
    actual = set(store.records)
    missing = expected_target_keys - actual
    extra = actual - expected_target_keys
    if missing or extra:
        raise ValueError(
            "artifact target coverage mismatch: "
            f"{len(missing)} missing, {len(extra)} extra"
        )
    return {
        "records": len(actual),
        "values": sum(len(record.values) for record in store.records.values()),
        "contexts": sum(
            len(record.contexts) for record in store.records.values()
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="model.value_evidence.offline",
        description="Prepare fixed CHESS-IR value evidence",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    index = subparsers.add_parser("index", help="build per-database value indexes")
    index.add_argument("--data", required=True)
    index.add_argument("--encoder", default=str(DEFAULT_ENCODER))
    index.set_defaults(handler=command_index)

    keywords = subparsers.add_parser(
        "keywords", help="extract resumable DeepSeek keywords"
    )
    keywords.add_argument("--data", required=True)
    keywords.add_argument("--chunk", type=int, default=50)
    keywords.add_argument("--concurrency", type=int, default=10)
    keywords.set_defaults(handler=command_keywords)

    select = subparsers.add_parser(
        "select", help="retrieve values/descriptions and build a fixed artifact"
    )
    select.add_argument("--data", required=True)
    select.add_argument("--encoder", default=str(DEFAULT_ENCODER))
    select.add_argument("--output", help="selection file name under selections/")
    select.add_argument(
        "--strategy",
        choices=(STRATEGY_V1, STRATEGY_V2),
        default=STRATEGY_V1,
        help="v2 removes the legacy substring filter bypass",
    )
    select.set_defaults(handler=command_select)

    audit = subparsers.add_parser("audit", help="strictly validate a selection")
    audit.add_argument("--path", required=True)
    audit.add_argument("--data", required=True)
    audit.add_argument(
        "--strategy",
        choices=(STRATEGY_V1, STRATEGY_V2),
        default=STRATEGY_V1,
        help="expected artifact strategy (defaults to v1)",
    )
    audit.set_defaults(handler=command_audit)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
