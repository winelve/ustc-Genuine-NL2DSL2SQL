"""DSL 声明层：模型输出的 {sql, declarations} 结构与四组纯规则校验。

半程 IR（设计见 docs/design/2026-07-22-M2-dslsql.md）：SQL 仍由模型直出，
声明表逼它把关键决定摊在桌面上；本模块只做机器校验，零 LLM 调用。
所有校验产出 issue 字符串列表（空 = 通过），文字直接作为修复反馈发回模型，
所以报错内容写给模型看：说清哪里不一致、期望是什么。
"""

from __future__ import annotations

import difflib
import json
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

import sqlglot
from pydantic import BaseModel, BeforeValidator, Field, ValidationError, field_validator, model_validator
from sqlglot import exp


# ---------------------------------------------------------------- 声明表结构

# 槽位不适用时模型自然写 null（displaced=false 就没有 reference 可填）。
# 这与"没填"同义，收下即可——否则整轮回复作废，白烧一次调用去纠正 null vs ""，
# 那一轮还不产生任何声明、不做任何语义校验（实测曾吃掉 en_dev 37% 的题的第一轮）。
BlankableText = Annotated[str, BeforeValidator(lambda v: "" if v is None else v)]
BlankableDict = Annotated[dict[str, str], BeforeValidator(lambda v: {} if v is None else v)]


class TimeContext(BaseModel):
    """必填：问题问的是"现在"还是别的时间点——模型不许沉默跳过这个判断。"""

    displaced: bool
    reference: BlankableText = ""


class OutputDecl(BaseModel):
    name: str
    source: Literal["column", "derived"]
    column: BlankableText = ""                  # source=column 时必填
    expr: BlankableText = ""                    # source=derived 时必填
    anchors: BlankableDict = Field(default_factory=dict)   # 列 -> 存量值的参照系

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


class Declarations(BaseModel):
    time_context: TimeContext
    outputs: list[OutputDecl] = Field(min_length=1)
    assumptions: list[Assumption] = Field(default_factory=list)


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


# ---------------------------------------------------------------- C1 完整性

def _c1_alignment(decl: Declarations, tree: exp.Expression) -> list[str]:
    """SQL 输出列与声明表 outputs 一一对应，且 column/derived 名实相符。"""
    selects = getattr(tree, "selects", None) or []
    if not selects:
        return []                    # 非 SELECT 顶层（罕见），C1 不裁决
    if any(_is_star(s) for s in selects):
        return ["SQL 用了 SELECT *，无法逐列声明——请把输出列逐一写出再逐列声明"]
    issues = []
    if len(selects) != len(decl.outputs):
        return [f"SQL 有 {len(selects)} 个输出列，声明表 outputs 有 "
                f"{len(decl.outputs)} 条——必须一一对应（按顺序）"]
    for sel, output in zip(selects, decl.outputs):
        bare = isinstance(sel.unalias(), exp.Column)
        if output.source == "column" and not bare:
            issues.append(f"输出列 {output.name!r} 声明为 column（原样取列），"
                          "但 SQL 中是计算表达式——请改声明为 derived 并给出 expr")
        if output.source == "derived" and bare:
            issues.append(f"输出列 {output.name!r} 声明为 derived（计算得出），"
                          "但 SQL 中是裸列——要么 SQL 里真的做计算，要么改声明为 column")
    return issues


# ---------------------------------------------------------------- C2 一致性

def _c2_consistency(decl: Declarations, tree: exp.Expression) -> list[str]:
    """说到必须做到：时间位移要有算式，反事实假设要改数据。"""
    issues = []
    if decl.time_context.displaced and not any(
            o.source == "derived" for o in decl.outputs):
        issues.append(
            "time_context.displaced=true（问题涉及非当前时间点），但没有任何输出列是 "
            "derived——若需要换算请给出表达式；若确认不需要，把 displaced 改为 false")
    literals = {str(l.this) for l in tree.find_all(exp.Literal)}
    for a in decl.assumptions:
        target_column = a.target.split(".")[-1].lower()
        if a.value not in literals:
            issues.append(
                f"假设 {a.target} = {a.value!r} 的假设值没有出现在 SQL 里——"
                "反事实假设必须参与计算（修改数据），不能被忽略")
        for col, lit in _eq_column_literal_pairs(tree):
            if col.name.lower() == target_column and str(lit.this) == a.value:
                issues.append(
                    f"假设 {a.target} = {a.value!r} 疑似被写成了过滤条件"
                    f"（{col.name} = {a.value}）——假设是修改数据，"
                    "不是筛选恰好满足假设的行")
    return issues


# ---------------------------------------------------------------- C3 接地

