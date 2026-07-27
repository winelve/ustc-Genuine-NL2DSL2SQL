"""蒸馏与测量的纯函数：闸门统计、泛化黑名单。"""

import pytest


def test_measure_counts_useful_and_harmful():
    from scripts.measure_checks import measure
    # 题 0/2 判错，题 1/3 判对
    match = {0: False, 1: True, 2: False, 3: True}
    hits = {"S1": [0, 1, 2]}
    out = measure(hits, match)
    assert out["S1"]["trigger"] == 3
    assert out["S1"]["useful"] == 2
    assert out["S1"]["harmful"] == 1
    assert out["S1"]["useful_ids"] == [0, 2]
    assert out["S1"]["harmful_ids"] == [1]
    assert abs(out["S1"]["precision"] - 2 / 3) < 1e-9


def test_measure_zero_trigger_precision_is_zero():
    """从不触发的检查 precision 记 0，不是除零也不是 1。"""
    from scripts.measure_checks import measure
    out = measure({"S9": []}, {0: False})
    assert out["S9"] == {"trigger": 0, "useful": 0, "harmful": 0,
                         "precision": 0.0, "useful_ids": [], "harmful_ids": []}


def test_measure_ignores_indices_absent_from_results():
    """预测比结果长时，多出来的题号不参与统计而不是崩掉。"""
    from scripts.measure_checks import measure
    out = measure({"S1": [0, 99]}, {0: False})
    assert out["S1"]["trigger"] == 1


def test_schema_vocabulary_picks_up_table_and_column_names():
    from model.pipeline.knowledge import schema_vocabulary
    vocab = schema_vocabulary("en_dev")
    assert "singer" in vocab          # concert_singer 的表
    assert "gnpold" in vocab          # world_1 的列
    assert len(vocab) > 50


def test_check_items_rejects_column_name_in_text():
    from model.pipeline.knowledge import KnowledgeError, check_items
    items = [{"id": "D1", "text": "Use GNPOld as the earlier value.",
              "evidence": [1, 2]}]
    with pytest.raises(KnowledgeError, match="表名/列名"):
        check_items(items, {"gnpold"}, max_items=12, min_evidence=2)


def test_check_items_accepts_generic_statement():
    from model.pipeline.knowledge import check_items
    items = [{"id": "D1",
              "text": "A difference between two quantities is absolute "
                      "unless the question fixes the direction.",
              "evidence": [1, 2]}]
    check_items(items, {"gnpold", "singer"}, max_items=12, min_evidence=2)


def test_check_items_rejects_thin_evidence():
    from model.pipeline.knowledge import KnowledgeError, check_items
    items = [{"id": "D1", "text": "Something generic.", "evidence": [1]}]
    with pytest.raises(KnowledgeError, match="证据"):
        check_items(items, set(), max_items=12, min_evidence=2)


def test_check_items_rejects_too_many():
    from model.pipeline.knowledge import KnowledgeError, check_items
    items = [{"id": f"D{i}", "text": "Generic.", "evidence": [1, 2]}
             for i in range(13)]
    with pytest.raises(KnowledgeError, match="条数"):
        check_items(items, set(), max_items=12, min_evidence=2)


def test_knowledge_block_numbers_items():
    from model.pipeline.knowledge import knowledge_block
    out = knowledge_block([{"id": "D1", "text": "A."}, {"id": "D2", "text": "B."}])
    assert out == "D1. A.\nD2. B."


def test_knowledge_block_empty_is_empty_string():
    from model.pipeline.knowledge import knowledge_block
    assert knowledge_block([]) == ""


def test_dslgen_system_byte_identical_when_knowledge_off():
    """knowledge=False 时 system 与基线逐字节相同——对照点不能悄悄漂移。"""
    from model.pipeline.stages.declare import DeclareStage
    from model.pipeline.templates import load_template
    assert DeclareStage(endpoint=None)._system() == load_template("dslgen.system")


