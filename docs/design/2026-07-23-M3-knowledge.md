# M3 知识层实施计划：库画像 + 强制表态 + 校验扩充

> **执行者须知**：分支 `dsl`，逐任务 TDD，每任务末尾提交。
> 提交前 `.venv\Scripts\python.exe -m pytest -q` 必须全绿。

**目标**：给 dslgen 注入**程序可确定的库事实**，并强制模型对每条事实表态，
再补两个校验器把"声明对了但 SQL 没跟上"抓出来。

**架构**：三层互不耦合——
`profile.py`（只读库，产出事实条目）→ `dslgen` prompt（注入 + 强制表态槽位）
→ `dsl.py` 校验器（表态完整性 C5a、比率线索 C6、锚一致性 C5b）。
三层各由一个开关控制，构成 M3-a/b/c 三档消融。

**依据**：`docs/analysis/2026-07-23-cot-failure-analysis.md`（dev）+
`2026-07-23-train-cot-failure-analysis.md`（train）。每个组件下方注明它对哪些题。

## 全局约束

- 分支 `dsl`，不新建分支；不动 `archer_eval/`、不动 M1 的 planner/vote 相关文件
- `archer_eval` 永远不准 import `model`；数据库一律 `mode=ro` 只读
- 新模型 = 继承 + 在 `model/__init__.py` 的 `MODELS` 注册
- 库画像**只出程序能确定的事实**，不写任何 Archer 专属口径、不写任何 dev 库的人工知识
- 提示词模板占位符必须同步登记进 `templates.PLACEHOLDERS`，否则加载即报错

## 预期命中（来自错因分析，非预测分数）

| 组件 | dev 目标题 | train 目标题 |
|---|---|---|
| 画像·存量时点列 | #2 #3 #4 #5 #12 #13 #14 #15 #20 #21 #23（~15） | — |
| 画像·时间成对列 | #74 #75 #90 #91（4） | — |
| 画像·多版本表 | — | soccer_1 约 20 |
| 画像·空表 | — | formula_1 #179 #184–#187（5） |
| C6 比率线索 | #24 #25 #33 #40 #41（5） | — |
| C5b 锚一致性 | #3 #4 #14（3） | #158–#161（4） |

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `model/pipeline/profile.py` | 库画像生成 + 数值列查询助手 | **新建** |
| `model/pipeline/dsl.py` | 加 `Considered` 模型、C5a/C5b/C6、`validate` 签名 | 修改 |
| `model/pipeline/templates.py` | `dslgen.user` 加 `profile` 占位符 | 修改 |
| `model/pipeline/prompts/dslgen.{system,user}.md` | 注入画像 + 说明 `considered`/`anchors` | 修改 |
| `model/pipeline/stages/declare.py` | 取画像、传 question、三个开关 | 修改 |
| `model/pipeline/plansql.py` | M3 三档消融子类 | 修改 |
| `model/__init__.py` | 注册 | 修改 |
| `tests/test_profile.py` | 画像生成器测试（打真库，只读） | **新建** |
| `tests/test_dsl.py` | 新校验器测试 | 修改 |

---

### Task 1: 库画像生成器

**Files:**
- Create: `model/pipeline/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `build_profile(db_path: Path) -> list[str]` —— 事实条目，每条一句完整中文
  - `numeric_columns(db_path: Path) -> dict[str, list[str]]` —— 表名(小写) → 非 ID 数值列原名

- [ ] **Step 1: 写失败测试**

`tests/test_profile.py`：

```python
"""库画像生成器：打真实库（只读），断言四类规则命中与不命中。"""
from pathlib import Path

import pytest

from model.pipeline.profile import build_profile, numeric_columns

DB = Path(__file__).resolve().parents[1] / "database"


def _profile(name: str) -> list[str]:
    return build_profile(DB / name / f"{name}.sqlite")


def test_stock_age_column_detected():
    """concert_singer.singer 有 Age 但无出生日期列 -> 必须报存量时点列。"""
    lines = _profile("concert_singer")
    hits = [x for x in lines if "singer.Age" in x]
    assert len(hits) == 1, lines
    assert "出生年" in hits[0]


def test_average_is_not_mistaken_for_age():
    """'Average' 含子串 'age'，不得被当成年龄列。"""
    assert not [x for x in _profile("concert_singer") if "stadium.Average" in x]


def test_old_new_pair_detected():
    lines = _profile("world_1")
    assert [x for x in lines if "GNPOld" in x and "GNP" in x], lines


def test_empty_table_detected():
    lines = _profile("formula_1")
    assert [x for x in lines if "lapTimes" in x and "0 行" in x], lines


def test_snapshot_table_detected():
    lines = _profile("soccer_1")
    assert [x for x in lines if "Player_Attributes" in x and "快照" in x], lines


def test_event_table_not_reported_as_snapshot():
    """results 的外键指向 3 张表 -> 事件表，不是快照表。"""
    assert not [x for x in _profile("formula_1")
                if "results" in x and "快照" in x]


@pytest.mark.parametrize("name", ["concert_singer", "world_1", "formula_1",
                                  "soccer_1", "bike_1", "wine_1",
                                  "hospital_1", "riding_club", "driving_school",
                                  "customers_and_products_contacts"])
def test_profile_stays_small(name):
    """画像必须短——长了就稀释注意力，也说明规则失控。"""
    assert len(_profile(name)) <= 6


