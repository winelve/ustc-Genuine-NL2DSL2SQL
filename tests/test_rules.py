"""L2 学习规则：谓词求值、needs_decl 分级、加载校验。"""

import json

import pytest

import sqlglot


def _tree(sql):
    return sqlglot.parse_one(sql, dialect="sqlite")


def _rule(when, message="X", needs_decl=False):
    return {"id": "T1", "when": when, "message": message, "needs_decl": needs_decl}


def test_question_predicate_matches():
    from model.pipeline.dsl.rules import eval_rules
    r = _rule({"question": "(?i)difference between"})
    hits = eval_rules([r], tree=_tree("SELECT a - b FROM t"),
                      question="What is the difference between A and B?",
                      decl=None, db_path=None)
    assert hits == ["X"]


def test_question_predicate_no_match():
    from model.pipeline.dsl.rules import eval_rules
    r = _rule({"question": "(?i)difference between"})
    hits = eval_rules([r], tree=_tree("SELECT a - b FROM t"),
                      question="List all singers", decl=None, db_path=None)
    assert hits == []


def test_all_predicates_must_hold():
    """when 里多个谓词是 AND，不是 OR。"""
    from model.pipeline.dsl.rules import eval_rules
    r = _rule({"question": "difference", "sql_lacks": ["Abs"]})
    assert eval_rules([r], tree=_tree("SELECT ABS(a - b) FROM t"),
                      question="difference", decl=None, db_path=None) == []
    assert eval_rules([r], tree=_tree("SELECT a - b FROM t"),
                      question="difference", decl=None, db_path=None) == ["X"]


def test_sql_has_and_lacks_are_inverses():
    """sql_has 和 sql_lacks 必须相反：有其一就触发 vs 一个都没有才触发。"""
    from model.pipeline.dsl.rules import eval_rules
    nodes = ["Abs", "Sub"]
    tree_with = _tree("SELECT ABS(a) FROM t")
    tree_without = _tree("SELECT a + b FROM t")

    # 有节点时：sql_has 触发，sql_lacks 不触发
    assert eval_rules([_rule({"sql_has": nodes})], tree=tree_with,
                      question="q", decl=None, db_path=None) == ["X"]
    assert eval_rules([_rule({"sql_lacks": nodes})], tree=tree_with,
                      question="q", decl=None, db_path=None) == []

    # 没节点时：sql_has 不触发，sql_lacks 触发
    assert eval_rules([_rule({"sql_has": nodes})], tree=tree_without,
                      question="q", decl=None, db_path=None) == []
    assert eval_rules([_rule({"sql_lacks": nodes})], tree=tree_without,
                      question="q", decl=None, db_path=None) == ["X"]


def test_sql_select_has_only_looks_at_select_clause():
    from model.pipeline.dsl.rules import eval_rules
    r = _rule({"sql_select_has": "Sub"})
    # 减法在 WHERE 里，不在 SELECT 里 => 不触发
    assert eval_rules([r], tree=_tree("SELECT a FROM t WHERE b - c > 0"),
                      question="q", decl=None, db_path=None) == []
    assert eval_rules([r], tree=_tree("SELECT b - c FROM t"),
                      question="q", decl=None, db_path=None) == ["X"]


def test_sql_has_literal():
    from model.pipeline.dsl.rules import eval_rules
    r = _rule({"sql_has_literal": ["0.453592", "2.20462"]})
    assert eval_rules([r], tree=_tree("SELECT w * 0.453592 FROM t"),
                      question="q", decl=None, db_path=None) == ["X"]
    assert eval_rules([r], tree=_tree("SELECT w * 0.45 FROM t"),
                      question="q", decl=None, db_path=None) == []


def test_sql_select_count():
    from model.pipeline.dsl.rules import eval_rules
    r = _rule({"sql_select_count": [">", 2]})
    assert eval_rules([r], tree=_tree("SELECT a, b, c FROM t"),
                      question="q", decl=None, db_path=None) == ["X"]
    assert eval_rules([r], tree=_tree("SELECT a, b FROM t"),
                      question="q", decl=None, db_path=None) == []


def test_uses_table_and_column():
    from model.pipeline.dsl.rules import eval_rules
    tree = _tree("SELECT Name FROM singer")
    assert eval_rules([_rule({"uses_table": "(?i)singer"})], tree=tree,
                      question="q", decl=None, db_path=None) == ["X"]
    assert eval_rules([_rule({"uses_column": "(?i)^name$"})], tree=tree,
                      question="q", decl=None, db_path=None) == ["X"]
    assert eval_rules([_rule({"uses_table": "(?i)concert"})], tree=tree,
                      question="q", decl=None, db_path=None) == []