def test_dslgen_system_carries_knowledge_when_on(monkeypatch):
    from model.pipeline.stages import declare as declare_mod
    from model.pipeline.stages.declare import DeclareStage
    monkeypatch.setattr(declare_mod, "load_knowledge",
                        lambda *_a, **_k: [{"id": "D1", "text": "Generic rule."}])
    system = DeclareStage(endpoint=None, knowledge=True)._system()
    assert "D1. Generic rule." in system
    assert system.startswith(
        __import__("model.pipeline.templates", fromlist=["x"])
        .load_template("dslgen.system"))


def test_dslgen_system_conventions_only_unaffected_by_knowledge_branch():
    """conventions=True, knowledge=False 时，_system() 只追加约定附录，
    与本任务之前的行为逐字节相同——约定分支必须保留在 knowledge 分支之前。

    换代后 conventions 移出了 DeclareStage 基类，进了
    archive._ArchivedDeclareStage；这条测试锁的是"约定附录在知识附录之前"
    这个顺序不变量本身，不是锁在哪个类上，所以只换构造的类。"""
    from model.pipeline.archive import _ArchivedDeclareStage
    from model.pipeline.templates import load_template, render
    from model.pipeline.conventions import conventions_block
    expected = (load_template("dslgen.system") + "\n"
                + render("dslgen.conventions", conventions=conventions_block()))
    actual = _ArchivedDeclareStage(endpoint=None, conventions=True,
                                   knowledge=False)._system()
    assert actual == expected


def test_check_items_rejects_non_list_evidence():
    """evidence 不是 list（如整数）时应抛 KnowledgeError，而不是 TypeError——
    畸形数据也要被拦下并给出清晰信息，不能在 len() 上直接崩掉。"""
    from model.pipeline.knowledge import KnowledgeError, check_items
    items = [{"id": "D1", "text": "Something generic.", "evidence": 2}]
    with pytest.raises(KnowledgeError, match="证据"):
        check_items(items, set(), max_items=12, min_evidence=2)


def test_cases_block_shows_question_pred_and_gold():
    from scripts.distill import cases_block
    out = cases_block([{"index": 7, "question": "How many?",
                        "pred_sql": "SELECT a", "gold_sql": "SELECT ABS(a)"}])
    assert "#7" in out and "How many?" in out
    assert "SELECT a" in out and "SELECT ABS(a)" in out


def test_parse_items_extracts_json_array():
    from scripts.distill import parse_items
    reply = 'blah\n```json\n{"items": [{"id": "D1", "text": "T", "evidence": [1,2]}]}\n```'
    assert parse_items(reply) == [{"id": "D1", "text": "T", "evidence": [1, 2]}]


def test_parse_items_raises_on_garbage():
    import pytest
    from scripts.distill import DistillError, parse_items
    with pytest.raises(DistillError):
        parse_items("I could not find any patterns, sorry.")


def test_wrong_cases_picks_only_failures(tmp_path, monkeypatch):
    import json as _json
    from scripts import distill
    data = [{"db_id": "d", "question": "q0", "query": "G0"},
            {"db_id": "d", "question": "q1", "query": "G1"}]
    (tmp_path / "train.json").write_text(_json.dumps(data), encoding="utf-8")
    (tmp_path / "p.json").write_text(_json.dumps(["P0", "P1"]), encoding="utf-8")
    (tmp_path / "r.json").write_text(_json.dumps(
        {"samples": [{"index": 0, "match": False}, {"index": 1, "match": True}]}),
        encoding="utf-8")
    cases = distill.wrong_cases(tmp_path / "train.json", tmp_path / "p.json",
                                tmp_path / "r.json")
    assert [c["index"] for c in cases] == [0]
    assert cases[0]["pred_sql"] == "P0" and cases[0]["gold_sql"] == "G0"


