"""预览 plansql 实际发给两个 LLM 的完整消息（不打 API，改完提示词先看再跑）。

    python -m model.pipeline --data en_dev --preview 0
"""

from __future__ import annotations

import argparse

import config
from archer_eval.data import load_dataset, resolve_dataset
from archer_eval.evaluate import find_db_file
from model.pipeline.conventions import conventions_block
from model.pipeline.dsl import render_profile, render_profile_block
from model.pipeline.profile import build_profile
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
    db_path = find_db_file(config.DB_DIR, sample.db_id)
    schema = schema_with_rows(db_path)
    # 库画像会注入 planner 与 dslgen；预览一律带上，改完规则先看再跑
    items = build_profile(db_path)
    profile = render_profile(items)

    # sqlgen 只有 plansql（无 DSL）用；dslsql 走 dslgen——预览分段标明归属，
    # 免得把 SQL 直出提示词误读成当前 DSL 管线的一部分
    sections = [
        ("planner system", load_template("planner.system")),
        ("planner user [带库画像]",
         render("planner.user", schema=schema, question=sample.question,
                profile=render_profile_block(items))),
        ("sqlgen system [仅 plansql]", load_template("sqlgen.system")),
        ("sqlgen user [仅 plansql]",
         render("sqlgen.user", schema=schema, question=sample.question,
                plan="<planner 的输出会填在这里>")),
        ("dslgen system [dslsql]", load_template("dslgen.system")),
        ("dslgen system 附录 [约定 prose 臂]",
         render("dslgen.conventions", conventions=conventions_block())),
        ("dslgen user [dslsql]",
         render("dslgen.user", schema=schema, question=sample.question,
                plan="<planner 的输出会填在这里>", profile=profile)),
    ]
    for title, text in sections:
        print(f"{'=' * 28} {title} {'=' * 28}")
        print(text.rstrip() + "\n")


if __name__ == "__main__":
    main()
