# M3-d 约定知识层（路线 A）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把从 train 错题蒸馏的 Archer 约定（口径/常数/输出形态）做成结构化知识层，
以"prose 注入"与"prose + 机器强制执行"双臂消融，对标 OraPlan 的 guidelines 路线
（其消融显示 guidelines 值 +27.9 EX，而其 no-guidelines 基线 44.23 ≈ 我们当前的 45.19）。

**Architecture:** 约定表（`conventions.py`，纯数据）→ 追加式系统提示词附录
（`dslgen.conventions.md`，基线模板零改动）→ C7 约定检查器（`dsl.py`，修复环里
按违规触发，上线前用 `scripts/measure_checks.py` 对已有 trace 离线测精度）→
两个新模型注册 `m3dp-pro-thinking`（只给 prose）/ `m3dc-pro-thinking`（+C7 强制）。

**Tech Stack:** Python 3.11 / pydantic / sqlglot / pytest（现有栈，零新依赖）。

## Global Constraints

- `archer_eval` 永不 import `model`；路径只写 `config.py`；数据库一律只读；密钥只走环境变量（DEVELOPMENT.md 铁律）。
- 新模型 = 继承 `SQLGenerator` 系 + 在 `model/__init__.py` 的 `MODELS` 注册一行。
- 提交前 `.venv\Scripts\python.exe -m pytest -q` 必须全绿；先写失败测试再实现。
- 提示词与代码分离：所有提示词文本放 `model/pipeline/prompts/*.md`，占位符登记进 `templates.py` 的 `PLACEHOLDERS`。
- **约定条目只从 train 证据立项（≥2 题），dev-only 观察不立项**；每条附 evidence 字段（题号/规模）。
- **通用模板（dslgen.system.md / planner.*）本计划一个字不改**——约定走独立附录文件，保证本周跑出的基线 45.19 与 m3a/b/c 四组数继续可比。
- **不注入 planner**：planner 对 M1/M2/M3a-c 冻结；m3d 的知识只进 dslgen（thinking 骨干下 dslgen 才是干活的人，且避免再触发基线重跑）。
- C7 检查器的正则/阈值只准对 **train** 的测量调参，dev 只看不调。
- 画像（P1..）与约定（K1..）是两个命名空间、两个消融轴，不混用、不叠加计分。

---

### Task 1: 约定表模块 `conventions.py`

**Files:**
- Create: `model/pipeline/conventions.py`
- Test: `tests/test_conventions.py`

**Interfaces:**
- Produces: `CONVENTIONS: list[Convention]`（字段 `id/text/evidence`）、
  `conventions_block() -> str`（K1..Kn 编号文本块，供 Task 2 渲染进附录）。

- [ ] **Step 1: 写失败测试**

```python
"""tests/test_conventions.py — 约定表的红线与格式。"""
import re

from model.pipeline.conventions import CONVENTIONS, conventions_block


def test_conventions_capped_at_twelve():
    """条目 ≤12：超了说明在往逐题答案滑（立项红线）。"""
    assert 1 <= len(CONVENTIONS) <= 12


def test_every_convention_cites_train_evidence():
    """每条必须带 train 证据引用；dev 是考卷，dev-only 不立项。"""
    for c in CONVENTIONS:
        assert "train" in c.evidence, c.id


def test_conventions_text_is_english_prompt_ready():
    for c in CONVENTIONS:
        assert not any("一" <= ch <= "鿿" for ch in c.text), c.id
        assert "\n" not in c.text and len(c.text) >= 20, c.id


def test_conventions_do_not_name_dev_db_columns():
    """条目措辞必须泛化——不得出现 dev 两库的专属列名/表名。"""
    banned = re.compile(r"GNPOld|Song_release_year|Stadium|concert_singer|world_1",
                        re.I)
    for c in CONVENTIONS:
        assert not banned.search(c.text), c.id


def test_block_numbers_are_stable_reference_keys():
    block = conventions_block()
    for i, c in enumerate(CONVENTIONS, 1):
        assert f"K{i}. " in block
        assert c.id == f"K{i}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conventions.py -q`
Expected: FAIL（ModuleNotFoundError: model.pipeline.conventions）

- [ ] **Step 3: 实现**