def test_gate_keeps_precise_rules_and_drops_thin_ones(monkeypatch):
    from scripts import distill
    rules = [{"id": "L1", "when": {"question": "x"}, "message": "m"},
             {"id": "L2", "when": {"question": "y"}, "message": "m"},
             {"id": "L3", "when": {"question": "z"}, "message": "m"}]
    # L1 干净（6 触发 6 有用）、L2 薄利（10 触发 5 有用）、L3 触发太少（2 次）
    monkeypatch.setattr(distill, "_rule_hits", lambda *a, **k: {
        "rule:L1": list(range(0, 6)),
        "rule:L2": list(range(0, 5)) + list(range(100, 105)),
        "rule:L3": [0, 1],
    })
    monkeypatch.setattr(distill, "_match_map", lambda *a, **k: (
        {i: False for i in range(6)} | {i: True for i in range(100, 105)}))
    kept, dropped = distill.gate(rules, split="en_train", pred="p", results="r",
                                 min_trigger=5, min_precision=0.7)
    assert [r["id"] for r in kept] == ["L1"]
    assert {d[0] for d in dropped} == {"L2", "L3"}
    assert kept[0]["measured"]["precision"] == 1.0


def test_gate_writes_measured_onto_kept_rules(monkeypatch):
    from scripts import distill
    rules = [{"id": "L1", "when": {"question": "x"}, "message": "m"}]
    monkeypatch.setattr(distill, "_rule_hits", lambda *a, **k: {"rule:L1": [0, 1, 2, 3, 4]})
    monkeypatch.setattr(distill, "_match_map", lambda *a, **k: {i: False for i in range(5)})
    kept, _ = distill.gate(rules, split="en_train", pred="p", results="r",
                           min_trigger=5, min_precision=0.7)
    assert kept[0]["measured"] == {"trigger": 5, "useful": 5, "harmful": 0,
                                   "precision": 1.0}


def test_parse_items_supports_alternate_key():
    """parse_items 泛化成 key 参数化——cmd_rules 复用它抽 {"rules": [...]}，
    而不是重写一遍花括号定位 + json.loads 那套逻辑。"""
    from scripts.distill import parse_items
    reply = ('blah\n{"rules": [{"id": "L1", "when": {"question": "x"}, '
             '"message": "m"}]}')
    assert parse_items(reply, key="rules") == [
        {"id": "L1", "when": {"question": "x"}, "message": "m"}]


def test_backbone_label_marks_thinking_variant_only():
    """distilled_by 标签必须与骨干实际配置一致：pro-t 带 request_params.extra_body
    （thinking 开启），标签要带 -thinking 后缀；pro 没有，标签不带。"""
    from scripts.distill import _backbone_label
    assert _backbone_label("pro-t") == "deepseek-v4-pro-thinking"
    assert _backbone_label("pro") == "deepseek-v4-pro"


def test_dslgen_system_conventions_precede_knowledge_when_both_on(monkeypatch):
    """两个附录都开时，约定块必须排在知识块前面——这是真正锁死顺序的测试：
    只开一个开关时另一分支根本不执行，对调分支顺序也照样能骗过测试；
    只有两个都开、再比较两个块在 system 里的位置索引，才能拦住顺序回归。

    换代后 conventions 与 knowledge 分处两个类
    （archive._ArchivedDeclareStage 覆写 `_system_extra` 插约定块，
    knowledge 分支留在 DeclareStage 基类的 `_system()` 里、原样继承）——
    要让两者同时生效，构造对象必须换成 _ArchivedDeclareStage，它同时支持
    两个开关；`_system()` 本身没有重写，用的还是基类那一份，所以锁的顺序
    不变量没有被削弱。monkeypatch 打的桩落在 declare 模块上，
    _ArchivedDeclareStage 继承来的 _system() 走的正是那个模块级
    load_knowledge，桩照样生效。"""
    from model.pipeline.archive import _ArchivedDeclareStage
    from model.pipeline.stages import declare as declare_mod
    from model.pipeline.templates import load_template
    monkeypatch.setattr(declare_mod, "load_knowledge",
                        lambda *_a, **_k: [{"id": "D1", "text": "Generic rule."}])
    system = _ArchivedDeclareStage(endpoint=None, conventions=True,
                                   knowledge=True)._system()
    conventions_pos = system.index("K1.")
    knowledge_pos = system.index("D1. Generic rule.")
    assert conventions_pos < knowledge_pos
    assert system.startswith(load_template("dslgen.system"))
