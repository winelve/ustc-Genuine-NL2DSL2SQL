"""CLI entry point.

Evaluate predictions (dataset can be a shorthand or a path):
    python -m archer_eval --data en_dev --pred predictions/first_table_en_dev.json

Sanity check (gold as prediction; expects VA=1.0, EX=1.0):
    python -m archer_eval --data en_dev --gold-as-pred
"""

from __future__ import annotations

import argparse
from pathlib import Path

import config
from archer_eval.data import load_dataset, load_predictions, resolve_dataset
from archer_eval.evaluate import evaluate
from archer_eval.report import make_meta, report_name, write_report


def main() -> None:
    parser = argparse.ArgumentParser(prog="archer_eval", description="Archer VA/EX evaluation")
    parser.add_argument(
        "--data", required=True,
        help=f"dataset: one of {', '.join(config.DATASETS)} or a JSON file path",
    )
    parser.add_argument("--pred", help="prediction JSON aligned with the dataset")
    parser.add_argument("--gold-as-pred", action="store_true", help="evaluate gold SQL against itself")
    parser.add_argument("--db-dir", default=config.DB_DIR, help="root directory of SQLite databases")
    parser.add_argument("--out-dir", default=config.RESULTS_DIR, help="directory for reports")
    parser.add_argument("--timeout", type=float, default=config.DEFAULT_TIMEOUT_S,
                        help="per-query timeout in seconds")
    args = parser.parse_args()

    if bool(args.pred) == args.gold_as_pred:
        parser.error("provide exactly one of --pred or --gold-as-pred")

    data_path = resolve_dataset(args.data)
    samples = load_dataset(data_path)
    if args.gold_as_pred:
        predictions = [s.query for s in samples]
        pred_name = "gold"
    else:
        predictions = load_predictions(args.pred, expected_len=len(samples))
        pred_name = Path(args.pred).stem

    report = evaluate(samples, predictions, args.db_dir, timeout_s=args.timeout, progress=True)
    report = {
        "meta": make_meta(data_path, args.pred or "gold-as-pred", args.db_dir, args.timeout),
        **report,
    }

    alias = args.data if args.data in config.DATASETS else data_path.stem
    name = report_name(alias, pred_name)
    json_path = write_report(report, args.out_dir, name)

    s = report["summary"]
    print(f"\n{alias}: {s['n']} samples  VA {s['VA']:.2%}  EX {s['EX']:.2%}  SIM {s['SIM']:.2%}")
    for db, m in report["by_db"].items():
        print(f"  {db:<35} n={m['n']:<4} VA {m['VA']:.2%}  EX {m['EX']:.2%}  SIM {m['SIM']:.2%}")
    print(f"wrote {json_path}")


if __name__ == "__main__":
    main()