```python
"""model/pipeline/conventions.py — Archer 约定表（M3-d，路线 A 主线）。

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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conventions.py -q`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add model/pipeline/conventions.py tests/test_conventions.py
git commit -m "feat(m3d): Archer 约定表——train 蒸馏 11 条，红线测试锁死"
```

---

### Task 2: 附录模板 + DeclareStage 接线（prose 注入臂）

**Files:**
- Create: `model/pipeline/prompts/dslgen.conventions.md`
- Modify: `model/pipeline/templates.py`（PLACEHOLDERS 登记一行）
- Modify: `model/pipeline/stages/declare.py`（`conventions` 参数，system 消息追加附录）
- Test: `tests/test_pipeline.py`（追加两条）

**Interfaces:**
- Consumes: `conventions_block()`（Task 1）。
- Produces: `DeclareStage(..., conventions: bool = False)`；
  关闭时 system 消息与现状**逐字节相同**（有测试锁死）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_pipeline.py`）

```python
def test_dslgen_system_byte_identical_when_conventions_off():
    """conventions=False 时 system 消息与本周基线完全一致——45.19 不作废。"""
    from model.pipeline.stages.declare import DeclareStage
    from model.pipeline.templates import load_template

    stage = DeclareStage(endpoint=None)
    assert stage._system() == load_template("dslgen.system")


def test_dslgen_system_carries_conventions_when_on():
    from model.pipeline.conventions import CONVENTIONS
    from model.pipeline.stages.declare import DeclareStage
    from model.pipeline.templates import load_template

    stage = DeclareStage(endpoint=None, conventions=True)
    system = stage._system()
    assert system.startswith(load_template("dslgen.system"))
    for c in CONVENTIONS:
        assert f"{c.id}. " in system
    # 反投降条款必须在场：中性事实诱发推理放弃是 m3a 的实锤教训
    assert "not a valid stance" in system
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q -k conventions`
Expected: FAIL（DeclareStage 无 `_system`/`conventions`）

- [ ] **Step 3: 写附录模板** `model/pipeline/prompts/dslgen.conventions.md`

```markdown
Benchmark conventions (fixed rules of this dataset; they override your own
preferences whenever both are defensible):

{conventions}

Declaration discipline: when a stored value's reference time is not recorded,
"cannot be determined" is not a valid stance - K1 applies and you must still
pick an explicit anchor (now/column/literal) and carry it through the SQL.
```

- [ ] **Step 4: 登记占位符**（`templates.py` 的 `PLACEHOLDERS` 加一行）

```python
    "dslgen.conventions": {"conventions"},
```

- [ ] **Step 5: DeclareStage 接线**（`declare.py`）

```python
# __init__ 签名追加参数（默认 False，基线行为不变）：
    def __init__(self, endpoint: ChatEndpoint, max_repairs: int = 2, *,
                 use_profile: bool = False, force_considered: bool = False,
                 extra_checks: bool = False, conventions: bool = False) -> None:
        ...
        self.conventions = conventions

# 新增方法（run 里的 system = load_template(...) 改为 system = self._system()）：
    def _system(self) -> str:
        """基线模板 + 可选约定附录。附录是追加式的——基线消息逐字节不变。"""
        system = load_template("dslgen.system")
        if self.conventions:
            from model.pipeline.conventions import conventions_block
            system += "\n" + render("dslgen.conventions",
                                    conventions=conventions_block())
        return system
```

- [ ] **Step 6: 全量测试**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
git add model/pipeline/prompts/dslgen.conventions.md model/pipeline/templates.py model/pipeline/stages/declare.py tests/test_pipeline.py
git commit -m "feat(m3d): 约定附录追加式注入 dslgen——基线消息逐字节不变"
```

---

### Task 3: C7 约定检查器（机器强制执行臂）

**Files:**
- Modify: `model/pipeline/dsl.py`（三个检查器 + `validate` 新开关）
- Test: `tests/test_dsl.py`（追加一节）

**Interfaces:**
- Produces: `validate(..., convention_checks: bool = False)`；
  `_c7_constants(tree)`、`_c7_abs_difference(decl_tree, question)`、
  `_c7_displaced_dodge(decl, question)`，各返回 `list[str]`。
- 三个检查器都是**建议级**：文字引用 K 编号，模型可反驳（同 C6 哲学）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_dsl.py`，沿用 toy_db fixture）