def test_decl_eq_reads_dotted_path():
    from model.pipeline.dsl.rules import eval_rules
    r = _rule({"decl_eq": {"time_context.displaced": False}}, needs_decl=True)
    decl = {"time_context": {"displaced": False, "reference": ""}}
    assert eval_rules([r], tree=_tree("SELECT a FROM t"), question="q",
                      decl=decl, db_path=None) == ["X"]
    decl2 = {"time_context": {"displaced": True, "reference": "x"}}
    assert eval_rules([r], tree=_tree("SELECT a FROM t"), question="q",
                      decl=decl2, db_path=None) == []


def test_needs_decl_rules_skipped_without_declarations():
    """裸直出档位没有声明表：needs_decl 的规则跳过，其余照跑。"""
    from model.pipeline.dsl.rules import eval_rules
    needs = _rule({"decl_eq": {"time_context.displaced": False}}, "A", needs_decl=True)
    plain = _rule({"question": "q"}, "B", needs_decl=False)
    hits = eval_rules([needs, plain], tree=_tree("SELECT a FROM t"),
                      question="q", decl=None, db_path=None)
    assert hits == ["B"]


def test_missing_decl_path_does_not_match():
    """声明表里没有这个路径时按不匹配处理，不抛异常。"""
    from model.pipeline.dsl.rules import eval_rules
    r = _rule({"decl_eq": {"nope.missing": True}}, needs_decl=True)
    assert eval_rules([r], tree=_tree("SELECT a FROM t"), question="q",
                      decl={"time_context": {"displaced": True}}, db_path=None) == []


def _write(tmp_path, rules):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"dataset": "en_train", "rules": rules},
                            ensure_ascii=False), encoding="utf-8")
    return p


def test_load_rules_marks_needs_decl(tmp_path):
    from model.pipeline.dsl.rules import load_rules
    p = _write(tmp_path, [
        {"id": "L1", "when": {"question": "x"}, "message": "m"},
        {"id": "L2", "when": {"decl_eq": {"time_context.displaced": False}}, "message": "m"},
    ])
    rules = load_rules(p)
    assert [r["needs_decl"] for r in rules] == [False, True]


def test_load_rules_rejects_unknown_predicate(tmp_path):
    from model.pipeline.dsl.rules import RuleError, load_rules
    p = _write(tmp_path, [{"id": "L1", "when": {"vibes": "good"}, "message": "m"}])
    with pytest.raises(RuleError, match="未知谓词"):
        load_rules(p)


def test_load_rules_rejects_unknown_ast_node(tmp_path):
    from model.pipeline.dsl.rules import RuleError, load_rules
    p = _write(tmp_path, [{"id": "L1", "when": {"sql_has": ["Frobnicate"]}, "message": "m"}])
    with pytest.raises(RuleError, match="不在白名单"):
        load_rules(p)


def test_load_rules_rejects_bad_regex(tmp_path):
    from model.pipeline.dsl.rules import RuleError, load_rules
    p = _write(tmp_path, [{"id": "L1", "when": {"question": "([unclosed"}, "message": "m"}])
    with pytest.raises(RuleError, match="正则"):
        load_rules(p)


def test_load_rules_rejects_empty_when(tmp_path):
    """空 when 会对每一题都触发——必须拒收。"""
    from model.pipeline.dsl.rules import RuleError, load_rules
    p = _write(tmp_path, [{"id": "L1", "when": {}, "message": "m"}])
    with pytest.raises(RuleError, match="when 不能为空"):
        load_rules(p)


def test_load_rules_rejects_missing_message(tmp_path):
    from model.pipeline.dsl.rules import RuleError, load_rules
    p = _write(tmp_path, [{"id": "L1", "when": {"question": "x"}, "message": ""}])
    with pytest.raises(RuleError, match="message"):
        load_rules(p)


def test_load_rules_rejects_bad_comparison_op(tmp_path):
    from model.pipeline.dsl.rules import RuleError, load_rules
    p = _write(tmp_path, [{"id": "L1", "when": {"sql_select_count": ["~=", 2]}, "message": "m"}])
    with pytest.raises(RuleError, match="比较符"):
        load_rules(p)


def test_load_rules_missing_file_returns_empty(tmp_path):
    """规则库不存在 = 没有 L2 规则，不是错误。"""
    from model.pipeline.dsl.rules import load_rules
    assert load_rules(tmp_path / "nope.json") == []
