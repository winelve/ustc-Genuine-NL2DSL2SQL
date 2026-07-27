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


# reasoning_type 的标注是封闭的 6 个 token，翻成人话当提示词。
_REASONING_TOKENS = {
    "-": "subtraction", "+": "addition", "*": "multiplication",
    "/": "division", "C": "commonsense", "H": "hypothetical",
}


def describe_reasoning_type(reasoning_type: str) -> str:
    """把 '- + C H' 翻成一句自然语言提示；空标签或全未知 token 返回空串。"""
    words = [_REASONING_TOKENS[t] for t in reasoning_type.split() if t in _REASONING_TOKENS]
    if not words:
        return ""
    listed = words[0] if len(words) == 1 else ", ".join(words[:-1]) + ", and " + words[-1]
    return f"this question involves {listed} reasoning."


def build_ct3_prompt(
    sample: Sample,
    db_path: str | Path,
    with_knowledge: bool = False,
    cot: bool = False,
    with_reasoning_type: bool = False,
    examples: str = "",
) -> str:
    question = sample.question
    if with_knowledge and sample.commonsense_knowledge:
        question = f"{sample.commonsense_knowledge} {question}"

    prompt = (
        f"{schema_with_rows(db_path)}\n\n"
        "-- Using valid SQLite, answer the following questions for the tables provided above.\n"
        f"-- {question}\n"
    )
    if with_reasoning_type:
        hint = describe_reasoning_type(sample.reasoning_type)
        if hint:
            prompt += f"-- Hint: {hint}\n"
    if cot:
        prompt += "-- Let's think step by step.\n"
    prompt += "SELECT"
    return f"{examples}\n\n{prompt}" if examples else prompt


def _main() -> None:
    import argparse
    import json

    import config
    from archer_eval.data import load_dataset, resolve_dataset
    from archer_eval.evaluate import find_db_file

    parser = argparse.ArgumentParser(description="Preview or export CT-3 prompts")
    parser.add_argument("--data", required=True,
                        help=f"one of {', '.join(config.DATASETS)} or a JSON file path")
    parser.add_argument("--index", type=int, help="print one prompt and exit")
    parser.add_argument("--out", help="write all prompts to this JSON file")
    parser.add_argument("--with-knowledge", action="store_true")
    parser.add_argument("--cot", action="store_true")
    parser.add_argument("--with-reasoning-type", action="store_true")
    args = parser.parse_args()

    samples = load_dataset(resolve_dataset(args.data))
    db_dir = config.db_dir_for(args.data)

    if args.index is not None:
        s = samples[args.index]
        print(build_ct3_prompt(s, find_db_file(db_dir, s.db_id),
                               args.with_knowledge, args.cot, args.with_reasoning_type))
        return

    if not args.out:
        parser.error("provide --index N or --out FILE")

    prompts = [
        build_ct3_prompt(s, find_db_file(db_dir, s.db_id),
                         args.with_knowledge, args.cot, args.with_reasoning_type)
        for s in samples
    ]
    Path(args.out).write_text(json.dumps(prompts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out} ({len(prompts)} prompts)")


if __name__ == "__main__":
    _main()