```python
# ---------------------------------------------------------- C7 约定检查

def _validate_conv(toy_db, sql, question, declarations=None):
    from model.pipeline.dsl import DslOutput, load_schema_info, validate

    decl = declarations or {
        "time_context": {"displaced": False, "reference": ""},
        "outputs": [{"name": "a", "source": "column", "column": "singer.Age"}],
        "assumptions": [], "considered": []}
    out = DslOutput.model_validate({"sql": sql, "declarations": decl})
    return validate(out, load_schema_info(toy_db), toy_db, question=question,
                    profile_ids=set(), convention_checks=True)


def test_c7_flags_offbrand_constants(toy_db):
    issues = _validate_conv(
        toy_db, "SELECT Age * 0.453592 AS kg FROM singer", "weight in kg?")
    assert any("K3" in i for i in issues), issues


def test_c7_flags_julianday_age(toy_db):
    issues = _validate_conv(
        toy_db, "SELECT julianday('now')/365.25 AS y FROM singer", "how old?")
    assert any("K2" in i for i in issues), issues


def test_c7_silent_on_archer_constants(toy_db):
    issues = _validate_conv(
        toy_db, "SELECT Age * 0.45 AS kg FROM singer", "weight in kg?")
    assert not [i for i in issues if "K3" in i], issues


def test_c7_abs_difference_hint(toy_db):
    issues = _validate_conv(
        toy_db, "SELECT MAX(Age) - MIN(Age) AS d FROM singer",
        "What is the difference between the oldest and youngest age?")
    assert any("K4" in i for i in issues), issues


def test_c7_abs_silent_when_abs_present(toy_db):
    issues = _validate_conv(
        toy_db, "SELECT ABS(MAX(Age) - MIN(Age)) AS d FROM singer",
        "What is the difference between the oldest and youngest age?")
    assert not [i for i in issues if "K4" in i], issues


def test_c7_displaced_dodge_challenged(toy_db):
    issues = _validate_conv(
        toy_db, "SELECT Name, Age FROM singer",
        "List the age of each singer at the time of the first concert.")
    assert any("displaced" in i for i in issues), issues


def test_c7_all_silent_by_default(toy_db):
    """convention_checks 默认关——m3a/b/c 与基线行为不变。"""
    import inspect
    from model.pipeline.dsl import validate

    assert inspect.signature(validate).parameters[
        "convention_checks"].default is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dsl.py -q -k c7`
Expected: FAIL（validate 无 convention_checks 参数）

- [ ] **Step 3: 实现**（`dsl.py`，C6 之后新增一节；docstring 里的精度数字由 Task 4 实测后回填）

```python
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
    r"\bwould (?:have|be)\b|\bin the year \d{4}\b", re.I)


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
                "SQL 用了 julianday/365.25 计算年数（K2）——本数据集的整年公式是 "
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

    m3a 的实锤（dev #4/#5）：模型以"无从确定"为由放弃换算并顺手声明
    displaced=false，C2/C4/C5b 全部合法静默。这一条堵的就是那扇门。
    建议级：模型坚持 false 需要给出理由（写进 reference），不强制改。
    """
    if decl.time_context.displaced or not _DISPLACED_WORDS.search(question):
        return []
    return ["题面含时间位移措辞（at the time of / years ago / would have…），"
            "但声明 displaced=false——若坚持不位移，请在 time_context.reference "
            "里写明理由；若确有位移，改 true 并按 K1 选锚换算"]
```

`validate` 签名与出口：

```python
def validate(out: DslOutput, schema_info: SchemaInfo, db_path: Path, *,
             question: str, profile_ids: set[str],
             extra_checks: bool = False,
             convention_checks: bool = False) -> list[str]:
    ...
    if extra_checks:
        issues += _c5b_anchor_sql(decl, tree, question)
        issues += _c6_ratio_hint(tree, question, db_path)
    if convention_checks:
        issues += _c7_constants(tree)
        issues += _c7_abs_difference(tree, question)
        issues += _c7_displaced_dodge(decl, question)
    return issues
```

