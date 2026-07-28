"""BIRD 官方 baseline 的提示词——全项目只有这一个文件知道它长什么样。

逐字复刻 `bird-bench/mini_dev` 的 `llm/src/{table_schema,prompt}.py`（SQLite 方言）：

    schema_ddl_block   ← generate_schema_prompt_sqlite(db_path, num_rows=None)
    comment_block      ← generate_comment_prompt(question, "SQLite", knowledge)
    COT_BLOCK          ← generate_cot_prompt("SQLite")
    INSTRUCTION_BLOCK  ← generate_instruction_prompt("SQLite")
    official_prompt    ← generate_combined_prompts_one(...)   （"\\n\\n" 连接四块）

**官方 baseline 不给的东西，这里一样不给**（跑分要跟榜单可比，多给就不是同一个设定）：

- 每表样本行 —— 官方 `num_rows` 不传，走不进那个分支；
- `database_description/*.csv` 的列描述 —— 官方只读 `sqlite_master`；
- 外键 / `dev_tables.json` —— 同上；
- few-shot 例子 —— 官方源码里 `few_shot()` 是注释掉的；
- system message —— 官方 `messages=[{"role": "user", ...}]` 只有一条。

这几样在 `bird/extras.py` 里有现成函数，但**不属于官方口径**，接进来分数就不可并排。
"""

from __future__ import annotations

from pathlib import Path

from archer_eval.data import Sample
from archer_eval.execution import connect_ro

SQL_DIALECT = "SQLite"

COT_BLOCK = f"\nGenerate the {SQL_DIALECT} for the above question after thinking step by step: "

INSTRUCTION_BLOCK = f"""
        \nIn your response, you do not need to mention your intermediate steps.
        Do not include any comments in your response.
        Do not need to start with the symbol ```
        You only need to return the result {SQL_DIALECT} SQL code
        start from SELECT
        """


def schema_ddl_block(db_path: str | Path) -> str:
    """全库 CREATE TABLE 语句，`\\n\\n` 连接。**不含样本行**。

    官方用可写 `sqlite3.connect`，这里用项目的只读连接——纯读取，结果一致
    （偏离清单见 docs/BIRD.md）。
    """
    conn = connect_ro(db_path)
    try:
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return "\n\n".join(sql for name, sql in rows if name != "sqlite_sequence" and sql)


def comment_block(question: str, evidence: str | None = None) -> str:
    """题面块。有 evidence 走官方的 "understanding External Knowledge" 分支。"""
    knowledge = (evidence or "").strip()
    knowledge_text = " and understanding External Knowledge" if knowledge else ""
    knowledge_prompt = f"-- External Knowledge: {knowledge}" if knowledge else ""
    return (
        f"-- Using valid {SQL_DIALECT}{knowledge_text}, "
        "answer the following questions for the tables provided above.\n"
        f"-- {question}\n"
        f"{knowledge_prompt}"
    )


def official_prompt(
    sample: Sample,
    db_path: str | Path,
    *,
    evidence: bool = True,
    schema: str | None = None,
) -> str:
    """官方 baseline 的完整 user 消息。

    `evidence=False` 走官方的无知识分支（`--use_knowledge False`），供将来做
    "屏蔽外部知识"的消融——官方 dev 榜的数一律是 **evidence=True**。
    """
    knowledge = sample.commonsense_knowledge if evidence else None
    return "\n\n".join([
        schema if schema is not None else schema_ddl_block(db_path),
        comment_block(sample.question, knowledge),
        COT_BLOCK,
        INSTRUCTION_BLOCK,
    ])
