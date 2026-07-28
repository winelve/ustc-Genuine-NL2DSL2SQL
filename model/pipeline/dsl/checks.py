"""L1 通用检查：跨数据集、程序静态判定，不依赖任何数据集专属知识。

所有检查产出 issue 字符串列表（空 = 通过），文字直接作为修复反馈发回模型，
所以报错内容写给模型看：说清哪里不一致、期望是什么。
"""

from __future__ import annotations

import difflib
import sqlite3
from pathlib import Path

import sqlglot
from sqlglot import exp

from model.pipeline.dsl.schema import (Declarations, DslOutput, SchemaInfo,
                                       _eq_column_literal_pairs, _expr_columns,
                                       _is_star)


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

def _normalize_identifier(identifier: str) -> str:
    """按 SQLite 规则去掉一层标识符引号，并统一成 schema 的小写口径。"""
    identifier = identifier.strip()
    pairs = {'"': '"', "`": "`", "[": "]"}
    if len(identifier) >= 2 and pairs.get(identifier[0]) == identifier[-1]:
        identifier = identifier[1:-1]
    return identifier.lower()


def _c3_relation_columns(tree: exp.Expression,
                         schema_info: SchemaInfo) -> SchemaInfo:
    """返回 SQL 中可按关系名/别名访问的列，包含物理表、CTE 与子查询。"""
    relations = {table: set(columns) for table, columns in schema_info.items()}
    derived_queries: list[tuple[str, exp.Query]] = []

    for cte in tree.find_all(exp.CTE):
        if isinstance(cte.this, exp.Query):
            name = _normalize_identifier(cte.alias_or_name)
            output_names = cte.alias_column_names or cte.this.named_selects
            relations[name] = {
                _normalize_identifier(output_name)
                for output_name in output_names
                if output_name != "*"
            }
            derived_queries.append((name, cte.this))

    for index, subquery in enumerate(tree.find_all(exp.Subquery)):
        if isinstance(subquery.this, exp.Query):
            name = (
                _normalize_identifier(subquery.alias)
                if subquery.alias
                else f"__anonymous_subquery_{index}"
            )
            relations[name] = {
                _normalize_identifier(output_name)
                for output_name in subquery.this.named_selects
                if output_name != "*"
            }
            derived_queries.append((name, subquery.this))

    def bind_relation_aliases() -> bool:
        changed = False
        # CTE 本身在 AST 里也是 Table；等 CTE 输出收集完再绑定 `rates AS r`。
        for table in tree.find_all(exp.Table):
            source = _normalize_identifier(table.name)
            alias = _normalize_identifier(table.alias)
            if not alias or source not in relations:
                continue
            before = relations.get(alias, set())
            after = before | relations[source]
            if after != before:
                relations[alias] = after
                changed = True
        return changed

    def query_sources(query: exp.Query) -> list[exp.Expression]:
        sources: list[exp.Expression] = []
        from_ = query.args.get("from_")
        if from_ is not None:
            if from_.this is not None:
                sources.append(from_.this)
            sources.extend(from_.expressions)
        sources.extend(join.this for join in query.args.get("joins") or [])
        return sources

    def source_columns(source: exp.Expression) -> set[str]:
        if isinstance(source, exp.Table):
            key = _normalize_identifier(source.alias_or_name)
            return relations.get(key, relations.get(
                _normalize_identifier(source.name), set()
            ))
        if isinstance(source, exp.Subquery) and source.alias:
            return relations.get(_normalize_identifier(source.alias), set())
        return set()

    # `SELECT *` 会把上游关系列继续输出；多层 CTE 需要迭代到不再增长。
    for _ in range(len(derived_queries) + 2):
        changed = bind_relation_aliases()
        for name, query in derived_queries:
            expanded = set(relations[name])
            sources = query_sources(query)
            for select in query.selects:
                if not _is_star(select):
                    continue
                inner = select.unalias()
                qualifier = (
                    _normalize_identifier(inner.table)
                    if isinstance(inner, exp.Column) and inner.table
                    else ""
                )
                if qualifier:
                    expanded.update(relations.get(qualifier, set()))
                else:
                    for source in sources:
                        expanded.update(source_columns(source))
            if expanded != relations[name]:
                relations[name] = expanded
                changed = True
        if not changed:
            break
    bind_relation_aliases()

    return relations