- [ ] **Step 4: 全量测试**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add model/pipeline/dsl.py tests/test_dsl.py
git commit -m "feat(m3d): C7 约定检查器——规定常数/ABS/反投降，建议级默认关"
```

---

### Task 4: 离线精度测量脚本（进版本库）+ 用 train 实测定去留

**Files:**
- Create: `scripts/measure_checks.py`
- Modify: `model/pipeline/dsl.py`（把实测数字回填进 C7 各函数 docstring）

**Interfaces:**
- Consumes: `predictions/m2-dslsql/dslsql-pro-thinking_en_{dev,train}.trace.json`、
  同名 `.json` 预测、`results/m2-dslsql/en_{dev,train}_dslsql-pro-thinking.json`。
- Produces: CLI `python scripts/measure_checks.py --split train`，输出每个检查器的
  触发题号 / useful（原判错）/ harmful（原判对）。

- [ ] **Step 1: 实现脚本**（无单测，本身就是测量工具；跑通即验证）

```python
"""对已有预测/trace 离线测量建议级检查器的精度，杜绝"数字凭空来"。

用法:
    python scripts/measure_checks.py --split train
    python scripts/measure_checks.py --split dev --pred predictions/... --results results/...

"useful" = 触发且该题原判错（提示有机会救）；"harmful" = 触发但原判对（白烧修复轮）。
调参纪律：只准对 train 的输出调正则/阈值，dev 只看不调。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sqlglot

import config
from model.pipeline.dsl import (Declarations, _c5b_anchor_sql, _c6_ratio_hint,
                                _c7_abs_difference, _c7_constants,
                                _c7_displaced_dodge)

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "dev": ("predictions/m2-dslsql/dslsql-pro-thinking_en_dev",
            "results/m2-dslsql/en_dev_dslsql-pro-thinking.json"),
    "train": ("predictions/m2-dslsql/dslsql-pro-thinking_en_train",
              "results/m2-dslsql/en_train_dslsql-pro-thinking.json"),
}


def last_declarations(trace_item: dict) -> dict | None:
    checks = None
    for cand in trace_item.get("candidates", []):
        if cand.get("checks"):
            checks = cand["checks"]
    if not checks:
        return None
    for r in reversed(checks.get("rounds") or []):
        if r.get("declarations"):
            return r["declarations"]
    return checks.get("declarations")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "train"], required=True)
    ap.add_argument("--pred")      # 不带扩展名的预测文件前缀，默认 M2 归档
    ap.add_argument("--results")
    args = ap.parse_args()
    stem, res = DEFAULTS[args.split]
    stem, res = args.pred or stem, args.results or res

    data = json.load(open(ROOT / "data" / "en_data" / f"{args.split}.json",
                          encoding="utf-8"))
    preds = json.load(open(ROOT / f"{stem}.json", encoding="utf-8"))
    trace = json.load(open(ROOT / f"{stem}.trace.json", encoding="utf-8"))
    match = {s["index"]: s["match"] for s in json.load(
        open(ROOT / res, encoding="utf-8"))["samples"]}

    hits: dict[str, list[int]] = {}
    for i, (item, sql, tr) in enumerate(zip(data, preds, trace)):
        try:
            tree = sqlglot.parse_one(sql, dialect="sqlite")
        except Exception:
            continue
        db = config.DB_DIR / item["db_id"] / f"{item['db_id']}.sqlite"
        q = item["question"]
        checks = {
            "C6": _c6_ratio_hint(tree, q, db),
            "C7-const": _c7_constants(tree),
            "C7-abs": _c7_abs_difference(tree, q),
        }
        raw = last_declarations(tr)
        if raw:
            try:
                decl = Declarations.model_validate(raw)
                checks["C5b"] = _c5b_anchor_sql(decl, tree, q)
                checks["C7-dodge"] = _c7_displaced_dodge(decl, q)
            except Exception:
                pass
        for name, issues in checks.items():
            if issues:
                hits.setdefault(name, []).append(i)

    for name in sorted(hits):
        idx = hits[name]
        useful = [i for i in idx if not match[i]]
        harmful = [i for i in idx if match[i]]
        print(f"{name}: 触发 {len(idx)} | useful {len(useful)} {useful} "
              f"| harmful {len(harmful)} {harmful}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 对 train 实测**

Run: `.venv\Scripts\python.exe scripts/measure_checks.py --split train`
Expected: 每个检查器一行触发/useful/harmful。

- [ ] **Step 3: 按结果定去留（决策规则写死，不临场发挥）**

- `harmful > useful` 的检查器：先收窄触发条件重测一次；仍然倒挂 → 从
  `convention_checks` 出口移除（代码留着，docstring 记"实测倒挂，未启用"）。
- 通过的检查器：把 train 数字回填进 docstring（格式沿用 C5b/C6），
  再跑一次 `--split dev` 把 dev 数字也记上（只记录，不调参）。

- [ ] **Step 4: 全量测试 + 提交**

```bash
.venv\Scripts\python.exe -m pytest -q
git add scripts/measure_checks.py model/pipeline/dsl.py
git commit -m "feat(m3d): 检查器离线测量脚本进库——C7 精度以 train 实测定去留"
```

---

### Task 5: 注册 m3dp / m3dc 双臂 + preview 支持

**Files:**
- Modify: `model/pipeline/plansql.py`（DSLSQL 两个新开关 + 两个新类）
- Modify: `model/pipeline/stages/declare.py`（透传 convention_checks 到 validate）
- Modify: `model/__init__.py`（MODELS 注册两行）
- Modify: `model/pipeline/__main__.py`（preview 增加附录段）
- Test: `tests/test_pipeline.py`（开关矩阵断言）

**Interfaces:**
- Consumes: Task 2 的 `conventions` 参数、Task 3 的 `convention_checks`。
- Produces: MODELS 新键 `m3dp-pro-thinking` / `m3dc-pro-thinking`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_pipeline.py` 的开关矩阵测试旁）

```python
def test_m3d_switch_matrix():
    """m3d 双臂：prose 臂只开 conventions，check 臂再开 convention_checks；
    画像/表态/C5bC6 三开关全关——约定轴与画像轴不叠加。"""
    from model.pipeline.plansql import M3DC, M3DP

    for cls in (M3DP, M3DC):
        assert (cls.use_profile, cls.force_considered, cls.extra_checks) \
            == (False, False, False)
    assert (M3DP.conventions, M3DP.convention_checks) == (True, False)
    assert (M3DC.conventions, M3DC.convention_checks) == (True, True)


def test_baseline_and_m3abc_keep_conventions_off():
    from model.pipeline.plansql import DSLSQLPro, M3A, M3B, M3C

    for cls in (DSLSQLPro, M3A, M3B, M3C):
        assert (cls.conventions, cls.convention_checks) == (False, False)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q -k m3d`
Expected: FAIL（ImportError: M3DP）

- [ ] **Step 3: 实现**

`plansql.py`——`DSLSQL` 类属性区追加两行开关并透传给 DeclareStage：

```python
    force_considered = False
    extra_checks = False
    conventions = False          # M3-d：约定附录进 dslgen system（prose 臂）
    convention_checks = False    # M3-d：C7 约定检查器（强制执行臂）

    def _stages(self) -> list:
        return [
            PlanStage(self.endpoint, self.n_plans, self.plan_temperature,
                      use_profile=self.use_profile),
            DeclareStage(self.endpoint, self.max_repairs,
                         use_profile=self.use_profile,
                         force_considered=self.force_considered,
                         extra_checks=self.extra_checks,
                         conventions=self.conventions,
                         convention_checks=self.convention_checks),
            VoteStage(),
        ]
```

文件末尾追加双臂（注意基类是 DSLSQLPro，不是 M3 系——约定轴与画像轴分开）：

```python
class M3DP(DSLSQLPro):
    """M3-d prose 臂：train 蒸馏的约定表以 guidelines 文本注入 dslgen。

    对照系即 OraPlan 的做法（其消融：guidelines 值 +27.9）。
    与画像轴（m3a/b/c）互斥不叠加——约定对齐的分数单独归因。
    """

    name = "m3dp-pro-thinking"
    conventions = True


class M3DC(M3DP):
    """M3-d 强制臂：同一份约定 + C7 检查器在修复环里按违规触发。

    m3dc − m3dp = "机器强制执行约定"的净值——路线 A 的中心论据
    （dev #40 的 C6 轨迹已证明决策点挑战能顶动模型，此处推广到约定族）。
    """

    name = "m3dc-pro-thinking"
    convention_checks = True
```

`declare.py`——`__init__` 追加 `convention_checks: bool = False` 存为
`self.convention_checks`，`run` 里 `validate(...)` 调用追加
`convention_checks=self.convention_checks`。

`model/__init__.py`——注册（沿用现有 m3a/b/c 的写法）：

```python
from model.pipeline.plansql import M3DC, M3DP
# MODELS 字典追加：
    "m3dp-pro-thinking": M3DP,
    "m3dc-pro-thinking": M3DC,
```

`__main__.py`——sections 列表追加一段（放 dslgen system 之后）：

```python
        ("dslgen system 附录 [仅 m3d]",
         render("dslgen.conventions", conventions=conventions_block())),
```

并在文件头部加 `from model.pipeline.conventions import conventions_block`。

- [ ] **Step 4: 全量测试 + preview 冒烟**

```bash
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m model.pipeline --data en_dev --preview 3
```
Expected: 全绿；preview 多出附录段，K1..K11 可见。

- [ ] **Step 5: 提交**

```bash
git add model/pipeline/plansql.py model/pipeline/stages/declare.py model/__init__.py model/pipeline/__main__.py tests/test_pipeline.py
git commit -m "feat(m3d): 注册 m3dp/m3dc 双臂——prose vs prose+C7 强制"
```

---

### Task 6: 文档收尾 + 交给用户的实验协议

**Files:**
- Modify: `docs/PROGRESS.md`

- [ ] **Step 1: PROGRESS 更新**，写入三块：

1. **路线 A 决策记录**（2026-07-23，用户拍板）：约定=知识，M3-d 升格主线；
   依据 = OraPlan 消融（guidelines +27.9 / no-guidelines 44.23 ≈ 我们 45.19）
   + 真知 NL2KE 架构（知识=带定义的词表+强制绑定）+ 本项目 CK 审计
   （97/133 条模型本来就会）。
2. **m3a/m3b 判负收档**：前置注入中性事实在 dev 实测 −2.9/−1.9（均在噪声内，
   McNemar p≥0.65），且有因果实锤（#4/#5 considered 投降原话 + displaced=false
   逃生门）。注册项保留作对照，路线关闭。
3. **m3d 实验协议**（用户执行）：

```
.venv\Scripts\python.exe -m model --model m3dp-pro-thinking --data en_dev --eval
.venv\Scripts\python.exe -m model --model m3dc-pro-thinking --data en_dev --eval
```

   读数方式（写死，防临场脑补）：
   - 对照点 = 本周基线 45.19（`results/en_dev_dslsql-pro-thinking.json`，
     模板未动所以继续有效）。
   - m3dp − 45.19 = prose 约定的价值；m3dc − m3dp = 机器强制的净值。
   - 每步逐题翻转表 + McNemar（脚本沿用本周做法）；|净差| ≤ 3 题按噪声报告。
   - **预期量级**：dev 错题里约定族目标 ≥ 20 题（时间锚 18、形态 8、
     反事实模板、per-capita……有重叠），若 m3dc 仍在噪声区，
     路线 A 的 dev 上限即到，转 zh_dev / 报告机制发现。
   - train 上**不评测主数**（约定蒸馏自 train，评了算污染）；
     只可跑 sanity（预期大涨，涨幅只写"上界"不写结论）。

- [ ] **Step 2: 提交**

```bash
git add docs/PROGRESS.md
git commit -m "docs(m3d): 路线 A 落地——约定双臂协议 + m3a/b 判负收档"
```

---

## Self-Review 结论

- **覆盖**：路线 A 的四件事（约定表、双臂注入、强制执行、收档）各有任务；
  反投降条款进了附录（Task 2）与 C7-dodge（Task 3）双保险。
- **占位符扫描**：无 TBD；C7 docstring 精度数字明确标注"Task 4 实测后回填"，
  且回填动作是 Task 4 Step 3 的显式步骤。
- **类型一致**：`conventions_block()`（T1→T2/T5）、`conventions` /
  `convention_checks` 开关名（T2/T3→T5）、`_c7_*` 签名（T3→T4）已交叉核对。
- **已知风险**：① K 条目 11 条全进 system prompt 约 +250 token/题——可接受；
  ② C7-dodge 的位移正则可能高误报，Task 4 的 train 测量是它的生死关；
  ③ m3dp 若像 OraPlan 一样吃掉大部分涨幅，m3dc 的增量可能落进噪声——
  协议里已写死"≤3 题按噪声报告"，不许硬解释。
