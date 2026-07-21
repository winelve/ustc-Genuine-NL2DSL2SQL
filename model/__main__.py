"""Stage-1 runner: run a registered model, write a standard prediction file.

    python -m model --model first_table --data en_dev          # generate only
    python -m model --model first_table --data en_dev --eval   # generate then evaluate

The runner loads the dataset, resolves database paths, calls the model per
sample, keeps output aligned with the dataset, and writes
predictions/<model>_<data>.json. Model classes only implement predict().
"""

from __future__ import annotations

import argparse
import json

import config
from archer_eval.data import load_dataset
from archer_eval.evaluate import evaluate, find_db_file
from archer_eval.report import make_meta, report_name, write_report
from model import MODELS


def main() -> None:
    parser = argparse.ArgumentParser(prog="model", description="Run a SQL generator on a dataset")
    parser.add_argument("--model", required=True, choices=sorted(MODELS),
                        help="registered model name (see model/__init__.py)")
    parser.add_argument("--data", required=True,
                        help=f"one of {', '.join(config.DATASETS)} or a JSON file path")
    parser.add_argument("--limit", type=int, help="only run the first N samples (smoke test)")
    parser.add_argument("--eval", action="store_true", help="evaluate right after generating")
    args = parser.parse_args()

    data_path = config.resolve_dataset(args.data)
    samples = load_dataset(data_path)
    if args.limit:
        samples = samples[: args.limit]

    generator = MODELS[args.model]()
    db_paths = [find_db_file(config.DB_DIR, s.db_id) for s in samples]
    print(f"{generator.name} on {data_path.name}: {len(samples)} samples")
    predictions = generator.predict_all(samples, db_paths)

    alias = args.data if args.data in config.DATASETS else data_path.stem
    out = config.PREDICTIONS_DIR / f"{generator.name}_{alias}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(predictions, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}")

    if args.eval:
        report = evaluate(samples, predictions, config.DB_DIR, progress=True)
        report = {"meta": make_meta(data_path, out, config.DB_DIR, config.DEFAULT_TIMEOUT_S), **report}
        s = report["summary"]
        json_path, md_path = write_report(
            report, samples, predictions, config.RESULTS_DIR,
            report_name(alias, generator.name),
        )
        print(f"VA {s['VA']:.2%}  EX {s['EX']:.2%}")
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
