"""CT-3 prompt 预览/导出脚本（实现在 model/prompts.py）。

Usage:
    python scripts/build_prompts.py --data en_dev --index 0          # 打印一条 prompt
    python scripts/build_prompts.py --data en_dev --out prompts.json # 导出全部 prompt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archer_eval import config
from archer_eval.data import load_dataset
from archer_eval.evaluate import find_db_file
from model.prompts import build_ct3_prompt


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CT-3 prompts for an Archer dataset")
    parser.add_argument("--data", required=True,
                        help=f"one of {', '.join(config.DATASETS)} or a JSON file path")
    parser.add_argument("--index", type=int, help="print the prompt of one sample and exit")
    parser.add_argument("--out", help="write all prompts to this JSON file (array of strings)")
    parser.add_argument("--with-knowledge", action="store_true",
                        help="prepend commonsense_knowledge to the question (analysis only)")
    parser.add_argument("--cot", action="store_true", help="append the chain-of-thought line")
    args = parser.parse_args()

    samples = load_dataset(config.resolve_dataset(args.data))

    if args.index is not None:
        s = samples[args.index]
        print(build_ct3_prompt(s, find_db_file(config.DB_DIR, s.db_id),
                               args.with_knowledge, args.cot))
        return

    if not args.out:
        parser.error("provide --index N to preview or --out FILE to dump all prompts")

    prompts = [
        build_ct3_prompt(s, find_db_file(config.DB_DIR, s.db_id), args.with_knowledge, args.cot)
        for s in samples
    ]
    Path(args.out).write_text(json.dumps(prompts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(prompts)} prompts written to {args.out}")


if __name__ == "__main__":
    main()
