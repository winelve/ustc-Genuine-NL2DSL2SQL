"""判负 / 被替代的检查，只被 archive.py 的历史档位引用，主线 validate() 不 import。

归档≠删除（项目规矩）：这些档位跑出过的结果要能一键复跑。

- C5a 画像表态 —— 依赖库画像，画像轴 m3a/m3b 已判负收档
- C5b 锚一致   —— 用户裁决本轮不启用
- C6 比率线索  —— 同上
- C7 三支      —— 手写约定检查，职能被 L2 学习规则覆盖
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlglot import exp

from model.pipeline.dsl.schema import Declarations, DslOutput
from model.pipeline.profile import numeric_columns


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

def validate_archived(out: DslOutput, tree: exp.Expression, db_path: Path, *,
                      question: str, profile_ids: set[str],
                      extra_checks: bool, convention_checks: bool) -> list[str]:
    """归档档位的附加检查；主线 validate() 不调用。"""
    decl = out.declarations
    issues = _c5a_considered(decl, profile_ids)
    if extra_checks:
        issues += _c5b_anchor_sql(decl, tree, question)
        issues += _c6_ratio_hint(tree, question, db_path)
    if convention_checks:
        issues += _c7_constants(tree)
        issues += _c7_abs_difference(tree, question)
        issues += _c7_displaced_dodge(decl, question)
    return issues
