"""CT-3 prompt construction (paper Appendix A).

Each table: CREATE TABLE statement + a /* 3 example rows */ block;
the question is appended as SQL comments, ending with "SELECT".

Preview / export:
    python -m model.prompts --data en_dev --index 0
    python -m model.prompts --data en_dev --out prompts.json
"""

from __future__ import annotations

from pathlib import Path

from archer_eval.data import Sample
from archer_eval.execution import connect_ro


def schema_with_rows(db_path: str | Path, n_rows: int = 3) -> str:
    conn = connect_ro(db_path)
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


def _main() -> None:
    import argparse
    import json

    import config
    from archer_eval.data import load_dataset
    from archer_eval.evaluate import find_db_file

    parser = argparse.ArgumentParser(description="Preview or export CT-3 prompts")
    parser.add_argument("--data", required=True,
                        help=f"one of {', '.join(config.DATASETS)} or a JSON file path")
    parser.add_argument("--index", type=int, help="print one prompt and exit")
    parser.add_argument("--out", help="write all prompts to this JSON file")
    parser.add_argument("--with-knowledge", action="store_true")
    parser.add_argument("--cot", action="store_true")
    args = parser.parse_args()

    samples = load_dataset(config.resolve_dataset(args.data))

    if args.index is not None:
        s = samples[args.index]
        print(build_ct3_prompt(s, find_db_file(config.DB_DIR, s.db_id),
                               args.with_knowledge, args.cot))
        return

    if not args.out:
        parser.error("provide --index N or --out FILE")

    prompts = [
        build_ct3_prompt(s, find_db_file(config.DB_DIR, s.db_id), args.with_knowledge, args.cot)
        for s in samples
    ]
    Path(args.out).write_text(json.dumps(prompts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out} ({len(prompts)} prompts)")


if __name__ == "__main__":
    _main()
