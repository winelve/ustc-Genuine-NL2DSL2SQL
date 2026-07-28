"""Prepare and run a fixed 80-question DPC pilot on BIRD."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import config
from archer_eval.data import load_dataset, load_predictions, resolve_dataset
from model.dpc_pilot.prepare import build_pilot_manifest
from model.dpc_pilot.runner import (
    DEFAULT_OFFICIAL_ROOT,
    _sha256,
    bootstrap_official_dpc,
    run_offline_self_test,
    run_pilot,
    write_json_atomic,
)


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
DEFAULT_MANIFEST = config.DATA_DIR / "dpc" / "bird_dev_dpc80.json"
DEFAULT_OUTPUT = (
    config.PREDICTIONS_DIR
    / "bird"
    / "bird-pro-t-dpc80_bird_dev.json"
)
DEFAULT_CHECKPOINT = (
    config.PREDICTIONS_DIR
    / "bird"
    / "bird-pro-t-dpc80_bird_dev.partial.json"
)


def _prepare(args) -> int:
    dataset_path = resolve_dataset(args.data)
    samples = load_dataset(dataset_path)
    direct = load_predictions(args.direct, expected_len=len(samples))
    dsl = load_predictions(args.dsl, expected_len=len(samples))
    routes = json.loads(Path(args.routes).read_text(encoding="utf-8"))
    sources = {
        "dataset_sha256": _sha256(dataset_path),
        "direct_sha256": _sha256(args.direct),
        "dsl_sha256": _sha256(args.dsl),
        "routes_sha256": _sha256(args.routes),
    }
    manifest = build_pilot_manifest(
        samples=samples,
        routes=routes,
        direct_predictions=direct,
        dsl_predictions=dsl,
        size=args.size,
        seed=args.seed,
        sources=sources,
    )
    write_json_atomic(args.manifest, manifest)
    print(
        f"pairwise {manifest['pairwise_total']}; selected {manifest['size']}; "
        f"strata {manifest['strata_selected']}"
    )
    print(f"wrote {args.manifest}")
    return 0


def _run(args) -> int:
    run_pilot(
        manifest_path=args.manifest,
        dsl_path=args.dsl,
        output_path=args.out,
        checkpoint_path=args.checkpoint,
        db_root=args.db_dir or config.db_dir_for(args.data),
        limit=args.limit,
        concurrency=args.concurrency,
        model_name=args.model,
        thinking=args.thinking == "enabled",
        max_tokens=args.max_tokens,
        max_correction_attempts=args.max_correction_attempts,
        sql_timeout=args.sql_timeout,
        python_timeout=args.python_timeout,
        epsilon=args.epsilon,
        official_root=args.official_root,
    )
    return 0


def _bootstrap(args) -> int:
    root = bootstrap_official_dpc(args.official_root)
    print(f"official DPC ready at {root}")
    print(
        "install dependencies: "
        r".\.venv\Scripts\python.exe -m pip install "
        "-r requirements-dpc.txt"
    )
    return 0


def _self_test(args) -> int:
    result = run_offline_self_test(args.official_root)
    print(
        "offline DPC self-test: "
        f"winner={result['winner']}; "
        f"reason={result['selection_reason']}; "
        f"scripted_calls={result['scripted_calls']}"
    )
    return 0 if result["winner"] == "direct" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Low-cost DPC-1x1 pilot over fixed BIRD disagreements."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser(
        "bootstrap",
        help="checkout the reviewed official DPC commit",
    )
    bootstrap.add_argument(
        "--official-root",
        type=Path,
        default=DEFAULT_OFFICIAL_ROOT,
    )
    bootstrap.set_defaults(handler=_bootstrap)

    self_test = sub.add_parser(
        "self-test",
        help="run the official DPC pipeline without an API key",
    )
    self_test.add_argument(
        "--official-root",
        type=Path,
        default=DEFAULT_OFFICIAL_ROOT,
    )
    self_test.set_defaults(handler=_self_test)

    prepare = sub.add_parser("prepare", help="build the fixed gold-free pilot")
    prepare.add_argument("--data", default="bird_dev")
    prepare.add_argument("--direct", type=Path, default=DEFAULT_DIRECT)
    prepare.add_argument("--dsl", type=Path, default=DEFAULT_DSL)
    prepare.add_argument("--routes", type=Path, default=DEFAULT_ROUTES)
    prepare.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    prepare.add_argument("--size", type=int, default=80)
    prepare.add_argument("--seed", default="bird-dpc80-v1")
    prepare.set_defaults(handler=_prepare)

    run = sub.add_parser("run", help="run/resume official DPC on the pilot")
    run.add_argument("--data", default="bird_dev")
    run.add_argument("--dsl", type=Path, default=DEFAULT_DSL)
    run.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    run.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    run.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    run.add_argument("--db-dir", type=Path)
    run.add_argument(
        "--official-root",
        type=Path,
        default=DEFAULT_OFFICIAL_ROOT,
    )
    run.add_argument("--limit", type=int)
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--model", default="deepseek-v4-pro")
    run.add_argument(
        "--thinking",
        choices=["enabled", "disabled"],
        default="disabled",
    )
    run.add_argument("--max-tokens", type=int, default=4096)
    run.add_argument("--max-correction-attempts", type=int, default=1)
    run.add_argument("--sql-timeout", type=int, default=30)
    run.add_argument("--python-timeout", type=int, default=15)
    run.add_argument("--epsilon", type=float, default=0.05)
    run.set_defaults(handler=_run)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