def _c3_grounding(decl: Declarations, tree: exp.Expression,
                  schema_info: SchemaInfo, db_path: Path) -> list[str]:
    """声明引用的表/列必须真实存在；等值比较的字面值给近邻提示。"""
    issues: list[str] = []
    relation_columns = _c3_relation_columns(tree, schema_info)
    visible_columns = {c for cols in relation_columns.values() for c in cols}

    def check_column(ref: str, owner: str, *,
                     relations: SchemaInfo = relation_columns) -> None:
        table, _, column = ref.rpartition(".")
        if table:
            table_key = _normalize_identifier(table)
            column_key = _normalize_identifier(column)
            if table_key not in relations:
                issues.append(f"{owner} 引用的表 {table!r} 不在 schema 里")
            elif column_key not in relations[table_key]:
                issues.append(f"{owner} 引用的列 {ref!r} 不在 schema 里")
        elif _normalize_identifier(column) not in {
                c for cols in relations.values() for c in cols}:
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
            for c in sorted(columns - visible_columns):
                issues.append(f"输出列 {output.name!r} 的 expr 引用的列 {c!r} "
                              "不在 schema 的任何表里")
    for a in decl.assumptions:
        check_column(a.target, f"假设 target {a.target!r}",
                     relations=schema_info)
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


# ---------------------------------------------------------------- 总入口

def validate(out: DslOutput, schema_info: SchemaInfo, db_path: Path, *,
             question: str) -> list[str]:
    """L1 通用检查汇总；返回 issue 列表（空 = 通过），文字直接作修复反馈。

    C1-C4 恒开、跨数据集。数据集专属的判断走 L2 学习规则（dsl/rules.py），
    SQLens 静态信号走 sqlens_issues()（默认关，见 checks.py 下半部分）。
    """
    try:
        tree = sqlglot.parse_one(out.sql, dialect="sqlite")
    except Exception as e:
        return [f"SQL 无法按 SQLite 语法解析: {e}"]
    decl = out.declarations
    return (_c1_alignment(decl, tree) + _c2_consistency(decl, tree)
            + _c3_grounding(decl, tree, schema_info, db_path)
            + _c4_anchors(decl))


# ---------------------------------------------------------------- SQLens 静态信号
#
# 来源：SQLens（arXiv 2506.04494）的 database-based signals。全部默认关，
# 先用 scripts/measure_checks.py 在 en_train 上离线测精度，过闸门才进档位。
# 只取 database-based 那一族——论文的 5 个 LLM 信号与 weak-supervision 分类器
# 不取（本项目是硬规则 → 修复环，不是打分器）。

_TEXTISH = ("CHAR", "TEXT", "CLOB", "VARCHAR")
_S1_MAX_COLUMNS = 300      # 单题最多探测多少列，防大库上把修复轮拖死


def _is_textish(decl_type: str) -> bool:
    return any(k in (decl_type or "").upper() for k in _TEXTISH)


def _s1_value_ambiguity(tree: exp.Expression, schema_info: SchemaInfo,
                        db_path: Path) -> list[str]:
    """S1 值歧义：`列 = '值'` 的值不在该列里，却在别的列里 => 可能配错了列。

    与 C3 近邻检查互补：C3 管"值打错了"（库里谁都没有，给近似值），
    S1 管"值没打错但配错了列"（库里有，在别处）。两边都不触发时才安静。
    只在列名能唯一定位一张表时才判（不猜表），与 C3 同一条纪律——这里的
    "唯一"是在本条 SQL 实际 FROM/JOIN 到的表范围内判定，而不是整个 schema：
    同名列分布在多张表很常见（如 country.Name 与 city.Name），不把查询没
    涉及的表也算进候选，否则会把本该能判的列误判成"不唯一"而放过。
    """
    pairs = [(c, l) for c, l in _eq_column_literal_pairs(tree) if l.is_string]
    if not pairs:
        return []
    queried_tables = {t.name.lower() for t in tree.find_all(exp.Table)}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    issues = []
    try:
        for col, lit in pairs:
            literal = str(lit.this)
            owners = [t for t, cols in schema_info.items()
                      if t in queried_tables and col.name.lower() in cols]
            if len(owners) != 1:
                continue
            if conn.execute(f'SELECT 1 FROM "{owners[0]}" WHERE "{col.name}" = ? '
                            f'LIMIT 1', (literal,)).fetchone():
                continue                      # 值就在用的这一列里，没问题
            elsewhere = _columns_holding(conn, literal,
                                         skip=(owners[0], col.name.lower()))
            if elsewhere:
                issues.append(
                    f"字面值 {literal!r} 不在 {owners[0]}.{col.name} 里，"
                    f"但出现在 {elsewhere}——是不是配错了列？")
    finally:
        conn.close()
    return issues