def test_numeric_columns_excludes_ids():
    cols = numeric_columns(DB / "concert_singer" / "concert_singer.sqlite")
    assert "Capacity" in cols["stadium"] and "Average" in cols["stadium"]
    assert "Stadium_ID" not in cols["stadium"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_profile.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'model.pipeline.profile'`

- [ ] **Step 3: 实现**

`model/pipeline/profile.py`：

```python
"""库画像：只读 schema + 数据分布，产出少量**程序能确定**的事实条目。

只出四类，绝不猜语义：
  存量时点列 / 时间成对列 / 多版本快照表 / 空表

刻意不出"数值列对（比率候选）"——组合爆炸（soccer_1 的 Player_Attributes
一张表就有 1264 组），进 prompt 只会稀释注意力。比率线索改由
dsl._c6_ratio_hint 在校验时按需触发：题面有比率词、SQL 又只用了同表数值列
中的一个，才提示。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

# (^|_)age(s)?($|_) —— 'Age'/'player_age' 命中，'Average' 不命中（子串陷阱）
_AGE = re.compile(r"(^|_)ages?($|_)", re.I)
_BIRTH = re.compile(r"dob|birth", re.I)
_SNAPDATE = re.compile(r"^(date|time|timestamp|.*_date|.*_time)$", re.I)
_IDISH = re.compile(r"(^|_)id$|^id$", re.I)
_OLD_SUFFIX = ("old", "prev", "last", "_old", "_prev")
_NUMERIC = ("INT", "REAL", "NUM", "DOUB", "FLOA", "DEC")


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]


def _is_numeric(decl_type: str) -> bool:
    return any(k in (decl_type or "").upper() for k in _NUMERIC)


def numeric_columns(db_path: Path) -> dict[str, list[str]]:
    """表名(小写) -> 非 ID、非主键的数值列原名。C6 与画像共用。"""
    conn = _connect(db_path)
    try:
        out: dict[str, list[str]] = {}
        for t in _tables(conn):
            out[t.lower()] = [
                r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')
                if _is_numeric(r[2]) and not r[5] and not _IDISH.search(r[1])
            ]
        return out
    finally:
        conn.close()


def build_profile(db_path: Path) -> list[str]:
    """产出事实条目；每条自成一句，调用方负责编号。"""
    conn = _connect(db_path)
    try:
        lines: list[str] = []
        for t in _tables(conn):
            cols = [(r[1], r[2], r[5]) for r
                    in conn.execute(f'PRAGMA table_info("{t}")')]
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if n == 0:
                lines.append(
                    f"空表 {t}：0 行——列名看着匹配也查不出东西，"
                    f"先确认同义数据是否在别的表里")
                continue
            lines += _stock_age(t, cols)
            lines += _old_new_pair(t, cols)
            lines += _snapshot(conn, t, cols, n)
        return lines
    finally:
        conn.close()


def _stock_age(table: str, cols: list[tuple]) -> list[str]:
    """年龄类数值列 + 本表无出生日期列 => 该值只能锚在录入时点。"""
    if any(_BIRTH.search(c) for c, _, _ in cols):
        return []
    return [
        f"存量时点列 {table}.{c}：本表没有出生日期列，该值只能是**录入时点**的"
        f"年龄；要换算到任何其他时点，先回推 出生年 = 录入年 - {table}.{c}"
        for c, ty, _ in cols if _AGE.search(c) and _is_numeric(ty)
    ]


def _old_new_pair(table: str, cols: list[tuple]) -> list[str]:
    """X 与 XOld 同表 => 涉及"增长/变化"时基准是 XOld。"""
    by_lower = {c.lower(): c for c, _, _ in cols}
    lines = []
    for c, _, _ in cols:
        for suffix in _OLD_SUFFIX:
            base = c.lower()[:-len(suffix)]
            if c.lower().endswith(suffix) and base in by_lower:
                lines.append(
                    f"时间成对列 {table}.{by_lower[base]}(现值) / {table}.{c}(旧值)："
                    f"问"增长/变化"时基准列是 {c}，不是题面里别的对照量")
    return lines


def _snapshot(conn: sqlite3.Connection, table: str,
              cols: list[tuple], n_rows: int) -> list[str]:
    """多版本快照表：有快照日期列 + 外键只指向一张表 + 每个外键多行。

    "外键只指向一张表"是快照表与事件表的判别式：快照挂在单个实体上
    （Player_Attributes -> Player），事件表连接多个实体
    （results -> races/drivers/constructors，Lessons -> Staff/Customers/Vehicles）。
    """
    date_cols = [c for c, _, _ in cols if _SNAPDATE.match(c)]
    if not date_cols:
        return []
    fks = list(conn.execute(f'PRAGMA foreign_key_list("{table}")'))
    if len({r[2] for r in fks}) != 1:
        return []
    for col, _, pk in cols:
        if pk or col not in {r[3] for r in fks}:
            continue
        n_keys = conn.execute(
            f'SELECT COUNT(DISTINCT "{col}") FROM "{table}"').fetchone()[0]
        if n_keys and n_rows / n_keys >= 2:
            return [f"多版本表 {table}：每个 {col} 平均 {n_rows / n_keys:.0f} 条带 "
                    f"{date_cols[0]} 的快照——必须明示是取全历史聚合还是取最新一条"]
    return []
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_profile.py -q`
Expected: PASS，16 passed

- [ ] **Step 5: 人工核对画像全文（不可跳过）**

Run:
```bash
.venv/Scripts/python.exe -c "
from pathlib import Path; from model.pipeline.profile import build_profile
import glob
for db in sorted(glob.glob('database/*/[a-z]*.sqlite')):
    ls = build_profile(Path(db))
    print(f'### {Path(db).stem}  ({len(ls)} 条)')
    for x in ls: print('  -', x)
"
```
Expected：10 库合计约 9 条；`concert_singer` 恰好 1 条（`singer.Age`）、
`world_1` 恰好 1 条（`GNP/GNPOld`）、`formula_1` 含 `lapTimes`/`pitStops` 两条空表、
`soccer_1` 含 `Player_Attributes`。
**若某库超过 6 条或出现明显误报，停下来收紧规则再继续。**

- [ ] **Step 6: 提交**

```bash
git add model/pipeline/profile.py tests/test_profile.py
git commit -m "feat(m3): 库画像生成器——存量时点列/时间成对列/多版本表/空表

四类都只用程序可确定的信号，不猜语义。刻意不出数值列对：
soccer_1 单表就有 1264 组，进 prompt 只稀释注意力，改由 C6 按需触发。
快照表与事件表的判别式 = 外键是否只指向一张表。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 画像进 prompt + `considered` 强制表态 + C5a 表态完整性

**Files:**
- Modify: `model/pipeline/dsl.py`（加 `Considered`、`Declarations.considered`、`_c5a_considered`、`validate` 签名）
- Modify: `model/pipeline/templates.py:26`（`dslgen.user` 占位符集）
- Modify: `model/pipeline/prompts/dslgen.user.md`、`dslgen.system.md`
- Modify: `model/pipeline/stages/declare.py`
- Test: `tests/test_dsl.py`

**Interfaces:**
- Consumes: `profile.build_profile(db_path) -> list[str]`
- Produces:
  - `dsl.render_profile(items: list[str]) -> str` —— 编号成 `P1. …` 文本块
  - `dsl.Considered(item: str, used: bool, note: str)`
  - `dsl.Declarations.considered: list[Considered]`
  - `dsl.validate(out, schema_info, db_path, *, question: str, profile_ids: set[str]) -> list[str]`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_dsl.py`：

```python
from model.pipeline.dsl import Considered, render_profile


def test_render_profile_numbers_items():
    assert render_profile(["甲", "乙"]) == "P1. 甲\nP2. 乙"


def test_render_profile_empty():
    assert render_profile([]) == "(本库没有需要特别注意的事实)"


def _decl_with_considered(considered):
    return {
        "time_context": {"displaced": False, "reference": ""},
        "outputs": [{"name": "n", "source": "column", "column": "singer.Name",
                     "expr": "", "anchors": {}}],
        "assumptions": [],
        "considered": considered,
    }


def test_c5a_missing_disposition_is_reported(toy_db):
    out = DslOutput.model_validate(
        {"sql": "SELECT Name FROM singer", "declarations": _decl_with_considered([])})
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="q", profile_ids={"P1"})
    assert any("P1" in i and "表态" in i for i in issues)


def test_c5a_unused_requires_note(toy_db):
    out = DslOutput.model_validate({
        "sql": "SELECT Name FROM singer",
        "declarations": _decl_with_considered(
            [{"item": "P1", "used": False, "note": ""}])})
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="q", profile_ids={"P1"})
    assert any("P1" in i and "理由" in i for i in issues)


def test_c5a_passes_when_all_disposed(toy_db):
    out = DslOutput.model_validate({
        "sql": "SELECT Name FROM singer",
        "declarations": _decl_with_considered(
            [{"item": "P1", "used": False, "note": "本题不涉及年龄换算"}])})
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="q", profile_ids={"P1"})
    assert not [i for i in issues if "P1" in i]
```

> fixture 名是 `toy_db`（`tests/test_dsl.py:243`），建的表是
> `singer(Name TEXT, Age INT, Song_Name TEXT)`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dsl.py -q`
Expected: FAIL —— `ImportError: cannot import name 'Considered'`

- [ ] **Step 3: 改 `dsl.py`**

在 `Assumption` 类之后、`Declarations` 之前插入：

```python
class Considered(BaseModel):
    """对库画像每一条事实的表态：用了没用；没用必须给理由。

    这是 M3 的触发机制：把"没想到"变成"想过并否决了"——后者可校验、可统计。
    """

    item: str                                   # 画像条目编号，如 "P1"
    used: bool
    note: BlankableText = ""                    # used=false 时必填理由
```

`Declarations` 加一个字段（其余不变）：

```python
class Declarations(BaseModel):
    time_context: TimeContext
    outputs: list[OutputDecl] = Field(min_length=1)
    assumptions: list[Assumption] = Field(default_factory=list)
    considered: list[Considered] = Field(default_factory=list)
```

在 `# --------- C4 锚完整` 段之后加：

```python
# ---------------------------------------------------------------- 画像渲染

def render_profile(items: list[str]) -> str:
    """把画像条目编号成 prompt 文本块；编号是 considered 的引用键。"""
    if not items:
        return "(本库没有需要特别注意的事实)"
    return "\n".join(f"P{i}. {x}" for i, x in enumerate(items, 1))


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
```

改 `validate` 总入口：

```python
def validate(out: DslOutput, schema_info: SchemaInfo, db_path: Path, *,
             question: str, profile_ids: set[str]) -> list[str]:
    """全部检查汇总；返回 issue 列表（空 = 通过），文字直接作修复反馈。"""
    try:
        tree = sqlglot.parse_one(out.sql, dialect="sqlite")
    except Exception as e:
        return [f"SQL 无法按 SQLite 语法解析: {e}"]
    decl = out.declarations
    return (_c1_alignment(decl, tree) + _c2_consistency(decl, tree)
            + _c3_grounding(decl, tree, schema_info, db_path)
            + _c4_anchors(decl) + _c5a_considered(decl, profile_ids))
```

`question` 本任务未用（Task 3 用），先收下——签名一次改到位，避免二次改动扩散到测试。

- [ ] **Step 4: 改模板登记与提示词**

`model/pipeline/templates.py`，把 `"dslgen.user"` 那一行改成：

```python
    "dslgen.user": {"schema", "question", "plan", "profile"},
```

`model/pipeline/prompts/dslgen.user.md` 全文改为：

```markdown
Database schema with sample rows:

{schema}

Facts derived from the actual database contents (each MUST be addressed in `considered`):

{profile}

Question: {question}

Plan:
{plan}

JSON:
```

`model/pipeline/prompts/dslgen.system.md`：在描述 `assumptions` 槽位的段落之后，
追加一段（与文件既有风格一致，用英文）：

```markdown
- `considered`: one entry per profile fact `P1`, `P2`, … listed in the user
  message. Set `used: true` when the fact shaped your SQL and say how in `note`;
  set `used: false` and give the reason in `note` when it does not apply.
  Every listed fact needs an entry — silence is not an option. Deciding a fact
  is irrelevant is a valid answer; not looking at it is not.
```

同时在 system 提示词的 JSON 示例里加上该键：

```json
"considered": [{"item": "P1", "used": false, "note": "question asks about the present, no time conversion needed"}]
```

- [ ] **Step 5: 改 `declare.py`**

```python
from model.pipeline.dsl import (load_schema_info, parse_output, render_profile,
                                validate)
from model.pipeline.profile import build_profile
```

`DeclareStage.__init__` 与 `run` 改为：

```python
class DeclareStage:
    def __init__(self, endpoint: ChatEndpoint, max_repairs: int = 2, *,
                 use_profile: bool = True, force_considered: bool = True) -> None:
        self.endpoint = endpoint
        self.max_repairs = max_repairs
        self.use_profile = use_profile
        self.force_considered = force_considered

    def run(self, ctx: PipelineContext) -> None:
        schema_info = load_schema_info(ctx.db_path)
        items = build_profile(ctx.db_path) if self.use_profile else []
        profile_ids = {f"P{i}" for i in range(1, len(items) + 1)} \
            if self.force_considered else set()
        system = load_template("dslgen.system")
        for plan in ctx.plans:
            user = render("dslgen.user", schema=ctx.schema,
                          question=ctx.question, plan=plan,
                          profile=render_profile(items))
            ...
                    issues = validate(out, schema_info, ctx.db_path,
                                      question=ctx.question,
                                      profile_ids=profile_ids)
```

其余循环体保持原样。

- [ ] **Step 6: 修既有 `validate` 调用点**

`tests/test_dsl.py:351` 与 `:357` 两处，补上关键字参数：

```python
    assert validate(out, load_schema_info(toy_db), toy_db,
                    question="", profile_ids=set()) == []
```

```python
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="", profile_ids=set())
```

- [ ] **Step 7: 全量测试**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS，全绿（原 93 项 + 新增）

- [ ] **Step 8: 提交**

```bash
git add model/pipeline/dsl.py model/pipeline/templates.py \
        model/pipeline/prompts/dslgen.system.md \
        model/pipeline/prompts/dslgen.user.md \
        model/pipeline/stages/declare.py tests/test_dsl.py
git commit -m "feat(m3): 库画像进 prompt + considered 强制表态 + C5a 校验

触发机制：把"没想到"变成"想过并否决了"。后者可校验、可统计。
validate 签名一次改到位（question 本轮未用，留给 C6），避免二次扩散。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: C6 比率线索

**Files:**
- Modify: `model/pipeline/dsl.py`
- Test: `tests/test_dsl.py`

**Interfaces:**
- Consumes: `profile.numeric_columns(db_path) -> dict[str, list[str]]`；
  `validate(..., question=...)`
- Produces: `dsl._c6_ratio_hint(tree, question, db_path) -> list[str]`

**依据**：dev #24/#25 用 `stadium.Average` 单列当 attendance rate（错），
#26/#27 题面提了 capacity 就正确写出 `Average / Capacity`（比率算对了）。
同一模型同一库，差别只在 `Capacity` 有没有进入视野——所以只要"摆到眼前"。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_dsl.py`：

```python
import sqlglot

from model.pipeline.dsl import _c6_ratio_hint

# toy_db 只有 singer 一张表，测不出"同表兄弟数值列"；C6 打真库（只读）
CONCERT = (Path(__file__).resolve().parents[1] / "database" /
           "concert_singer" / "concert_singer.sqlite")


def _tree(sql):
    return sqlglot.parse_one(sql, dialect="sqlite")


def test_c6_hints_unused_sibling_numeric_column():
    """题面问 rate、SQL 只用了 Average -> 提示同表还有 Capacity。"""
    issues = _c6_ratio_hint(
        _tree("SELECT Name, Average FROM stadium ORDER BY Average DESC"),
        "Which stadium has the highest average attendance rate?", CONCERT)
    assert any("Capacity" in i for i in issues), issues


def test_c6_silent_when_any_division_present():
    """SQL 里已经做了除法 -> 模型已经在算比率，闭嘴。"""
    assert not _c6_ratio_hint(
        _tree("SELECT Name, Average / Capacity AS r FROM stadium"),
        "Which stadium has the highest average attendance rate?", CONCERT)


def test_c6_silent_without_ratio_word():
    """题面没有比率词 -> 不打扰（避免把普通取值题逼成比率题）。"""
    assert not _c6_ratio_hint(
        _tree("SELECT Name, Average FROM stadium"),
        "List the name and average attendance of each stadium.", CONCERT)
```

> `tests/test_dsl.py` 顶部若还没有 `from pathlib import Path`，补上。
>
> **触发条件为什么是"SQL 里没有任何除法"而不是"有未用到的兄弟列"**：
> 后者会在 dev #26/#27 上误报——那两题**正确**写出了 `Average / Capacity`，
> 但 `Highest`/`Lowest` 仍未被用到，会白烧一轮修复去改一个已经对的答案。
> "有没有做除法"是"模型有没有在算比率"的准确代理。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dsl.py -k c6 -q`
Expected: FAIL —— `ImportError: cannot import name '_c6_ratio_hint'`

- [ ] **Step 3: 实现**

`dsl.py` 顶部 import 加：

```python
from model.pipeline.profile import numeric_columns
```

在 C5a 之后加：

```python
# ---------------------------------------------------------------- C6 比率线索

# 只在题面明确要"比率"时才触发；"average" 不算——它常指聚合而非比率，
# 且 Archer 里恰好有名为 Average 的存量列，宽进只会把普通取值题逼成比率题。
_RATIO_WORDS = re.compile(
    r"\brate\b|\bratio\b|\bdensity\b|proportion|percentage|per capita|\bper\b",
    re.I)


def _c6_ratio_hint(tree: exp.Expression, question: str,
                   db_path: Path) -> list[str]:
    """题面要比率、SQL 却一个除法都没有 => 把用到的表的数值列摆出来。

    触发条件用"有没有除法"而不是"有没有未用到的兄弟列"：后者会在
    dev #26/#27 上误报（那两题正确写出了 Average/Capacity，但同表的
    Highest/Lowest 仍未用到），白烧一轮修复去改一个已经对的答案。

    只提示不判错——分母是哪一列由模型决定，程序无从判定。
    """
    if not _RATIO_WORDS.search(question):
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
```

`validate` 汇总加上（`question` 此处开始生效）：

```python
            + _c4_anchors(decl) + _c5a_considered(decl, profile_ids)
            + _c6_ratio_hint(tree, question, db_path))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dsl.py -q`
Expected: PASS

- [ ] **Step 5: 噪声抽查（不可跳过）**

C6 是"建议级"检查，误报会白烧修复轮。抽查它在 dev 全集上的触发率：

```bash
.venv/Scripts/python.exe -c "
import json, sqlglot
from pathlib import Path
from model.pipeline.dsl import _c6_ratio_hint
d = json.load(open('data/en_data/dev.json', encoding='utf-8'))
r = json.load(open('predictions/m2-dslsql/dslsql-pro-thinking_en_dev.json', encoding='utf-8'))
res = json.load(open('results/m2-dslsql/en_dev_dslsql-pro-thinking.json', encoding='utf-8'))['samples']
wrong = {s['index'] for s in res if not s['match']}
fired = []
for i, x in enumerate(d):
    try: t = sqlglot.parse_one(r[i], dialect='sqlite')
    except Exception: continue
    db = Path('database')/x['db_id']/f\"{x['db_id']}.sqlite\"
    if _c6_ratio_hint(t, x['question'], db): fired.append(i)
print('C6 在 dev 104 题触发', len(fired), '题:', fired)
print('  其中原本判错的', len([i for i in fired if i in wrong]),
      '/ 原本判对的', len([i for i in fired if i not in wrong]))
print('  是否命中目标题 #24 #25 #33 #40 #41:',
      [i for i in (24,25,33,40,41) if i in fired])
"
```
Expected：`predictions/*.json` 是 `list[str]`（下标即题号）。判据三条：
1. 触发总数 **5–25**
2. **#24/#25 必须在触发列表里**——它们是 C6 的设计靶子，不命中说明规则失效
3. "原本判对的"触发数 **≤ 3**——每一个都是白烧一轮修复的成本

**任一条不满足就停下来调 `_RATIO_WORDS` 或触发条件，不要带着噪声往下走。**

- [ ] **Step 6: 提交**

```bash
git add model/pipeline/dsl.py tests/test_dsl.py
git commit -m "feat(m3): C6 比率线索——题面要比率但 SQL 只用了单列时摆出同表兄弟列

依据 dev #24/#25 vs #26/#27 天然对照：同模型同库，题面提了 capacity 就
算对比率，没提就直接用 Average 列。缺的是候选进入视野，不是公式。
只提示不判错——分母是哪列程序无从判定。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: anchors 枚举化 + C5b 锚一致性

**Files:**
- Modify: `model/pipeline/dsl.py`
- Modify: `model/pipeline/prompts/dslgen.system.md`
- Test: `tests/test_dsl.py`

**Interfaces:**
- Produces: `dsl.Anchor(kind, ref)`；`OutputDecl.anchors: dict[str, Anchor]`；
  `dsl._c5b_anchor_sql(decl, tree) -> list[str]`

**依据**：train #158 —— plan 原文写了 `dob` 是 `DD/MM/YYYY`、anchor 也写了，
SQL 照样写 `strftime('%Y', dob)`（对该格式返回 NULL）。dev #3 同构。
**知识已经在上下文里，断的是执行**——这一类只有一致性校验能抓。

- [ ] **Step 1: 写失败测试**

```python
from model.pipeline.dsl import Anchor


def _decl_anchor(kind, expr, ref=""):
    return {
        "time_context": {"displaced": True, "reference": "2001"},
        "outputs": [{"name": "a", "source": "derived", "column": "",
                     "expr": expr, "anchors": {"Age": {"kind": kind, "ref": ref}}}],
        "assumptions": [], "considered": [],
    }


def test_anchor_now_requires_now_in_sql(toy_db):
    """声明锚在当前，SQL 里却没有 'now' -> 自相矛盾。"""
    out = DslOutput.model_validate({
        "sql": "SELECT Age + 5 AS a FROM singer",
        "declarations": _decl_anchor("now", "Age + 5")})
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="q", profile_ids=set())
    assert any("now" in i and "Age" in i for i in issues), issues


def test_anchor_now_satisfied_by_strftime(toy_db):
    out = DslOutput.model_validate({
        "sql": "SELECT Age + 2001 - strftime('%Y','now') AS a FROM singer",
        "declarations": _decl_anchor(
            "now", "Age + 2001 - strftime('%Y','now')")})
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="q", profile_ids=set())
    assert not [i for i in issues if "now" in i]


def test_anchor_ref_says_current_but_kind_is_not_now(toy_db):
    """dev #3 的真实形态：ref 写"current age…"却挑了别的 kind。

    没有这一条，模型只要把锚写成 kind="literal" 就能绕过 C5b，
    等于什么都没查——枚举的意义就没了。
    """
    out = DslOutput.model_validate({
        "sql": "SELECT Age - (Song_Name - 2001) AS a FROM singer",
        "declarations": _decl_anchor(
            "literal", "Age - (Song_Name - 2001)",
            ref="current age of the singer as stored in the database")})
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="q", profile_ids=set())
    assert any("kind" in i and "Age" in i for i in issues), issues


def test_anchor_accepts_plain_string_for_backward_compat():
    """anchors 写成裸字符串时按 kind=literal 收下，不整轮作废。"""
    d = OutputDecl.model_validate(
        {"name": "a", "source": "derived", "column": "", "expr": "Age",
         "anchors": {"Age": "age at song release"}})
    assert d.anchors["Age"].kind == "literal"
    assert d.anchors["Age"].ref == "age at song release"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dsl.py -k anchor -q`
Expected: FAIL —— `ImportError: cannot import name 'Anchor'`

- [ ] **Step 3: 实现**

`dsl.py`，在 `OutputDecl` 之前插入：

```python
class Anchor(BaseModel):
    """存量列的参照系。枚举化的意义是可证伪——自由文本写什么都合法。

    只枚举**程序能验的**三种；单位（"weight 存的是磅"）刻意不进 kind，
    因为 SQL 里没有任何东西能证伪它，声明了也只是换个地方写自由文本。
    """

    kind: Literal["now", "column", "literal"]
    ref: BlankableText = ""


def _coerce_anchor(v):
    """裸字符串按 literal 收下：宁可降级也不要整轮作废（见 BlankableText 注释）。"""
    if isinstance(v, str):
        return {"kind": "literal", "ref": v}
    return v


AnchorMap = Annotated[
    dict[str, Anchor],
    BeforeValidator(lambda v: {} if v is None
                    else {k: _coerce_anchor(x) for k, x in v.items()}),
]
```

`OutputDecl.anchors` 的类型换成 `AnchorMap`：

```python
    anchors: AnchorMap = Field(default_factory=dict)
```

`_c4_anchors` 里 `anchors = {k.split(".")[-1].lower() for k in output.anchors}`
一行不用改（仍然只遍历键）。

新增检查：

```python
# ---------------------------------------------------------------- C5b 锚一致

_NOW_IN_SQL = re.compile(r"""["']now["']""", re.I)
# ref 的措辞说的是"当前"，kind 却不是 now —— 枚举被绕过的典型形态（dev #3）
_CURRENT_WORDS = re.compile(r"current|\bnow\b|today|present", re.I)


def _c5b_anchor_sql(decl: Declarations, tree: exp.Expression) -> list[str]:
    """锚的声明与 SQL/自身措辞必须自洽。

    train #158 证明模型会"写对声明、写错 SQL"：plan 和 anchor 都写了
    dob 是 DD/MM/YYYY，SQL 照样 strftime('%Y', dob)。纯知识注入对这一类
    零收益——事实已经在上下文里，断的是执行。
    """
    issues: list[str] = []
    pairs = [(k, a) for o in decl.outputs for k, a in o.anchors.items()]
    named_now = sorted({k for k, a in pairs if a.kind == "now"})
    if named_now and not _NOW_IN_SQL.search(tree.sql(dialect="sqlite")):
        issues.append(
            f"anchors 里 {named_now} 声明锚在当前时点（kind=\"now\"），但 SQL 里"
            f"没有出现 'now'——要么用 strftime('%Y','now') 真的锚到当前，"
            f"要么把 kind 改成实际用的参照系")
    for k, a in pairs:
        if a.kind != "now" and _CURRENT_WORDS.search(a.ref):
            issues.append(
                f"anchors 里 {k!r} 的 ref 描述的是当前时点（{a.ref!r}），"
                f"kind 却是 {a.kind!r}——若它确实是"库里存的当下值"请改成 "
                f"kind=\"now\"，并确认算式是从当前时点换算过去的")
    return issues
```

`validate` 汇总加 `+ _c5b_anchor_sql(decl, tree)`。

- [ ] **Step 4: 改 system 提示词**

`dslgen.system.md` 里描述 `anchors` 的位置改为：

```markdown
- `anchors`: for every column used in a `derived` expression, state its frame of
  reference as `{"kind": "now"|"column"|"literal", "ref": "..."}`.
  - `now` — the stored value is as-of the current date. **If you declare `now`,
    your SQL must actually reference `'now'`.**
  - `column` — the frame is another column; put its name in `ref`.
  - `literal` — a fixed point in time or a plain note; put it in `ref`.
```

JSON 示例同步改成新结构。

- [ ] **Step 5: 全量测试**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS 全绿

- [ ] **Step 6: 提交**

```bash
git add model/pipeline/dsl.py model/pipeline/prompts/dslgen.system.md tests/test_dsl.py
git commit -m "feat(m3): anchors 枚举化 + C5b 锚一致性校验

train #158 证据：模型把 dob 是 DD/MM/YYYY 写进了 plan 和 anchor，SQL 照样
写 strftime('%Y',dob)。知识已在上下文里，断的是执行——只有一致性校验能抓。
单位锚刻意不进 kind：SQL 里没有东西能证伪它。
裸字符串 anchors 降级成 literal 收下，不整轮作废。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: M3 三档消融注册

**Files:**
- Modify: `model/pipeline/plansql.py`
- Modify: `model/__init__.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `DeclareStage(endpoint, max_repairs, use_profile=, force_considered=)`
- Produces: 模型名 `m3a-pro-thinking` / `m3b-pro-thinking` / `m3c-pro-thinking`

**消融轴**：a = 给知识，b = 强制用知识，c = 加校验。**a→b 的分差是核心论据。**

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_pipeline.py`：

```python
from model import MODELS


def test_m3_variants_registered():
    for name in ("m3a-pro-thinking", "m3b-pro-thinking", "m3c-pro-thinking"):
        assert name in MODELS, sorted(MODELS)


def test_m3_ablation_flags_differ():
    from model.pipeline.plansql import M3A, M3B, M3C
    assert (M3A.use_profile, M3A.force_considered, M3A.extra_checks) == (True, False, False)
    assert (M3B.use_profile, M3B.force_considered, M3B.extra_checks) == (True, True, False)
    assert (M3C.use_profile, M3C.force_considered, M3C.extra_checks) == (True, True, True)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -k m3 -q`
Expected: FAIL —— `ImportError: cannot import name 'M3A'`

- [ ] **Step 3: `extra_checks` 开关接进 `DeclareStage` 与 `validate`**

`dsl.validate` 加一个关键字：

```python
def validate(out: DslOutput, schema_info: SchemaInfo, db_path: Path, *,
             question: str, profile_ids: set[str],
             extra_checks: bool = True) -> list[str]:
    ...
    issues = (_c1_alignment(decl, tree) + _c2_consistency(decl, tree)
              + _c3_grounding(decl, tree, schema_info, db_path)
              + _c4_anchors(decl) + _c5a_considered(decl, profile_ids))
    if extra_checks:
        issues += _c5b_anchor_sql(decl, tree)
        issues += _c6_ratio_hint(tree, question, db_path)
    return issues
```

`DeclareStage.__init__` 加 `extra_checks: bool = True`，`run` 里透传。

- [ ] **Step 4: 加消融子类**

`model/pipeline/plansql.py`，`DSLSQL._stages` 改为读类属性：

```python
class DSLSQL(PlanSQL):
    max_repairs = 2
    use_profile = False          # M2 基线：无画像、无表态、无新校验
    force_considered = False
    extra_checks = False

    def _stages(self) -> list:
        return [
            PlanStage(self.endpoint, self.n_plans, self.plan_temperature),
            DeclareStage(self.endpoint, self.max_repairs,
                         use_profile=self.use_profile,
                         force_considered=self.force_considered,
                         extra_checks=self.extra_checks),
            VoteStage(),
        ]
```

在 `DSLSQLPro` 之后追加：

```python
class M3A(DSLSQLPro):
    """M3-a：库画像只给，不强制表态、不加新校验。"""

    name = "m3a-pro-thinking"
    use_profile = True


class M3B(M3A):
    """M3-b：+ considered 强制表态。a→b 的分差 = 给知识 vs 强制用知识。"""

    name = "m3b-pro-thinking"
    force_considered = True


class M3C(M3B):
    """M3-c：+ C5b 锚一致性 + C6 比率线索。"""

    name = "m3c-pro-thinking"
    extra_checks = True
```

> `DSLSQL` 的三个开关默认 `False`，保证 `dslsql-pro-thinking` 行为与已跑出的
> M2 结果**逐位一致**，消融基线不被污染。

- [ ] **Step 5: 注册**

`model/__init__.py:13` 的 import 改为：

```python
from model.pipeline.plansql import DSLSQLPro, M3A, M3B, M3C, PlanSQLPro
```

`MODELS` 字典里 `DSLSQLPro.name: DSLSQLPro,` 之后追加三行：

```python
    M3A.name: M3A,
    M3B.name: M3B,
    M3C.name: M3C,
```

- [ ] **Step 6: 全量测试**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS 全绿

- [ ] **Step 7: 假 LLM 端到端冒烟**

Run: `.venv\Scripts\python.exe -m pytest tests/test_end_to_end.py -q`
Expected: PASS。若端到端用例硬编码了 `dslgen.user` 的占位符集合，同步补 `profile`。

- [ ] **Step 8: 预览真实 prompt（不可跳过）**

Run: `.venv\Scripts\python.exe -m model.pipeline --preview 1 --model m3c-pro-thinking --data en_dev`
Expected：dslgen 的 user 消息里能看到 `P1. 存量时点列 singer.Age：…`。
**看不到就说明画像没接上，停下来查 `declare.py` 的透传。**

- [ ] **Step 9: 提交**

```bash
git add model/pipeline/plansql.py model/pipeline/dsl.py \
        model/pipeline/stages/declare.py model/__init__.py tests/test_pipeline.py
git commit -m "feat(m3): 注册 m3a/m3b/m3c 三档消融

DSLSQL 三个开关默认 False，保证 dslsql-pro-thinking 与已跑出的 M2 结果
逐位一致，基线不被污染。a=给知识 / b=强制用 / c=加校验。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 明确不做（YAGNI）

- **数值列对进 prompt**：soccer_1 单表 1264 组，组合爆炸；改由 C6 按需触发
- **列义注释生成器**：已实测 dev 的 9 条知识需求全部落在"画像 + 通用公式"上，
  需要列义生成器的**为 0 条**
- **通用公式库（14 条）**：已实测 133 道有 CK 的错题里约 97 道 CK 内容 pred 早就有了；
  真正补缺口的只有"Archer 规定值 ≠ 常识值"那 4–5 条（`0.45`/`25mm`/`1.609344` 全精度）
  ——性质属约定对齐，划归 M3-d，不进本计划
- **M3-d（规定值表 + 输出形态规约 + entity-linking 指引）**：单独一档、单独计分，
  另开计划；理由见 train 分析 §3.3——它是刷分不是能力，混进主线会污染消融轴
- **schema embedding 检索**：论文 §2.1 用 top-k，但 PROGRESS 已拍板不采纳
  （Archer 单库表数少，全量 schema 不损失效果）
- ~~**画像注入 planner**~~ —— **这条已作废，画像同时注入 planner 与 dslgen。**
  作废理由（2026-07-23，用户纠正）：原先援引"planner 与 M1 保持一致"来拒绝注入，
  但那条不变量只约束 M2，对 M3 不成立——M1/M2 的数已跑完冻结，改 M3 的 planner
  动不到 M1↔M2 的对比。而 **dev 62% 的错断在 plan 阶段**，只注 dslgen 等于错已经
  犯完了才递材料。
  实现：`PlanStage(use_profile=)`，关闭时 `render_profile_block([])` 返回空串，
  planner 消息与 M1 **逐字节相同**，`tests/test_pipeline.py` 有断言锁死。

## 已知局限（不是缺陷，是边界）

- **C6 只能提示"还有别的数值列"，判不了哪一列是分母**——程序无从判定，
  这一步必须交给模型。它兑现的是 dev #26/#27 证明过的那件事：把候选摆到眼前就够。
- **C5b 只覆盖 `kind="now"` 一种锚**。单位锚（"weight 存的是磅"）刻意不做：
  SQL 里没有任何东西能证伪它，加了只是换个地方写自由文本。
- **画像的多版本表规则残留 1 个误报**（formula_1 的 `races`：外键只指向 `circuits`，
  但它是事件表不是快照表）。代价是模型多写一条 `used: false`，可接受。
- **`considered` 会引入一种新的失败模式**：模型漏写 `considered` 会白烧一轮修复
  （bookkeeping 而非语义）。缓解手段是 system 提示词的 JSON 示例里带上该键
  （Task 2 Step 4）。M3-a→M3-b 的分差里含这部分成本，这是诚实的代价，不修饰。

## 验收

1. `.venv\Scripts\python.exe -m pytest -q` 全绿
2. Task 1 Step 5 的画像全文人工过目，10 库合计约 9 条、无明显误报
3. Task 3 Step 5 的 C6 触发数落在 5–25
4. Task 5 Step 8 能在真实 prompt 里看到 `P1.`
5. `dslsql-pro-thinking` 的行为与本计划实施前**逐位一致**（三开关默认 False）
