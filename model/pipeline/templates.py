"""提示词模板：prompts/*.md 的加载、占位符校验与填充。

模板即纯文本，占位符写成 {question} 这样的小写标识符；每个模板允许哪些
占位符登记在 PLACEHOLDERS（prompts/README.md 有同一份人话版）。
只替换登记过的占位符，模板里出现的其他花括号（JSON 示例等）原样保留；
写错占位符名会在加载时报错并列出该模板可用的名字，而不是运行到一半才炸。
"""

from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"

# 模板名 -> 允许出现的占位符集合（模板名即 prompts/<名>.md）
PLACEHOLDERS: dict[str, set[str]] = {
    "planner.system": set(),
    "planner.user": {"schema", "question"},
    "sqlgen.system": set(),
    "sqlgen.user": {"schema", "question", "plan"},
    "dslgen.system": set(),
    "dslgen.user": {"schema", "question", "plan"},
    "dslgen.repair": {"issues"},
}

# 只把 {小写标识符} 当占位符候选，其余花括号不归模板管
_TOKEN = re.compile(r"\{([a-z_]+)\}")


def render_text(text: str, values: dict[str, str]) -> str:
    """把 text 里的已知占位符换成 values 的值；出现未知占位符立即报错。"""
    unknown = {m for m in _TOKEN.findall(text) if m not in values}
    if unknown:
        raise ValueError(
            f"模板里有未知占位符 {sorted(unknown)}，可用的是 {sorted(values)}"
        )
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def load_template(name: str) -> str:
    if name not in PLACEHOLDERS:
        raise KeyError(f"未登记的模板 {name}，已有：{sorted(PLACEHOLDERS)}")
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    """加载模板并填充。传入的键必须与 PLACEHOLDERS[name] 完全一致。"""
    expected = PLACEHOLDERS[name] if name in PLACEHOLDERS else None
    if expected is not None and set(values) != expected:
        raise ValueError(
            f"模板 {name} 需要占位符 {sorted(expected)}，传入的是 {sorted(values)}"
        )
    return render_text(load_template(name), values)