def _columns_holding(conn: sqlite3.Connection, literal: str,
                     skip: tuple[str, str]) -> list[str]:
    """全库扫文本列，找哪些列真的存着这个值；最多报 3 个。"""
    found, probed = [], 0
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        for row in conn.execute(f'PRAGMA table_info("{table}")'):
            column, decl_type = row[1], row[2]
            if (table.lower(), column.lower()) == (skip[0], skip[1]):
                continue
            if not _is_textish(decl_type):
                continue
            probed += 1
            if probed > _S1_MAX_COLUMNS:
                return found
            try:
                hit = conn.execute(
                    f'SELECT 1 FROM "{table}" WHERE "{column}" = ? LIMIT 1',
                    (literal,)).fetchone()
            except sqlite3.Error:
                continue
            if hit:
                found.append(f"{table}.{column}")
                if len(found) >= 3:
                    return found
    return found


_AGGREGATES = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)


def _s2_groupby_without_aggregate(tree: exp.Expression) -> list[str]:
    """S2：有 GROUP BY 却没有任何聚合函数——多半该用 DISTINCT，或漏了聚合。"""
    if next(tree.find_all(exp.Group), None) is None:
        return []
    if any(next(tree.find_all(a), None) is not None for a in _AGGREGATES):
        return []
    return ["SQL 有 GROUP BY 但没有任何聚合函数（COUNT/SUM/AVG/MIN/MAX）——"
            "若只是想去重请用 DISTINCT；若确需分组统计，补上聚合"]


