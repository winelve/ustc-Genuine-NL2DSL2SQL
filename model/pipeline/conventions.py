"""model/pipeline/conventions.py — Archer 约定表。

从 train 错题蒸馏的口径/常数/输出形态约定。三条红线：
1. 只收 train 证据 ≥2 题的条目；dev 观察只能佐证，不能立项（dev 是考卷）。
2. 措辞泛化：说规则，不点 dev 库的任何列名（有测试锁死）。
3. 条目 ≤12，超了 = 在往逐题答案滑。
evidence 字段只进文档与审计，不进 prompt。
对照系：OraPlan 附录 5.1 的 guidelines 覆盖其中 K6/K8 两族，
其消融显示该类知识在 GPT-5 上值 +27.9 EX（44.23 → 72.12）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Convention:
    id: str          # K1..Kn —— prompt 与 trace 的引用键
    text: str        # 进 prompt 的英文陈述（一行）
    evidence: str    # train 证据（题号/规模），进文档不进 prompt


CONVENTIONS: list[Convention] = [
    Convention("K1",
        "When a computation needs a reference time and none is recorded, "
        "anchor at query time via strftime('%Y','now') or date('now'); "
        "never invent a fixed year.",
        "train gold 全域用 'now'（driving_school/formula_1 年龄题 26+ 题）"),
    Convention("K2",
        "Whole-year age or duration is strftime('%Y',b)-strftime('%Y',a)"
        "-(strftime('%m-%d',b)<strftime('%m-%d',a)); never julianday()/365.25.",
        "train B-1：26 错题中 17 题式不合（driving_school 为主）"),
    Convention("K3",
        "Unit conversions use exactly: 1 lb = 0.45 kg, 1 inch = 25 mm, "
        "1 mile = 1.609344 km - even where a more precise constant exists.",
        "train B-2：soccer #314-#317/#351/#358-#361、bike #30-#37，12+ 题"),
    Convention("K4",
        "A 'difference between A and B' means ABS(A-B) unless the question "
        "fixes the direction of subtraction.",
        "train B-6：bike #34-#37、soccer #318-#323/#340/#341/#352（一致可学）"),
    Convention("K5",
        "When adding a year and a fractional quantity, truncate the result "
        "with CAST(... AS INT).",
        "train：hospital #224-#227"),
    Convention("K6",
        "A hypothetical 'if X is v' rewrites v into every matching row "
        "(UNION ALL of rewritten matching rows and untouched rest); it is "
        "never a filter and never a total to spread across rows.",
        "train 2.4：driving_school/wine_1/customers/soccer_1 全模板；wine #373"),
    Convention("K7",
        "In tables holding multiple dated snapshots per entity, an entity's "
        "attribute means an aggregate over its full history (e.g. MAX(expr) "
        "GROUP BY entity), not the latest snapshot only.",
        "train B-4：soccer_1 走最新快照路线 20 错 3 对"),
    Convention("K8",
        "A share/percentage is a single output column computed as "
        "100.0 * part / total with float division; do not output the "
        "intermediate counts as extra columns.",
        "train 2.3(b)：hospital #236/#244、riding_club #263、wine #363"),
    Convention("K9",
        "Spell proper nouns exactly as stored in the database (verify against "
        "sample rows); but when the question itself supplies a number, use "
        "that literal number instead of recomputing it.",
        "train A-5：driving_school #108/#109 vs formula_1 #183/#197、bike #15、customers #206/#207"),
    Convention("K10",
        "An 'average per-capita X' over a group is SUM(X)/SUM(population), "
        "not AVG(X/population).",
        "train #90/#91（与 dev #102/#103 同分歧，train 侧立项）"),
    Convention("K11",
        "When a question asks for 'the highest and lowest ... respectively', "
        "output one wide row with a column per superlative, not one row per "
        "entity.",
        "train 2.3(a)：soccer #330/#331、wine #394-#397"),
]


def conventions_block() -> str:
    """K1..Kn 编号块；编号即 trace/审计里的引用键。"""
    return "\n".join(f"{c.id}. {c.text}" for c in CONVENTIONS)
