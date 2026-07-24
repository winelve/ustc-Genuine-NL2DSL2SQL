"""DSL 声明层：模型输出的 {sql, declarations} 结构与四组纯规则校验。

半程 IR（设计见 docs/design/2026-07-22-M2-dslsql.md）：SQL 仍由模型直出，
声明表逼它把关键决定摊在桌面上；本模块只做机器校验，零 LLM 调用。
所有校验产出 issue 字符串列表（空 = 通过），文字直接作为修复反馈发回模型，
所以报错内容写给模型看：说清哪里不一致、期望是什么。
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

import sqlglot
from pydantic import BaseModel, BeforeValidator, Field, ValidationError, field_validator, model_validator
from sqlglot import exp

from model.pipeline.profile import numeric_columns


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
    """时间位移时，派生表达式用到的每个列都要声明存量值参照系。"""
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


# ---------------------------------------------------------------- 画像渲染

def render_profile(items: list[str]) -> str:
    """把画像条目编号成 prompt 文本块；编号是 considered 的引用键。"""
    if not items:
        return "(none for this database)"
    return "\n".join(f"P{i}. {x}" for i, x in enumerate(items, 1))


def profile_ids_for(items: list[str]) -> set[str]:
    """与 render_profile 同源的编号集合，避免两处各编一套。"""
    return {f"P{i}" for i in range(1, len(items) + 1)}


def render_profile_block(items: list[str]) -> str:
    """planner 用的画像块：**没有画像时返回空串**。

    知识要在 planner 犯错之前送到，但 planner 提示词与不带画像的对照组共用——
    返回空串是为了让 use_profile=False 时渲染出的消息与对照组**逐字节相同**
    （tests/test_pipeline.py 有断言锁死）。
    """
    if not items:
        return ""
    return ("\nFacts derived from the actual database contents:\n\n"
            + render_profile(items) + "\n")


# ---------------------------------------------------------------- C5a 表态完整

def _c5a_considered(decl: Declarations, profile_ids: set[str]) -> list[str]:
    """库画像的每一条都必须被表态；否决必须给理由。"""
    if not profile_ids:
        return []
    issues = []
    disposed = {c.item for c in decl.considered}
    for missing in sorted(profile_ids - disposed):
        issues.append(
            f"库画像条目 {missing} 没有出现在 considered 里——每一条都必须表态"
            f"（used=true 说明怎么用；used=false 在 note 里说明为什么不用）")
    for c in decl.considered:
        if c.item in profile_ids and not c.used and not c.note.strip():
            issues.append(
                f"库画像条目 {c.item} 标了 used=false 但没写理由——"
                f"在 note 里说明为什么本题不需要它")
    return issues


# ---------------------------------------------------------------- C5b 锚一致

_NOW_IN_SQL = re.compile(r"""["']now["']""", re.I)
# ref 措辞说的是"当前"、kind 却不是 now —— 枚举被绕过的典型形态
_CURRENT_WORDS = re.compile(r"current|\bnow\b|today|present", re.I)
# 题面已给出百分数字面量（"growth rate is 0.4%"）=> 比率/位移是给定输入，无需换算
_GIVEN_RATIO = re.compile(r"\d+(\.\d+)?\s*(%|percent\b)", re.I)


def _c5b_anchor_sql(decl: Declarations, tree: exp.Expression,
                    question: str) -> list[str]:
    """时间位移的题里，锚在当前的列必须真的从当前换算过去。

    事实已经在上下文里，断的往往是执行（声明写对了，SQL 忘了换算）——这一类
    纯知识注入零收益，只有一致性校验能抓。

    四个条件缺一不可：
    1. `displaced=true`——不涉及别的时点时，"存的是当前值"是无害陈述，
       没有换算可以算错。
    2. 题面没给出百分数字面量——这类题的时间位移由给定比率表达
       （`x * 1.004`），SQL 里合法地没有任何日期函数。
    3. 锚是 now-ish——kind=now，或 ref 措辞本身说的是当前（后者防止模型把
       kind 写成 literal 绕开这条检查）。
    4. SQL 里没有 'now'。
    """
    if not decl.time_context.displaced or _GIVEN_RATIO.search(question):
        return []
    now_ish = sorted({k for o in decl.outputs for k, a in o.anchors.items()
                      if a.kind == "now" or _CURRENT_WORDS.search(a.ref)})
    if not now_ish or _NOW_IN_SQL.search(tree.sql(dialect="sqlite")):
        return []
    return [f"问题涉及别的时间点，anchors 里 {now_ish} 的参照系是当前时点，"
            f"但 SQL 里没有出现 'now'——存量值锚在当前，就必须从当前换算过去"
            f"（如 strftime('%Y','now')）；若锚其实不在当前，改 kind/ref 说清楚"]


# ---------------------------------------------------------------- C6 比率线索

# 只在题面明确要"比率"时才触发。"average" 刻意不收：它常指聚合而非比率，
# 且 Archer 里恰好有名为 Average 的存量列，宽进只会把普通取值题逼成比率题。
_RATIO_WORDS = re.compile(
    r"\brates?\b|\bratios?\b|\bdensity\b|proportion|percentage|per capita|\bper\b",
    re.I)


def _c6_ratio_hint(tree: exp.Expression, question: str,
                   db_path: Path) -> list[str]:
    """题面要比率、SQL 却一个除法都没有 => 把用到的表的数值列摆出来。

    三道闸门：
    1. 题面必须有比率词（"average" 不算——库里恰好有名为 Average 的列）。
    2. 题面若已给出百分数字面量，比率是给定输入，不用算。
    3. SQL 里若已有除法，说明已经在算比率了。

    只提示不判错：分母是哪一列由模型决定，程序无从判定。精度实测见
    scripts/measure_checks.py 与 docs/ABLATION.md。
    """
    if not _RATIO_WORDS.search(question) or _GIVEN_RATIO.search(question):
        return []
    if next(tree.find_all(exp.Div), None) is not None:
        return []
    used = {c.name.lower() for c in tree.find_all(exp.Column)}
    issues = []
    for table, cols in numeric_columns(db_path).items():
        hit = [c for c in cols if c.lower() in used]
        rest = [c for c in cols if c.lower() not in used]
        if hit and rest:
            issues.append(
                f"题面问的是比率，但 SQL 里没有任何除法，只取了 {table} 的 {hit}；"
                f"同表还有数值列 {rest}——比率的分母是不是其中之一？"
                f"确认不需要归一化就在 considered 里写明理由")
    return issues


# ---------------------------------------------------------------- C7 约定检查

# Archer 规定值 vs 常见"更精确"写法。365.25 抓 julianday 年龄公式（K2）。
_OFFBRAND_CONSTANTS = {
    "0.453592": "K3", "2.20462": "K3", "25.4": "K3",
    "1.60934": "K3",   # 注意 1.609344 是对的——用精确匹配整个字面量判定
    "365.25": "K2",
}
_ARCHER_OK = {"0.45", "25", "1.609344"}

_DIFF_WORDS = re.compile(
    r"difference between|how (?:many|much) (?:more|less|older|younger|taller|"
    r"higher|longer|heavier)", re.I)

_DISPLACED_WORDS = re.compile(
    r"\bat the time of\b|\byears? (?:ago|later|earlier)\b|"
    r"\bin the year \d{4}\b", re.I)


def _c7_constants(tree: exp.Expression) -> list[str]:
    """K2/K3：出现"更精确"的换算常数/儒略年龄式 => 提示 Archer 规定值。"""
    issues = []
    for lit in tree.find_all(exp.Literal):
        token = str(lit.this)
        if token in _ARCHER_OK:
            continue
        k = _OFFBRAND_CONSTANTS.get(token)
        if k == "K3":
            issues.append(
                f"SQL 里的常数 {token} 不是本数据集的规定值（K3：0.45 / 25 / "
                f"1.609344）——请改用规定值")
        elif k == "K2":
            issues.append(
                "SQL 用了 365.25 折算年数（K2）——本数据集的整年公式是 "
                "strftime('%Y',b)-strftime('%Y',a)-(strftime('%m-%d',b)<"
                "strftime('%m-%d',a))")
    return issues


def _c7_abs_difference(tree: exp.Expression, question: str) -> list[str]:
    """K4：题面问 difference、SELECT 里有裸减法且全程无 ABS => 提示。"""
    if not _DIFF_WORDS.search(question):
        return []
    if next(tree.find_all(exp.Abs), None) is not None:
        return []
    for sel in getattr(tree, "selects", None) or []:
        if next(sel.find_all(exp.Sub), None) is not None:
            return ["题面问的是 difference（K4：默认取绝对值），SQL 的输出列里"
                    "有减法但没有 ABS——若方向确由题面固定，请在 considered/note "
                    "里说明"]
    return []


def _c7_displaced_dodge(decl: Declarations, question: str) -> list[str]:
    """反投降：题面有位移措辞、声明却 displaced=false => 要求表态。

    防止模型以"无从确定"为由放弃换算、顺手把 displaced 声明为 false，
    让 C2/C4/C5b 全部合法静默。建议级：坚持 false 需要给出理由，不强制改。
    """
    if decl.time_context.displaced or not _DISPLACED_WORDS.search(question):
        return []
    return ["题面含时间位移措辞（at the time of / years ago / in the year "
            "YYYY），但声明 displaced=false——若坚持不位移，请在 "
            "time_context.reference 里写明理由；若确有位移，改 true 并按 "
            "K1 选锚换算"]


# ---------------------------------------------------------------- 总入口

def validate(out: DslOutput, schema_info: SchemaInfo, db_path: Path, *,
             question: str, profile_ids: set[str],
             extra_checks: bool = False,
             convention_checks: bool = False) -> list[str]:
    """全部检查汇总；返回 issue 列表（空 = 通过），文字直接作修复反馈。

    C1–C4 恒开。C5a 由 profile_ids 是否为空自然开关。C5b/C6/C7 是建议级
    检查，默认关闭，由 extra_checks/convention_checks 开关控制（精度见
    scripts/measure_checks.py 与 docs/ABLATION.md）。
    """
    try:
        tree = sqlglot.parse_one(out.sql, dialect="sqlite")
    except Exception as e:
        return [f"SQL 无法按 SQLite 语法解析: {e}"]
    decl = out.declarations
    issues = (_c1_alignment(decl, tree) + _c2_consistency(decl, tree)
              + _c3_grounding(decl, tree, schema_info, db_path)
              + _c4_anchors(decl) + _c5a_considered(decl, profile_ids))
    if extra_checks:
        issues += _c5b_anchor_sql(decl, tree, question)
        issues += _c6_ratio_hint(tree, question, db_path)
    if convention_checks:
        issues += _c7_constants(tree)
        issues += _c7_abs_difference(tree, question)
        issues += _c7_displaced_dodge(decl, question)
    return issues