def foreign_key_pairs(db_path: Path) -> set[frozenset[str]]:
    """库里全部外键的列名对（小写、无表限定）。

    刻意忽略表限定：SQL 里的表前缀常是别名（`c.CountryCode`），解析别名要跟
    FROM/JOIN 全表建映射，工程量与收益不成比例。代价是极少数同名列会被放过。
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        pairs = set()
        for (table,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"):
            for row in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
                src, dst = row[3], row[4]
                if src and dst:
                    pairs.add(frozenset({src.lower(), dst.lower()}))
        return pairs
    finally:
        conn.close()


def _s3_join_predicate(tree: exp.Expression, db_path: Path) -> list[str]:
    """S3：JOIN 的 ON 条件不落在库里任何一对主外键关系上。"""
    joins = list(tree.find_all(exp.Join))
    if not joins:
        return []
    fks = foreign_key_pairs(db_path)
    issues = []
    for join in joins:
        on = join.args.get("on")
        if on is None:
            continue
        for eq in on.find_all(exp.EQ):
            left, right = eq.this, eq.expression
            if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                continue
            pair = frozenset({left.name.lower(), right.name.lower()})
            if pair not in fks:
                issues.append(
                    f"JOIN 条件 {left.sql()} = {right.sql()} 不是库里的主外键关系——"
                    f"请核对连接键；若确实要按业务字段连接，说明理由")
    return issues


# ---------------------------------------------------------------- SQLens 执行数据库

from archer_eval.execution import execute_sql

_SQLENS_TIMEOUT_S = 10.0     # 检查器自己的预算，短于评测的 30s：宁可放过不拖慢修复轮


def _s4_subquery_equality(tree: exp.Expression, db_path: Path) -> list[str]:
    """S4：`= (子查询)` 但子查询返回多行——SQLite 静默取第一行，不报错。"""
    issues = []
    for eq in tree.find_all(exp.EQ):
        for side in (eq.this, eq.expression):
            if not isinstance(side, exp.Subquery):
                continue
            inner = side.this.sql(dialect="sqlite")
            result = execute_sql(db_path, f"SELECT COUNT(*) FROM ({inner})",
                                 timeout_s=_SQLENS_TIMEOUT_S)
            if not result.ok or not result.rows:
                continue                    # 跑不出来就不判，交给别的检查
            n = result.rows[0][0]
            if isinstance(n, int) and n > 1:
                issues.append(
                    f"子查询返回 {n} 行，却用 `=` 比较——SQLite 会静默只取第一行；"
                    f"若本意是“其中任意一个”请改用 IN，若本意是唯一值请加限定条件")
    return issues


def _s5_empty_predicate(tree: exp.Expression, schema_info: SchemaInfo,
                        db_path: Path) -> list[str]:
    """S5：单个 `列 = '值'` 条件自己就筛出 0 行 => 该条件本身写错了。

    只判列名能唯一定位一张表的情形（不猜表），与 S1 同一条纪律——这里的
    "唯一"同样收窄到本条 SQL 实际 FROM/JOIN 到的表范围内判定，而不是整个
    schema（同名列分布在多张表很常见，如 country.Name 与 city.Name）。
    **已知争议**：空结果不一定等于错（反事实题、极端条件题的正确答案就是空集）。
    本检查默认关，去留由 scripts/measure_checks.py 在 en_train 上的实测数字裁决。
    """
    pairs = [(c, l) for c, l in _eq_column_literal_pairs(tree) if l.is_string]
    if not pairs:
        return []
    queried_tables = {t.name.lower() for t in tree.find_all(exp.Table)}
    issues = []
    for col, lit in pairs:
        owners = [t for t, cols in schema_info.items()
                 if t in queried_tables and col.name.lower() in cols]
        if len(owners) != 1:
            continue
        literal = str(lit.this)
        result = execute_sql(
            db_path,
            f'SELECT COUNT(*) FROM "{owners[0]}" WHERE "{col.name}" = '
            f"'{literal.replace(chr(39), chr(39) * 2)}'",
            timeout_s=_SQLENS_TIMEOUT_S)
        if result.ok and result.rows and result.rows[0][0] == 0:
            issues.append(
                f"条件 {col.name} = {literal!r} 单独执行筛出 0 行——"
                f"这个条件本身就选不出任何数据，请核对列名与取值")
    return issues


def _s6_abnormal_result(sql: str, db_path: Path) -> list[str]:
    """S6：整条 SQL 的结果可疑——空结果 / 某列全 0 / 某列全 NULL。

    执行报错时静默（那是 VA 与 C3 的活）。**已知争议**同 S5。
    """
    result = execute_sql(db_path, sql, timeout_s=_SQLENS_TIMEOUT_S)
    if not result.ok:
        return []
    if not result.rows:
        return ["SQL 执行结果为空——若题意本就可能无匹配行请忽略，"
                "否则请核对过滤条件是否过严"]
    issues = []
    for j in range(result.n_cols):
        column = [row[j] for row in result.rows if j < len(row)]
        if not column:
            continue
        if all(v is None for v in column):
            issues.append(f"第 {j + 1} 个输出列全部是 NULL——"
                          f"多半是连接不上或聚合了空集合")
        elif all(v == 0 for v in column):
            issues.append(f"第 {j + 1} 个输出列全部是 0——请核对计算式")
    return issues


# 过闸的信号（判定见 docs/ABLATION.md「SQLens 信号离线精度」，Task 8 在 en_train 上
# 用 scripts/measure_checks.py 实测：trigger≥5 且 precision≥0.7 两条都过才留）。
# S1/S2/S4 触发数 <5（样本太少读不出信号），S3 precision 67%<0.7——三支均未过闸。
# 未过闸的实现保留但不进 sqlens_issues 的默认集合——留着是为了换数据集后重测。
ENABLED_SQLENS = ("S5", "S6")

# 全部六支的名字，供离线重测工具（scripts/measure_checks.py）显式传参绕过
# ENABLED_SQLENS——归档 ≠ 测不到：换数据集后要能重新测 S1-S4 的 trigger/precision。
ALL_SQLENS = tuple(f"S{i}" for i in range(1, 7))


def sqlens_issues(tree: exp.Expression, sql: str, question: str,
                  schema_info: SchemaInfo, db_path: Path, *,
                  enabled: tuple[str, ...] | None = None) -> dict[str, list[str]]:
    """S1-S6 的统一入口；键恒定，方便离线测量逐支归因。

    默认（`enabled=None`）只跑 `ENABLED_SQLENS` 里过闸的信号；其余键仍在
    （恒为空列表），保持返回形状不变，方便调用方与离线测量脚本不用区分
    "关闭"与"没触发"——**这是线上主流程调用的行为，不传参就不变**。

    `enabled` 参数是为离线重测开的后门：`scripts/measure_checks.py` 显式传
    `enabled=ALL_SQLENS`，绕过闸门把 S1-S4 也跑一遍，这样"归档但保留实现"
    才真的可重测，而不是被 ENABLED_SQLENS 结构性挡死。

    **容错纪律**：任何一支自己出错（库打不开、超时、sqlglot 抽风）都静默返回
    空列表，绝不因为检查器出问题而阻断主流程或吞掉一条本来能用的 SQL。
    `question` 目前未被 S1-S6 使用，留在签名里是为了与 L2 求值器同形。
    """
    active = ENABLED_SQLENS if enabled is None else enabled
    out: dict[str, list[str]] = {f"S{i}": [] for i in range(1, 7)}
    probes = {
        "S1": lambda: _s1_value_ambiguity(tree, schema_info, db_path),
        "S2": lambda: _s2_groupby_without_aggregate(tree),
        "S3": lambda: _s3_join_predicate(tree, db_path),
        "S4": lambda: _s4_subquery_equality(tree, db_path),
        "S5": lambda: _s5_empty_predicate(tree, schema_info, db_path),
        "S6": lambda: _s6_abnormal_result(sql, db_path),
    }
    for name, probe in probes.items():
        if name not in active:
            continue
        try:
            out[name] = probe()
        except Exception:
            out[name] = []
    return out
