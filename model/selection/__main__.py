"""Select between existing Direct+FS and DSL+FS prediction files.

Example:
    python -m model.selection --data bird_dev \
      --direct predictions/bird/bird-pro-t-direct-fs_bird_dev.json \
      --dsl predictions/bird/bird-pro-t-dsl-fs_bird_dev.json \
      --out predictions/bird/bird-pro-t-fs-sel_bird_dev.json
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import config
from archer_eval.data import load_dataset, load_predictions, resolve_dataset
from archer_eval.evaluate import find_db_file
from model.llm import ChatEndpoint
from model.selection.runner import select_all


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    temporary.replace(path)


def _default_endpoint() -> ChatEndpoint:
    return ChatEndpoint(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        key_env="DEEPSEEK_API_KEY",
        request_params={
            "temperature": 0.0,
            "max_tokens": 800,
            "extra_body": {"thinking": {"type": "disabled"}},
        },
    )


def run_selection(
    *,
    data: str,
    direct_path: str | Path,
    dsl_path: str | Path,
    out_path: str | Path,
    db_dir: str | Path | None = None,
    endpoint=None,
    concurrency: int = config.API_CONCURRENCY,
    progress: bool = True,
) -> tuple[list[str], list[dict]]:
    dataset_path = resolve_dataset(data)
    direct_path = Path(direct_path)
    dsl_path = Path(dsl_path)
    out_path = Path(out_path)

    samples = load_dataset(dataset_path)
    direct_predictions = load_predictions(direct_path, expected_len=len(samples))
    dsl_predictions = load_predictions(dsl_path, expected_len=len(samples))
    database_root = Path(db_dir) if db_dir else config.db_dir_for(data)
    db_paths = [find_db_file(database_root, sample.db_id) for sample in samples]

    predictions, traces = select_all(
        samples=samples,
        db_paths=db_paths,
        direct_predictions=direct_predictions,
        dsl_predictions=dsl_predictions,
        endpoint=endpoint or _default_endpoint(),
        concurrency=concurrency,
        progress=progress,
    )
    sources = {
        "dataset_sha256": _sha256(Path(dataset_path)),
        "direct_sha256": _sha256(direct_path),
        "dsl_sha256": _sha256(dsl_path),
    }
    for trace in traces:
        trace["sources"] = sources

    trace_path = out_path.with_name(out_path.stem + ".trace.json")
    _write_json_atomic(out_path, predictions)
    _write_json_atomic(trace_path, traces)

    routes = Counter(trace["route"] for trace in traces)
    api_calls = sum(trace["metrics"]["api_calls"] for trace in traces)
    elapsed = sum(trace["metrics"]["elapsed_seconds"] for trace in traces)
    usage = {}
    for field in config_usage_fields():
        values = [
            trace["metrics"]["usage"][field]
            for trace in traces
            if trace["metrics"]["usage"][field] is not None
        ]
        usage[field] = sum(values) if values else None
    print(f"routes {dict(sorted(routes.items()))}")
    print(f"selector api calls {api_calls}; summed question seconds {elapsed:.2f}")
    print(f"usage {json.dumps(usage, ensure_ascii=False)}")
    print(f"wrote {out_path}  ({len(predictions)}/{len(samples)})")
    print(f"wrote {trace_path}")
    return predictions, traces


def config_usage_fields() -> tuple[str, ...]:
    from model.metrics import TOKEN_FIELDS

    return TOKEN_FIELDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select between aligned Direct+FS and DSL+FS predictions."
    )
    parser.add_argument("--data", default="bird_dev")
    parser.add_argument("--direct", required=True)
    parser.add_argument("--dsl", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--db-dir")
    parser.add_argument("--concurrency", type=int, default=config.API_CONCURRENCY)
    args = parser.parse_args(argv)
    run_selection(
        data=args.data,
        direct_path=args.direct,
        dsl_path=args.dsl,
        out_path=args.out,
        db_dir=args.db_dir,
        concurrency=args.concurrency,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
