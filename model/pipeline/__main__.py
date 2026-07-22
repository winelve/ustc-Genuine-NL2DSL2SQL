"""预览 plansql 实际发给两个 LLM 的完整消息（不打 API，改完提示词先看再跑）。

    python -m model.pipeline --data en_dev --preview 0
"""

from __future__ import annotations

import argparse

import config
from archer_eval.data import load_dataset, resolve_dataset
from archer_eval.evaluate import find_db_file
from model.pipeline.templates import load_template, render
from model.prompts import schema_with_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="model.pipeline", description="Preview the exact planner/sqlgen messages"
    )
    parser.add_argument("--data", required=True,
                        help=f"one of {', '.join(config.DATASETS)} or a JSON file path")
    parser.add_argument("--preview", type=int, required=True, metavar="N",
                        help="dataset index of the sample to preview")
    args = parser.parse_args()

    sample = load_dataset(resolve_dataset(args.data))[args.preview]
    schema = schema_with_rows(find_db_file(config.DB_DIR, sample.db_id))

    sections = [
        ("planner system", load_template("planner.system")),
        ("planner user", render("planner.user", schema=schema, question=sample.question)),
        ("sqlgen system", load_template("sqlgen.system")),
        ("sqlgen user", render("sqlgen.user", schema=schema, question=sample.question,
                               plan="<planner 的输出会填在这里>")),
    ]
    for title, text in sections:
        print(f"{'=' * 28} {title} {'=' * 28}")
        print(text.rstrip() + "\n")


if __name__ == "__main__":
    main()