def _c3_grounding(decl: Declarations, tree: exp.Expression,
                  schema_info: SchemaInfo, db_path: Path) -> list[str]:
    """声明引用的表/列必须真实存在；等值比较的字面值给近邻提示。"""
    issues: list[str] = []
    all_columns = {c for cols in schema_info.values() for c in cols}

    def check_column(ref: str, owner: str) -> None:
        table, _, column = ref.rpartition(".")
        if table:
            if table.lower() not in schema_info:
                issues.append(f"{owner} 引用的表 {table!r} 不在 schema 里")
            elif column.lower() not in schema_info[table.lower()]:
                issues.append(f"{owner} 引用的列 {ref!r} 不在 schema 里")
        elif column.lower() not in all_columns:
            issues.append(f"{owner} 引用的列 {column!r} 不在 schema 的任何表里")

    for output in decl.outputs:
        if output.source == "column":
            check_column(output.column, f"输出列 {output.name!r}")
        else:
            columns = _expr_columns(output.expr)
            if columns is None:
                issues.append(f"输出列 {output.name!r} 的 expr 无法按 SQLite 表达式"
                              f"解析: {output.expr!r}")
                continue
            for c in sorted(columns - all_columns):
                issues.append(f"输出列 {output.name!r} 的 expr 引用的列 {c!r} "
                              "不在 schema 的任何表里")
    for a in decl.assumptions:
        check_column(a.target, f"假设 target {a.target!r}")
    issues += _c3_literal_neighbors(tree, schema_info, db_path)
    return issues


def _c3_literal_neighbors(tree: exp.Expression, schema_info: SchemaInfo,
                          db_path: Path, cap: int = 2000) -> list[str]:
    """列 = '字面值' 里的值若不在该列值域且存在近邻，提示改用库内真实值。

    只在列名能唯一定位到一张表时才查（不猜表）；找不到近邻不打扰——
    空结果可能正是题意。这是建议级检查，宁缺毋滥。

    "值是否存在"用带条件的查询精确判定，cap 只截断喂给 difflib 的候选池：
    值域大到万级的列（如 soccer_1.Player.player_name）若拿截断后的池子判存在性，
    排在 cap 之后的真实值会被误判成打错，白白逼模型改掉正确的 SQL。
    """
    pairs = [(col, lit) for col, lit in _eq_column_literal_pairs(tree)
             if lit.is_string]
    if not pairs:
        return []
    issues = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for col, lit in pairs:
            literal = str(lit.this)
            tables = [t for t, cols in schema_info.items()
                      if col.name.lower() in cols]
            if len(tables) != 1:
                continue
            if conn.execute(
                f'SELECT 1 FROM "{tables[0]}" WHERE "{col.name}" = ? LIMIT 1',
                (literal,),
            ).fetchone():
                continue
            rows = conn.execute(
                f'SELECT DISTINCT "{col.name}" FROM "{tables[0]}" LIMIT {cap}'
            ).fetchall()
            values = {str(r[0]) for r in rows if r[0] is not None}
            close = difflib.get_close_matches(literal, values, n=3, cutoff=0.6)
            if close:
                issues.append(
                    f"字面值 {literal!r} 不在列 {tables[0]}.{col.name} 的取值里，"
                    f"库内近似值有 {close}——请核对是否应使用库内真实值")
    finally:
        conn.close()
    return issues


# ---------------------------------------------------------------- C4 锚完整

def _c4_anchors(decl: Declarations) -> list[str]:
    """时间位移时，派生表达式用到的每个列都要声明存量值参照系（M3 注入口）。"""
    if not decl.time_context.displaced:
        return []
    issues = []
    for output in decl.outputs:
        if output.source != "derived":
            continue
        columns = _expr_columns(output.expr) or set()
        anchors = {k.split(".")[-1].lower() for k in output.anchors}
        missing = sorted(columns - anchors)
        if missing:
            issues.append(
                f"输出列 {output.name!r} 的 expr 用到列 {missing}，但 anchors 没有"
                "声明它们的参照系——每个列存的是哪个时间点/口径的值？")
    return issues


# ---------------------------------------------------------------- 总入口

def validate(out: DslOutput, schema_info: SchemaInfo, db_path: Path) -> list[str]:
    """四组检查汇总；返回 issue 列表（空 = 通过），文字直接作修复反馈。"""
    try:
        tree = sqlglot.parse_one(out.sql, dialect="sqlite")
    except Exception as e:
        return [f"SQL 无法按 SQLite 语法解析: {e}"]
    decl = out.declarations
    return (_c1_alignment(decl, tree) + _c2_consistency(decl, tree)
            + _c3_grounding(decl, tree, schema_info, db_path)
            + _c4_anchors(decl))
