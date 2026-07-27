"""L2 学习规则：JSON 配置 + 封闭谓词表 + 求值器。**运行时零 LLM 调用。**

规则由 scripts/distill.py 离线蒸馏、程序把关后落到 data/rules/<数据集>.json；
这里只做静态匹配。模型只在离线阶段出现，在线阶段一次都不调。

谓词是封闭词表：模型只能组合，不能发明。表外的谓词名、白名单外的 AST 节点名
在加载时就被拒收——这既是安全性底线，也是"规则可被程序审计"的前提。
"""

from __future__ import annotations

import json
import operator
import re
from dataclasses import dataclass
from pathlib import Path

import config
from sqlglot import exp

# 允许在 sql_has / sql_lacks / sql_select_has 里出现的 AST 节点名。
NODE_WHITELIST: dict[str, type] = {
    "Abs": exp.Abs, "Sub": exp.Sub, "Div": exp.Div, "Mul": exp.Mul,
    "Add": exp.Add, "Star": exp.Star, "Distinct": exp.Distinct,
    "Limit": exp.Limit, "Order": exp.Order, "Group": exp.Group,
    "Having": exp.Having, "Join": exp.Join, "Subquery": exp.Subquery,
    "Count": exp.Count, "Sum": exp.Sum, "Avg": exp.Avg, "Min": exp.Min,
    "Max": exp.Max, "Cast": exp.Cast, "Case": exp.Case, "Like": exp.Like,
    "In": exp.In, "Between": exp.Between,
}

# 用到这些谓词的规则需要声明表；没有声明层的档位（如 BIRD 裸直出）跳过它们。
DECL_PREDICATES = {"decl_eq"}

_CMP = {">": operator.gt, ">=": operator.ge, "<": operator.lt,
        "<=": operator.le, "==": operator.eq, "!=": operator.ne}


@dataclass(frozen=True)
class RuleContext:
    """一条规则求值需要的全部材料；每题算一次，所有规则共用。"""

    tree: exp.Expression
    question: str
    decl: dict | None
    db_path: Path | None
    selects: tuple
    tables: frozenset[str]
    columns: frozenset[str]
    literals: frozenset[str]

    @classmethod
    def build(cls, tree, question, decl, db_path) -> "RuleContext":
        return cls(
            tree=tree,
            question=question,
            decl=decl,
            db_path=Path(db_path) if db_path else None,
            selects=tuple(getattr(tree, "selects", None) or []),
            tables=frozenset(t.name.lower() for t in tree.find_all(exp.Table) if t.name),
            columns=frozenset(c.name.lower() for c in tree.find_all(exp.Column) if c.name),
            literals=frozenset(str(l.this) for l in tree.find_all(exp.Literal)),
        )


def _has_node(node: exp.Expression, name: str) -> bool:
    return next(node.find_all(NODE_WHITELIST[name]), None) is not None


def _dig(decl: dict | None, path: str):
    """按点分路径取值；任一层缺失返回哨兵 _MISSING（与 None 值区分开）。"""
    cur = decl
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


class _Missing:
    pass


_MISSING = _Missing()


PREDICATES = {
    "question": lambda a, c: re.search(a, c.question) is not None,
    "sql_has": lambda a, c: any(_has_node(c.tree, n) for n in a),
    "sql_lacks": lambda a, c: not any(_has_node(c.tree, n) for n in a),
    "sql_select_has": lambda a, c: any(_has_node(s, a) for s in c.selects),
    "sql_has_literal": lambda a, c: bool(c.literals & set(a)),
    "sql_select_count": lambda a, c: _CMP[a[0]](len(c.selects), a[1]),
    "uses_table": lambda a, c: any(re.search(a, t) for t in c.tables),
    "uses_column": lambda a, c: any(re.search(a, x) for x in c.columns),
    "decl_eq": lambda a, c: all(_dig(c.decl, k) == v for k, v in a.items()),
}


def eval_rules(rules: list[dict], *, tree: exp.Expression, question: str,
               decl: dict | None, db_path: Path | None) -> list[str]:
    """匹配上的规则的 message 列表（空 = 都没触发）。

    没有声明表时（decl is None）跳过 needs_decl 的规则——规则库因此可以
    整体搬到裸直出档位，不必先在那边建声明层。
    """
    if not rules:
        return []
    ctx = RuleContext.build(tree, question, decl, db_path)
    hits = []
    for rule in rules:
        if decl is None and rule.get("needs_decl"):
            continue
        if all(PREDICATES[key](arg, ctx) for key, arg in rule["when"].items()):
            hits.append(rule["message"])
    return hits


class RuleError(ValueError):
    """规则库不合法。加载期抛出，绝不让非法规则跑到线上。"""


def _check_regex(pattern: str, where: str) -> None:
    if not isinstance(pattern, str):
        raise RuleError(f"{where} 需要正则字符串，收到 {type(pattern).__name__}")
    try:
        re.compile(pattern)
    except re.error as e:
        raise RuleError(f"{where} 的正则编译失败: {e}") from e


def _check_nodes(names, where: str) -> None:
    if isinstance(names, str):
        names = [names]
    for name in names:
        if name not in NODE_WHITELIST:
            raise RuleError(
                f"{where} 的 AST 节点名 {name!r} 不在白名单——"
                f"可用的是 {sorted(NODE_WHITELIST)}")


def check_rule(rule: dict) -> None:
    """不合法就抛 RuleError。校验的是"能不能求值"，不是"值不值得留"。"""
    rid = rule.get("id", "<无 id>")
    if not rule.get("message"):
        raise RuleError(f"规则 {rid} 缺 message——触发了要发什么话给模型？")
    when = rule.get("when")
    if not isinstance(when, dict) or not when:
        raise RuleError(f"规则 {rid} 的 when 不能为空（空 when 对每题都触发）")
    for key, arg in when.items():
        if key not in PREDICATES:
            raise RuleError(
                f"规则 {rid} 用了未知谓词 {key!r}——可用的是 {sorted(PREDICATES)}")
        where = f"规则 {rid} 的 {key}"
        if key in ("question", "uses_table", "uses_column"):
            _check_regex(arg, where)
        elif key in ("sql_has", "sql_lacks", "sql_select_has"):
            _check_nodes(arg, where)
        elif key == "sql_has_literal":
            if not isinstance(arg, list) or not all(isinstance(x, str) for x in arg):
                raise RuleError(f"{where} 需要字符串列表")
        elif key == "sql_select_count":
            if not (isinstance(arg, list) and len(arg) == 2):
                raise RuleError(f"{where} 需要 [比较符, 数字] 两元列表")
            if arg[0] not in _CMP:
                raise RuleError(f"{where} 的比较符 {arg[0]!r} 非法——可用 {sorted(_CMP)}")
            if not isinstance(arg[1], int):
                raise RuleError(f"{where} 的第二项需要整数")
        elif key == "decl_eq":
            if not isinstance(arg, dict) or not arg:
                raise RuleError(f"{where} 需要非空的 {{路径: 值}} 字典")


def rules_path_for(dataset: str) -> Path:
    """en_dev/en_train -> data/rules/en.json；bird_dev -> data/rules/bird.json。"""
    prefix = dataset.split("_")[0]
    return config.ROOT / "data" / "rules" / f"{prefix}.json"


def load_rules(path: str | Path) -> list[dict]:
    """读规则库，逐条校验，写入 needs_decl。文件不存在 = 没有规则，返回 []。"""
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules", [])
    for rule in rules:
        check_rule(rule)
        rule["needs_decl"] = bool(set(rule["when"]) & DECL_PREDICATES)
    return rules
