"""阶段一的统一入口（runner）：跑一个模型，产出标准格式的预测文件。

    python -m model --model first_table --data en_dev          # 只生成
    python -m model --model first_table --data en_dev --eval   # 生成后立刻评测

runner 负责所有"体力活"：加载数据集、找数据库、逐条调模型、
保证输出与数据集同序同长、落盘到 predictions/<model>_<data>.json。
模型实现者只需要关心 predict() 里的一条进一条出。
"""

from __future__ import annotations

import argparse
import json

from archer_eval import config
from archer_eval.data import load_dataset
from archer_eval.evaluate import evaluate, find_db_file
from archer_eval.report import make_meta, write_report
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
    print(f"Generating with '{generator.name}' on {data_path} ({len(samples)} samples)...")
    predictions = generator.predict_all(samples, db_paths)

    alias = args.data if args.data in config.DATASETS else data_path.stem
    out = config.PREDICTIONS_DIR / f"{generator.name}_{alias}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(predictions, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"预测已写入 {out}")

    if args.eval:
        report = evaluate(samples, predictions, config.DB_DIR, progress=True)
        s = report["summary"]
        report = {"meta": make_meta(data_path, out, config.DB_DIR, config.DEFAULT_TIMEOUT_S), **report}
        json_path, md_path = write_report(
            report, samples, predictions, config.RESULTS_DIR, f"{alias}_{generator.name}"
        )
        print(f"VA = {s['VA']:.2%}   EX = {s['EX']:.2%}")
        print(f"报告已写入 {md_path}")


if __name__ == "__main__":
    main()
