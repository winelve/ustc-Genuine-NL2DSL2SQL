"""DSL 声明层：模型输出的 {sql, declarations} 结构与四组纯规则校验。

半程 IR（设计见 docs/design/2026-07-22-M2-dslsql.md）：SQL 仍由模型直出，
声明表逼它把关键决定摊在桌面上；本模块只做机器校验，零 LLM 调用。
所有校验产出 issue 字符串列表（空 = 通过），文字直接作为修复反馈发回模型，
所以报错内容写给模型看：说清哪里不一致、期望是什么。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

import sqlglot
from pydantic import BaseModel, BeforeValidator, Field, ValidationError, field_validator, model_validator
from sqlglot import exp


# ---------------------------------------------------------------- 声明表结构

# 槽位不适用时模型自然写 null（displaced=false 就没有 reference 可填），
# 与"没填"同义，直接收下即可——否则整轮回复作废，还得白烧一次调用去纠正 null vs ""。
BlankableText = Annotated[str, BeforeValidator(lambda v: "" if v is None else v)]
BlankableDict = Annotated[dict[str, str], BeforeValidator(lambda v: {} if v is None else v)]


class TimeContext(BaseModel):
    """必填：问题问的是"现在"还是别的时间点——模型不许沉默跳过这个判断。"""

    displaced: bool
    reference: BlankableText = ""


class Anchor(BaseModel):
    """存量列的参照系。枚举化的意义是**可证伪**——自由文本写什么都合法。

    只枚举程序能验的三种。单位锚（"weight 存的是磅"）刻意不进 kind：
    SQL 里没有任何东西能证伪它，声明了也只是换个地方写自由文本。
    """

    kind: Literal["now", "column", "literal"]
    ref: BlankableText = ""


def _coerce_anchor(v):
    """裸字符串按 literal 收下：宁可降级也不整轮作废（同 BlankableText 的理由）。"""
    return {"kind": "literal", "ref": v} if isinstance(v, str) else v


AnchorMap = Annotated[
    dict[str, Anchor],
    BeforeValidator(lambda v: {} if v is None
                    else {k: _coerce_anchor(x) for k, x in v.items()}),
]


class OutputDecl(BaseModel):
    name: str
    source: Literal["column", "derived"]
    column: BlankableText = ""                  # source=column 时必填
    expr: BlankableText = ""                    # source=derived 时必填
    anchors: AnchorMap = Field(default_factory=dict)       # 列 -> 存量值的参照系

    @model_validator(mode="after")
    def _source_fields(self) -> "OutputDecl":
        if self.source == "column" and not self.column:
            raise ValueError(f"输出列 {self.name!r} 声明为 column 但缺 column 字段")
        if self.source == "derived" and not self.expr:
            raise ValueError(f"输出列 {self.name!r} 声明为 derived 但缺 expr 字段")
        return self


class Assumption(BaseModel):
    """反事实假设 = 数据补丁（改数据），永远不是过滤条件。"""

    target: str                                 # table.column
    where: BlankableText = ""
    value: str

    @field_validator("value", mode="before")
    @classmethod
    def _stringify(cls, v) -> str:              # JSON 里写数字也接受
        # value=null 不是"不适用"而是没给出假设值：宁可打回，也不能悄悄变成 "None"
        # 再去和 SQL 字面值比对（那会伪造出一条"假设被忽略"的 C2 报错）
        if v is None:
            raise ValueError("假设缺少 value——请写出假设把该列改成什么值")
        return str(v)


class Considered(BaseModel):
    """对库画像每一条事实的表态：用了没用；没用必须给理由。

    强制表态把"没想到"变成"想过并否决了"——后者才可校验、可统计。
    """

    item: str                                   # 画像条目编号，如 "P1"
    used: bool
    note: BlankableText = ""                    # used=false 时必填理由


class Declarations(BaseModel):
    time_context: TimeContext
    outputs: list[OutputDecl] = Field(min_length=1)
    assumptions: list[Assumption] = Field(default_factory=list)
    considered: list[Considered] = Field(default_factory=list)


class DslOutput(BaseModel):
    sql: str = Field(min_length=1)
    declarations: Declarations


def parse_output(text: str) -> tuple[DslOutput | None, str]:
    """从模型回复里抽出 JSON 并结构化；失败返回 (None, 给模型看的错误说明)。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None, "回复中找不到 JSON 对象——请只输出一个符合格式的 JSON 对象"
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败（{e}）——请输出合法 JSON，不要附加解释文字"
    try:
        return DslOutput.model_validate(data), ""
    except ValidationError as e:
        heads = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in e.errors()[:3]
        )
        return None, f"声明表结构不合法: {heads}"


# ---------------------------------------------------------------- schema 信息

SchemaInfo = dict[str, set[str]]     # 小写表名 -> 小写列名集合


def load_schema_info(db_path: Path) -> SchemaInfo:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        return {
            t.lower(): {r[1].lower() for r in conn.execute(f'PRAGMA table_info("{t}")')}
            for t in tables
        }
    finally:
        conn.close()


# ---------------------------------------------------------------- 校验助手

def _expr_columns(expr_sql: str) -> set[str] | None:
    """一段表达式引用的列名（小写、去表前缀）；解析失败返回 None。"""
    try:
        tree = sqlglot.parse_one(f"SELECT {expr_sql}", dialect="sqlite")
    except Exception:
        return None
    return {c.name.lower() for c in tree.find_all(exp.Column)}


def _is_star(sel: exp.Expression) -> bool:
    """SELECT * / t.* 才算；count(*) 里的 * 不算。"""
    inner = sel.unalias()
    return isinstance(inner, exp.Star) or (
        isinstance(inner, exp.Column) and isinstance(inner.this, exp.Star)
    )


def _eq_column_literal_pairs(tree: exp.Expression) -> list[tuple[exp.Column, exp.Literal]]:
    """SQL 里所有 列 = 字面值 的等值比较（两个方向都认）。"""
    pairs = []
    for eq in tree.find_all(exp.EQ):
        left, right = eq.this, eq.expression
        col, lit = (left, right) if isinstance(left, exp.Column) else (right, left)
        if isinstance(col, exp.Column) and isinstance(lit, exp.Literal):
            pairs.append((col, lit))
    return pairs
