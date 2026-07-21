"""CT-3 prompt 构造（论文附录 A，零样本 LLM 最优设定）。

每张表输出 CREATE TABLE 语句 + /* 3 example rows */ 注释块，
末尾以 SQL 注释形式附上问题，并以 "SELECT" 结尾引导模型续写。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from archer_eval.data import Sample


def schema_with_rows(db_path: str | Path, n_rows: int = 3) -> str:
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
