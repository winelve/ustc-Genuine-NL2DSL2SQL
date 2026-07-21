"""CT-3 prompt construction (paper Appendix A) — generation-side utility.

The evaluation package does not depend on this. Use it when running an LLM
baseline: build one prompt per sample, send to the model, collect the SQL
answers into predictions/<name>.json, then evaluate with `python -m archer_eval`.

Usage:
    python scripts/build_prompts.py --data en_dev --index 0          # print one prompt
    python scripts/build_prompts.py --data en_dev --out prompts.json # dump all prompts
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archer_eval import config
from archer_eval.data import Sample, load_dataset
from archer_eval.evaluate import find_db_file


def schema_with_rows(db_path: str | Path, n_rows: int = 3) -> str:
    """CREATE TABLE statements, each followed by a /* 3 example rows */ block."""
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    parts = []
    try:
        tables = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        ).fetchall()
        for name, create_sql in tables:
            cur = conn.execute(f'SELECT * FROM "{name}" LIMIT {n_rows}')
            col_names = [d[0] for d in cur.description]
            rows = cur.fetchall()
            lines = [
                f"/* {n_rows} example rows:",
                f"SELECT * FROM {name} LIMIT {n_rows};",
                "\t".join(col_names),
            ]
            lines += ["\t".join("" if v is None else str(v) for v in row) for row in rows]
            lines.append("*/")
            parts.append(f"{create_sql.strip()}\n" + "\n".join(lines))
    finally:
        conn.close()
    return "\n\n".join(parts)


def build_ct3_prompt(
    sample: Sample,
    db_path: str | Path,
    with_knowledge: bool = False,
    cot: bool = False,
) -> str:
    question = sample.question
    if with_knowledge and sample.commonsense_knowledge:
        question = f"{sample.commonsense_knowledge} {question}"

    prompt = (
        f"{schema_with_rows(db_path)}\n\n"
        "-- Using valid SQLite, answer the following questions for the tables provided above.\n"
        f"-- {question}\n"
    )
    if cot:
        prompt += "-- Let's think step by step.\n"
    return prompt + "SELECT"


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
