"""Export Direct+FS vs DSL+FS execution disagreements for manual analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import config
from archer_eval.data import load_dataset, load_predictions, resolve_dataset


DEFAULT_DIRECT = (
    config.PREDICTIONS_DIR
    / "bird"
    / "bird-pro-t-direct-fs_bird_dev.json"
)
DEFAULT_DSL = (
    config.PREDICTIONS_DIR
    / "bird"
    / "bird-pro-t-dsl-fs_bird_dev.json"
)
DEFAULT_ROUTES = (
    config.PREDICTIONS_DIR
    / "bird"
    / "bird-pro-t-fs-sel_bird_dev.trace.json"
)
DEFAULT_DIRECT_RESULTS = (
    config.RESULTS_DIR
    / "bird"
    / "bird_dev_bird-pro-t-direct-fs_bird_dev.json"
)
DEFAULT_DSL_RESULTS = (
    config.RESULTS_DIR
    / "bird"
    / "bird_dev_bird-pro-t-dsl-fs_bird_dev.json"
)
DEFAULT_OUTPUT = (
    config.ROOT
    / "analysis"
    / "bird_direct_dsl_fs_disagreements.json"
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _label(direct_match: bool, dsl_match: bool) -> str:
    if direct_match and dsl_match:
        return "both"
    if direct_match:
        return "direct-fs"
    if dsl_match:
        return "direct-dsl-fs"
    return "neither"


def export_disagreements(
    *,
    data: str,
    direct_path: Path,
    dsl_path: Path,
    routes_path: Path,
    direct_results_path: Path,
    dsl_results_path: Path,
    output_path: Path,
) -> dict:
    samples = load_dataset(resolve_dataset(data))
    direct = load_predictions(direct_path, expected_len=len(samples))
    dsl = load_predictions(dsl_path, expected_len=len(samples))
    routes = _read_json(routes_path)
    direct_results = _read_json(direct_results_path)["samples"]
    dsl_results = _read_json(dsl_results_path)["samples"]

    lengths = {
        len(samples),
        len(routes),
        len(direct_results),
        len(dsl_results),
    }
    if len(lengths) != 1:
        raise ValueError("dataset, routes, predictions, and results must align")

    records = []
    for index, (sample, route) in enumerate(zip(samples, routes)):
        if route.get("route") != "pairwise":
            continue
        direct_match = bool(direct_results[index]["match"])
        dsl_match = bool(dsl_results[index]["match"])
        records.append(
            {
                "question_no": index + 1,
                "question_id": sample.extras.get("question_id", index),
                "dataset_index": index,
                "db_id": sample.db_id,
                "difficulty": sample.extras.get("difficulty", ""),
                "question": sample.question,
                "evidence": sample.commonsense_knowledge or "",
                "direct-fs": direct[index],
                "direct-dsl-fs": dsl[index],
                "answer": sample.query,
                "correctness": {
                    "direct-fs": direct_match,
                    "direct-dsl-fs": dsl_match,
                    "label": _label(direct_match, dsl_match),
                },
            }
        )

    artifact = {
        "format": "bird-direct-dsl-fs-disagreements-v1",
        "count": len(records),
        "field_notes": {
            "question_no": "1-based position in BIRD dev",
            "question_id": "official BIRD question_id",
            "direct-fs": str(direct_path),
            "direct-dsl-fs": str(dsl_path),
            "answer": "gold SQL from data/bird/dev.json",
            "correctness.label": (
                "one of direct-fs, direct-dsl-fs, both, neither"
            ),
        },
        "records": records,
    }
    _write_json_atomic(output_path, artifact)
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export BIRD Direct+FS/DSL+FS pairwise disagreements."
    )
    parser.add_argument("--data", default="bird_dev")
    parser.add_argument("--direct", type=Path, default=DEFAULT_DIRECT)
    parser.add_argument("--dsl", type=Path, default=DEFAULT_DSL)
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES)
    parser.add_argument(
        "--direct-results",
        type=Path,
        default=DEFAULT_DIRECT_RESULTS,
    )
    parser.add_argument(
        "--dsl-results",
        type=Path,
        default=DEFAULT_DSL_RESULTS,
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    artifact = export_disagreements(
        data=args.data,
        direct_path=args.direct,
        dsl_path=args.dsl,
        routes_path=args.routes,
        direct_results_path=args.direct_results,
        dsl_results_path=args.dsl_results,
        output_path=args.out,
    )
    counts: dict[str, int] = {}
    for record in artifact["records"]:
        label = record["correctness"]["label"]
        counts[label] = counts.get(label, 0) + 1
    print(f"wrote {args.out} ({artifact['count']} records)")
    print(f"correctness {dict(sorted(counts.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
