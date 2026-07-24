"""Tests for dslsql: chat_messages, declaration schema, validators, DeclareStage, e2e."""

import pytest


# ---------------------------------------------------------- chat_messages

def _endpoint(monkeypatch):
    pytest.importorskip("openai")
    from model.llm import ChatEndpoint

    monkeypatch.setenv("TEST_LLM_KEY", "sk-test")
    return ChatEndpoint(base_url="https://example.invalid/v1",
                        model="m", key_env="TEST_LLM_KEY")


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)

        class _Msg:  # 最小化模拟 openai 响应结构
            content = "REPLY"

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


def test_chat_messages_sends_full_conversation(monkeypatch):
    ep = _endpoint(monkeypatch)
    fake = _FakeCompletions()
    monkeypatch.setattr(ep._client.chat, "completions", fake)

    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]
    assert ep.chat_messages(messages, temperature=0.0) == "REPLY"
    assert fake.calls[0]["messages"] == messages
    assert fake.calls[0]["temperature"] == 0.0


def test_chat_still_builds_system_user_pair(monkeypatch):
    ep = _endpoint(monkeypatch)
    fake = _FakeCompletions()
    monkeypatch.setattr(ep._client.chat, "completions", fake)

    assert ep.chat("sys", "usr") == "REPLY"
    assert fake.calls[0]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


# ---------------------------------------------------------- parse_output

GOOD_JSON = """
{"sql": "SELECT count(*) AS n FROM singer",
 "declarations": {
   "time_context": {"displaced": false, "reference": ""},
   "outputs": [{"name": "n", "source": "derived", "expr": "count(*)"}],
   "assumptions": []}}
"""


def test_parse_output_accepts_plain_and_fenced_json():
    from model.pipeline.dsl import parse_output

    out, err = parse_output(GOOD_JSON)
    assert err == "" and out.sql.startswith("SELECT")
    assert out.declarations.outputs[0].source == "derived"

    out2, err2 = parse_output("```json\n" + GOOD_JSON + "\n```")  # 栅栏也能抽
    assert err2 == "" and out2.sql == out.sql


def test_parse_output_rejects_garbage_with_readable_message():
    from model.pipeline.dsl import parse_output

    out, err = parse_output("I think the answer is SELECT 1")
    assert out is None and "JSON" in err


def test_parse_output_rejects_missing_fields():
    from model.pipeline.dsl import parse_output

    # 缺 time_context —— 必填字段是①"强制表态"的主武器，不许缺
    out, err = parse_output(
        '{"sql": "SELECT 1", "declarations": {"outputs": '
        '[{"name": "x", "source": "column", "column": "t.c"}]}}')
    assert out is None and "time_context" in err


def test_parse_output_source_field_pairing():
    from model.pipeline.dsl import parse_output

    # source=column 必须给 column；source=derived 必须给 expr
    out, err = parse_output(
        '{"sql": "SELECT a FROM t", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "a", "source": "derived"}]}}')
    assert out is None and "expr" in err


def test_parse_output_accepts_null_for_optional_text_fields():
    """模型在"不适用"的槽位写 null 是常态，等价于空串，不该烧一轮修复。"""
    from model.pipeline.dsl import parse_output

    out, err = parse_output(
        '{"sql": "SELECT a FROM t", "declarations": {'
        '"time_context": {"displaced": false, "reference": null}, '
        '"outputs": [{"name": "a", "source": "column", "column": "t.a", '
        '"expr": null, "anchors": null}], '
        '"assumptions": [{"target": "t.a", "where": null, "value": 3}]}}')
    assert err == ""
    assert out.declarations.time_context.reference == ""
    assert out.declarations.outputs[0].expr == "" and out.declarations.outputs[0].anchors == {}
    assert out.declarations.assumptions[0].where == ""


def test_parse_output_rejects_null_assumption_value():
    """value=null 不是"不适用"而是没写出假设值——必须打回，不能变成字符串 "None"。"""
    from model.pipeline.dsl import parse_output

    out, err = parse_output(
        '{"sql": "SELECT a FROM t", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "a", "source": "column", "column": "t.a"}], '
        '"assumptions": [{"target": "t.a", "value": null}]}}')
    assert out is None and "value" in err


def test_parse_output_stringifies_numeric_assumption_value():
    from model.pipeline.dsl import parse_output

    out, err = parse_output(
        '{"sql": "SELECT 2001", "declarations": {'
        '"time_context": {"displaced": true, "reference": "release"}, '
        '"outputs": [{"name": "y", "source": "derived", "expr": "2001"}], '
        '"assumptions": [{"target": "singer.Song_release_year", "value": 2001}]}}')
    assert err == "" and out.declarations.assumptions[0].value == "2001"


# ---------------------------------------------------------- C1/C2 校验

def _decl(payload: str):
    """从 JSON 造 Declarations（借 parse_output 走同一入口）。"""
    from model.pipeline.dsl import parse_output

    out, err = parse_output(payload)
    assert err == "", err
    return out


def _tree(sql: str):
    import sqlglot

    return sqlglot.parse_one(sql, dialect="sqlite")


def test_c1_flags_count_mismatch_and_kind_mismatch():
    from model.pipeline.dsl import _c1_alignment

    out = _decl(
        '{"sql": "SELECT Name, Age FROM singer", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "Name", "source": "column", "column": "singer.Name"}]}}')
    issues = _c1_alignment(out.declarations, _tree(out.sql))
    assert issues and "2" in issues[0]          # SQL 2 列 vs 声明 1 条

    out = _decl(
        '{"sql": "SELECT Age FROM singer", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "Age", "source": "derived", "expr": "Age + 1"}]}}')
    issues = _c1_alignment(out.declarations, _tree(out.sql))
    assert issues and "裸列" in issues[0]       # 声明 derived 但 SQL 是裸列


def test_c1_rejects_select_star_but_allows_count_star():
    from model.pipeline.dsl import _c1_alignment

    out = _decl(
        '{"sql": "SELECT * FROM singer", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "all", "source": "column", "column": "singer.Name"}]}}')
    assert _c1_alignment(out.declarations, _tree(out.sql))  # SELECT * 无法逐列声明

    out = _decl(GOOD_JSON)                       # count(*) 里的 * 不该被误伤
    assert _c1_alignment(out.declarations, _tree(out.sql)) == []


def test_c2_displaced_requires_some_derived_output():
    from model.pipeline.dsl import _c2_consistency

    out = _decl(
        '{"sql": "SELECT Name, Age FROM singer", "declarations": {'
        '"time_context": {"displaced": true, "reference": "release year"}, '
        '"outputs": [{"name": "Name", "source": "column", "column": "singer.Name"}, '
        '{"name": "Age", "source": "column", "column": "singer.Age"}]}}')
    issues = _c2_consistency(out.declarations, _tree(out.sql))
    assert issues and "displaced" in issues[0]


def test_c2_assumption_value_must_appear_and_not_as_filter():
    from model.pipeline.dsl import _c2_consistency

    base = ('{"sql": "%s", "declarations": {'
            '"time_context": {"displaced": true, "reference": "hypothetical release"}, '
            '"outputs": [{"name": "y", "source": "derived", "expr": "Age + 1", '
            '"anchors": {"Age": "now"}}], '
            '"assumptions": [{"target": "singer.Song_release_year", '
            '"where": "Song_Name = \'G\'", "value": "2001"}]}}')

    # 假设值没出现在 SQL：被忽略
    out = _decl(base % "SELECT Age + 1 AS y FROM singer")
    assert any("没有出现" in i for i in _c2_consistency(out.declarations, _tree(out.sql)))

    # 假设值只出现在等值过滤：反事实被当成了过滤条件
    out = _decl(base % "SELECT Age + 1 AS y FROM singer WHERE Song_release_year = 2001")
    assert any("过滤" in i for i in _c2_consistency(out.declarations, _tree(out.sql)))

    # 假设值参与计算：合格
    out = _decl(base % "SELECT Age + 2001 - 2026 AS y FROM singer")
    assert _c2_consistency(out.declarations, _tree(out.sql)) == []


# ---------------------------------------------------------- C3/C4 + validate

@pytest.fixture()
def toy_db(tmp_path):
    import sqlite3

    db = tmp_path / "toy.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE singer (Name TEXT, Age INT, Song_Name TEXT)")
    conn.executemany("INSERT INTO singer VALUES (?, ?, ?)",
                     [("Balmoor", 20, "Gentleman"), ("Bob", 30, "Hello")])
    conn.commit()
    conn.close()
    return db


def test_c3_flags_unknown_table_and_column(toy_db):
    from model.pipeline.dsl import _c3_grounding, load_schema_info

    info = load_schema_info(toy_db)
    assert info == {"singer": {"name", "age", "song_name"}}

    out = _decl(
        '{"sql": "SELECT Name FROM singer", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "Name", "source": "column", "column": "artist.Name"}]}}')
    issues = _c3_grounding(out.declarations, _tree(out.sql), info, toy_db)
    assert any("artist" in i for i in issues)   # 幻觉表

    out = _decl(
        '{"sql": "SELECT Height FROM singer", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "h", "source": "derived", "expr": "Height * 2"}]}}')
    issues = _c3_grounding(out.declarations, _tree(out.sql), info, toy_db)
    assert any("height" in i.lower() for i in issues)   # 幻觉列（expr 里）


def test_c3_suggests_close_value_for_missing_literal(toy_db):
    from model.pipeline.dsl import _c3_grounding, load_schema_info

    out = _decl(
        '{"sql": "SELECT Age FROM singer WHERE Name = \'Balmor\'", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "Age", "source": "column", "column": "singer.Age"}]}}')
    issues = _c3_grounding(out.declarations, _tree(out.sql),
                           load_schema_info(toy_db), toy_db)
    assert any("Balmoor" in i for i in issues)  # 'Balmor' 打错 -> 提示库内近邻

    # 字面值真实存在则不打扰
    out = _decl(
        '{"sql": "SELECT Age FROM singer WHERE Name = \'Bob\'", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "Age", "source": "column", "column": "singer.Age"}]}}')
    assert _c3_grounding(out.declarations, _tree(out.sql),
                         load_schema_info(toy_db), toy_db) == []


def test_c3_does_not_flag_real_value_beyond_the_neighbor_pool_cap(tmp_path):
    """值域大于 cap 时，截断的候选池只用于找近邻，不能用来判定"值不存在"。

    否则 soccer_1.Player.player_name（10848 个不同值）这类列上，排在 cap 之后的
    真实值会被当成打错的字面值，白白逼模型改掉正确的 SQL。
    """
    import sqlite3

    from model.pipeline.dsl import _c3_literal_neighbors, load_schema_info

    db = tmp_path / "big.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE singer (Name TEXT)")
    # 'Balmore' 真实存在，但排在候选池（cap=1）之外，且与池内的 'Balmoor' 极像
    conn.executemany("INSERT INTO singer VALUES (?)", [("Balmoor",), ("Balmore",)])
    conn.commit()
    conn.close()

    info = load_schema_info(db)
    tree = _tree("SELECT Name FROM singer WHERE Name = 'Balmore'")
    assert _c3_literal_neighbors(tree, info, db, cap=1) == []

    # 真正打错的值仍要提示（cap 之内能找到近邻）
    tree = _tree("SELECT Name FROM singer WHERE Name = 'Balmor'")
    issues = _c3_literal_neighbors(tree, info, db, cap=1)
    assert issues and "Balmoor" in issues[0]


def test_c4_requires_anchor_per_expr_column_when_displaced():
    from model.pipeline.dsl import _c4_anchors

    out = _decl(
        '{"sql": "SELECT Age + 1 AS y FROM singer", "declarations": {'
        '"time_context": {"displaced": true, "reference": "release"}, '
        '"outputs": [{"name": "y", "source": "derived", "expr": "Age + 1"}]}}')
    issues = _c4_anchors(out.declarations)
    assert issues and "age" in issues[0].lower()        # Age 缺 anchor

    out = _decl(
        '{"sql": "SELECT Age + 1 AS y FROM singer", "declarations": {'
        '"time_context": {"displaced": true, "reference": "release"}, '
        '"outputs": [{"name": "y", "source": "derived", "expr": "Age + 1", '
        '"anchors": {"Age": "value as of now"}}]}}')
    assert _c4_anchors(out.declarations) == []

    # 未位移时不强制 anchor
    out = _decl(GOOD_JSON)
    assert _c4_anchors(out.declarations) == []


def test_validate_aggregates_and_passes_good_output(toy_db):
    from model.pipeline.dsl import load_schema_info, parse_output, validate

    out, _ = parse_output(GOOD_JSON)
    assert validate(out, load_schema_info(toy_db), toy_db,
                    question="", profile_ids=set()) == []

    out, _ = parse_output(
        '{"sql": "SELECT_BROKEN((", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "x", "source": "column", "column": "singer.Name"}]}}')
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="", profile_ids=set())
    assert issues and "解析" in issues[0]      # SQL 解析失败单独成 issue


# ---------------------------------------------------------- DeclareStage

BAD_JSON = (
    '{"sql": "SELECT Name FROM singer", "declarations": {'
    '"time_context": {"displaced": false}, '
    '"outputs": [{"name": "Name", "source": "derived", "expr": "Age + 1"}]}}'
)   # C1: 声明 derived 但 SQL 是裸列


class _FakeEndpoint:
    """按脚本轮流吐回复；记录每次收到的消息列表。"""

    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def chat_messages(self, messages, **kw):
        self.calls.append([dict(m) for m in messages])
        return next(self.replies)


def _run_declare(toy_db, replies, max_repairs=2):
    from model.pipeline.context import PipelineContext
    from model.pipeline.stages.declare import DeclareStage

    ctx = PipelineContext(question="q", db_path=toy_db)
    ctx.schema, ctx.plans = "CREATE TABLE singer (...)", ["1. do it"]
    endpoint = _FakeEndpoint(replies)
    DeclareStage(endpoint, max_repairs=max_repairs).run(ctx)
    return ctx, endpoint


def test_declare_good_first_try_single_call(toy_db):
    ctx, endpoint = _run_declare(toy_db, [GOOD_JSON])
    [c] = ctx.candidates
    assert c.sql == "SELECT count(*) AS n FROM singer"
    assert c.checks["passed"] is True and len(c.checks["rounds"]) == 1
    assert c.checks["declarations"]["outputs"][0]["name"] == "n"


def test_declare_noplan_mode_runs_without_plans(toy_db):
    """use_plan=False：ctx.plans 为空也要出恰好一个候选，user 消息无 Plan 段。

    no-plan 消融的接线关键——知识（约定）与问题在同一条消息里直达 dslgen，
    没有"planner 先把决定定死"的前站。
    """
    from model.pipeline.context import PipelineContext
    from model.pipeline.stages.declare import DeclareStage

    ctx = PipelineContext(question="How many singers?", db_path=toy_db)
    ctx.schema = "CREATE TABLE singer (...)"          # 刻意不设 ctx.plans
    endpoint = _FakeEndpoint([GOOD_JSON])
    DeclareStage(endpoint, use_plan=False).run(ctx)

    [c] = ctx.candidates
    assert c.sql == "SELECT count(*) AS n FROM singer" and c.plan == ""
    user = endpoint.calls[0][1]["content"]
    assert "Plan:" not in user
    assert "How many singers?" in user and "CREATE TABLE singer" in user


def test_declare_noplan_still_carries_conventions(toy_db):
    """no-plan + conventions：附录进 system，user 走 noplan 模板。"""
    from model.pipeline.context import PipelineContext
    from model.pipeline.stages.declare import DeclareStage

    ctx = PipelineContext(question="q", db_path=toy_db)
    ctx.schema = "CREATE TABLE singer (...)"
    endpoint = _FakeEndpoint([GOOD_JSON])
    DeclareStage(endpoint, use_plan=False, conventions=True).run(ctx)
    system = endpoint.calls[0][0]["content"]
    assert "K1. " in system and "not a valid stance" in system
    assert len(endpoint.calls) == 1


def test_declare_repairs_with_issue_feedback(toy_db):
    ctx, endpoint = _run_declare(toy_db, [BAD_JSON, GOOD_JSON])
    [c] = ctx.candidates
    assert c.checks["passed"] is True and len(c.checks["rounds"]) == 2
    assert c.checks["rounds"][0]["issues"]           # 第一轮抓到问题
    # 第二次调用带着历史：assistant 原文 + 含具体失败项的修复请求
    followup = endpoint.calls[1]
    assert followup[2]["role"] == "assistant" and followup[2]["content"] == BAD_JSON
    assert followup[3]["role"] == "user" and "裸列" in followup[3]["content"]


def test_declare_exhausted_keeps_last_sql(toy_db):
    ctx, _ = _run_declare(toy_db, [BAD_JSON, BAD_JSON, BAD_JSON], max_repairs=2)
    [c] = ctx.candidates
    # 轮数用尽：SQL 照常下传（绝不空串），trace 记未通过
    assert c.sql == "SELECT Name FROM singer"
    assert c.checks["passed"] is False and len(c.checks["rounds"]) == 3


def test_declare_trace_keeps_declarations_of_every_round(toy_db):
    """设计 §5：trace 记每轮的 SQL 与声明——修复前后的声明差异是过程证据。"""
    ctx, _ = _run_declare(toy_db, [BAD_JSON, GOOD_JSON])
    [c] = ctx.candidates
    first, second = c.checks["rounds"]
    assert first["declarations"]["outputs"][0]["source"] == "derived"
    assert first["declarations"]["outputs"][0]["name"] == "Name"
    assert second["declarations"]["outputs"][0]["name"] == "n"


def test_declare_unparseable_reply_records_empty_sql(toy_db):
    ctx, _ = _run_declare(toy_db, ["no json here"] * 3, max_repairs=2)
    [c] = ctx.candidates
    assert c.sql == "" and c.checks["passed"] is False
    assert all(r["issues"] for r in c.checks["rounds"])


# ---------------------------------------------------------- 端到端

def test_dslsql_end_to_end_with_repair(monkeypatch, tmp_path):
    """planner → dslgen(坏声明→修复→好声明) → 执行投票 → trace 含 checks。"""
    import json
    import sqlite3

    pytest.importorskip("openai")
    from model.pipeline.plansql import ProTPlanDsl

    db = tmp_path / "toy.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE singer (Name TEXT, Age INT, Song_Name TEXT)")
    conn.execute("INSERT INTO singer VALUES ('A', 20, 'G')")
    conn.commit()
    conn.close()

    monkeypatch.setenv(ProTPlanDsl.endpoint_spec["key_env"], "sk-test")
    generator = ProTPlanDsl()

    dsl_replies = iter([BAD_JSON, GOOD_JSON])

    def fake_chat_messages(messages, **kw):
        # dslgen.user.md 以 "JSON:" 结尾；planner 走 chat() 也汇到这里
        if "JSON:" in messages[1]["content"]:
            return next(dsl_replies)
        return "1. count the singers"

    monkeypatch.setattr(generator.endpoint, "chat_messages", fake_chat_messages)

    from archer_eval.data import Sample

    sample = Sample(db_id="toy", query="SELECT count(*) FROM singer",
                    question="How many singers?")
    preds = generator.predict_all([sample], [db], progress=False)
    assert preds == ["SELECT count(*) AS n FROM singer"]

    [trace] = generator.trace_records
    checks = trace["candidates"][0]["checks"]
    assert checks["passed"] is True and len(checks["rounds"]) == 2
    assert checks["rounds"][0]["issues"]      # 第一轮的失败项进了 trace
    json.dumps(trace)                          # trace 必须可直接落盘


# ---------------------------------------------------------- 库画像 / considered

def _decl_with_considered(considered):
    return {
        "time_context": {"displaced": False, "reference": ""},
        "outputs": [{"name": "n", "source": "column", "column": "singer.Name",
                     "expr": "", "anchors": {}}],
        "assumptions": [],
        "considered": considered,
    }


def _validate_considered(toy_db, considered, profile_ids={"P1"}):
    from model.pipeline.dsl import DslOutput, load_schema_info, validate

    out = DslOutput.model_validate(
        {"sql": "SELECT Name FROM singer",
         "declarations": _decl_with_considered(considered)})
    return validate(out, load_schema_info(toy_db), toy_db,
                    question="q", profile_ids=profile_ids)


def test_render_profile_numbers_items():
    from model.pipeline.dsl import render_profile

    assert render_profile(["甲", "乙"]) == "P1. 甲\nP2. 乙"


def test_render_profile_empty_is_explicit():
    from model.pipeline.dsl import render_profile

    assert render_profile([]) == "(none for this database)"


def test_profile_ids_match_render_numbering():
    """两处编号必须同源，否则 C5a 会要求一个 prompt 里不存在的编号。"""
    from model.pipeline.dsl import profile_ids_for, render_profile

    items = ["a", "b", "c"]
    rendered = render_profile(items)
    assert all(f"{pid}. " in rendered for pid in profile_ids_for(items))


def test_c5a_missing_disposition_is_reported(toy_db):
    issues = _validate_considered(toy_db, [])
    assert any("P1" in i and "表态" in i for i in issues), issues


def test_c5a_unused_requires_note(toy_db):
    issues = _validate_considered(
        toy_db, [{"item": "P1", "used": False, "note": ""}])
    assert any("P1" in i and "理由" in i for i in issues), issues


def test_c5a_passes_when_all_disposed(toy_db):
    issues = _validate_considered(
        toy_db, [{"item": "P1", "used": False, "note": "本题不涉及年龄换算"}])
    assert not [i for i in issues if "P1" in i], issues


def test_c5a_used_true_needs_no_note(toy_db):
    issues = _validate_considered(
        toy_db, [{"item": "P1", "used": True, "note": ""}])
    assert not [i for i in issues if "P1" in i], issues


def test_c5a_silent_when_profile_empty(toy_db):
    """画像为空（关闭画像注入或无事实的库）时，considered 不该被要求。"""
    assert _validate_considered(toy_db, [], profile_ids=set()) == []


# ---------------------------------------------------------- C6 比率线索

# toy_db 只有 singer 一张表，测不出"同表兄弟数值列"；C6 打真库（只读）
def _concert_db():
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "database" /
            "concert_singer" / "concert_singer.sqlite")


def test_c6_hints_unused_sibling_numeric_column():
    """题面问 rate、SQL 里没有除法 -> 提示同表还有 Capacity。"""
    from model.pipeline.dsl import _c6_ratio_hint

    issues = _c6_ratio_hint(
        _tree("SELECT Name, Average FROM stadium ORDER BY Average DESC"),
        "Which stadium has the highest average attendance rate?", _concert_db())
    assert any("Capacity" in i for i in issues), issues


def test_c6_silent_when_any_division_present():
    """SQL 里已经做了除法 -> 模型已经在算比率，闭嘴。

    若在这里还报一条就是白烧一轮修复去改一个已经对的答案。
    """
    from model.pipeline.dsl import _c6_ratio_hint

    assert not _c6_ratio_hint(
        _tree("SELECT Name, Average / Capacity AS r FROM stadium"),
        "Which stadium has the highest average attendance rate?", _concert_db())


def test_c6_silent_without_ratio_word():
    """题面没有比率词 -> 不打扰（避免把普通取值题逼成比率题）。"""
    from model.pipeline.dsl import _c6_ratio_hint

    assert not _c6_ratio_hint(
        _tree("SELECT Name, Average FROM stadium"),
        "List the name and average attendance of each stadium.", _concert_db())


def test_c6_average_alone_is_not_a_ratio_word():
    """'average' 不算比率词——库里恰好有名为 Average 的列，宽进必炸。"""
    from model.pipeline.dsl import _RATIO_WORDS

    assert not _RATIO_WORDS.search("What is the average attendance?")
    assert _RATIO_WORDS.search("What is the average attendance rate?")


def test_c6_silent_when_question_supplies_the_ratio():
    """题面已给百分数字面量 -> 比率是输入不是待求量，别提示。

    不加这道闸门，"给定比率"类题目会被误触发，白烧一轮修复去改一个已经对的答案。
    """
    from model.pipeline.dsl import _c6_ratio_hint

    assert not _c6_ratio_hint(
        _tree("SELECT Population * 1.004 AS p FROM country WHERE Name = 'UK'"),
        "The annual population growth rate in the UK is 0.4%. "
        "What is the population one year later?",
        _concert_db())


def test_c6_ratio_words_match_plural():
    """'attendance rates' 这类复数形式也要能命中——漏了复数就打不中检查目标。"""
    from model.pipeline.dsl import _RATIO_WORDS

    assert _RATIO_WORDS.search("the lowest and highest average attendance rates")
    assert _RATIO_WORDS.search("the highest attendance rate")


# ---------------------------------------------------------- C5b 锚一致

def _decl_anchor(kind, expr, ref=""):
    return {
        "time_context": {"displaced": True, "reference": "2001"},
        "outputs": [{"name": "a", "source": "derived", "column": "",
                     "expr": expr,
                     "anchors": {"Age": {"kind": kind, "ref": ref}}}],
        "assumptions": [], "considered": [],
    }


def _validate_anchor(toy_db, sql, kind, expr, ref="", question="q"):
    from model.pipeline.dsl import DslOutput, load_schema_info, validate

    out = DslOutput.model_validate(
        {"sql": sql, "declarations": _decl_anchor(kind, expr, ref)})
    # C5b 是建议级检查，默认关；测它就得显式打开
    return validate(out, load_schema_info(toy_db), toy_db,
                    question=question, profile_ids=set(), extra_checks=True)


def test_anchor_now_requires_now_in_sql(toy_db):
    """声明锚在当前、SQL 里却没有 'now' -> 自相矛盾。"""
    issues = _validate_anchor(
        toy_db, "SELECT Age + 5 AS a FROM singer", "now", "Age + 5")
    assert any("now" in i and "Age" in i for i in issues), issues


def test_anchor_now_satisfied_by_strftime(toy_db):
    sql = "SELECT Age + 2001 - strftime('%Y','now') AS a FROM singer"
    issues = _validate_anchor(
        toy_db, sql, "now", "Age + 2001 - strftime('%Y','now')")
    assert not [i for i in issues if "kind=now" in i], issues


def test_anchor_ref_says_current_but_kind_is_not_now(toy_db):
    """ref 写 'current age…' 却挑了别的 kind——枚举被绕过的典型形态。

    没有这一条，模型只要把锚写成 literal 就能绕过 C5b，枚举就白做了。
    """
    issues = _validate_anchor(
        toy_db, "SELECT Age - 3 AS a FROM singer", "literal", "Age - 3",
        ref="current age of the singer as stored in the database")
    assert any("kind" in i and "Age" in i for i in issues), issues


def test_anchor_plain_string_degrades_to_literal():
    """anchors 写成裸字符串时按 literal 收下，不整轮作废。"""
    from model.pipeline.dsl import OutputDecl

    d = OutputDecl.model_validate(
        {"name": "a", "source": "derived", "column": "", "expr": "Age",
         "anchors": {"Age": "age at song release"}})
    assert d.anchors["Age"].kind == "literal"
    assert d.anchors["Age"].ref == "age at song release"


def test_anchor_rejects_unknown_kind():
    from model.pipeline.dsl import parse_output

    out, err = parse_output(
        '{"sql": "SELECT Age FROM singer", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "a", "source": "derived", "expr": "Age", '
        '"anchors": {"Age": {"kind": "vibes", "ref": ""}}}]}}')
    assert out is None and "kind" in err


def test_c5b_silent_when_question_is_not_time_displaced(toy_db):
    """displaced=false 时"存的是当前值"是无害陈述，没有换算可以算错。

    "current age as stored" 是正确声明里的常见措辞，没有这道闸门会把大量
    本来判对的题目错判。
    """
    from model.pipeline.dsl import DslOutput, load_schema_info, validate

    out = DslOutput.model_validate({
        "sql": "SELECT Age AS a FROM singer",
        "declarations": {
            "time_context": {"displaced": False, "reference": ""},
            "outputs": [{"name": "a", "source": "derived", "column": "",
                         "expr": "Age",
                         "anchors": {"Age": {"kind": "now", "ref": "current age"}}}],
            "assumptions": [], "considered": []}})
    issues = validate(out, load_schema_info(toy_db), toy_db,
                      question="q", profile_ids=set(), extra_checks=True)
    assert not [i for i in issues if "now" in i], issues


def test_c5b_silent_when_question_gives_the_rate(toy_db):
    """题面已给出百分数（"growth rate is 0.4%"）时不触发。

    这类题的时间位移由给定比率表达（Population * 1.004），SQL 里合法地
    没有任何日期函数。C6 对同一形态早有 _GIVEN_RATIO 闸门，C5b 抄齐。
    """
    issues = _validate_anchor(
        toy_db, "SELECT Age * 1.004 AS a FROM singer", "now", "Age * 1.004",
        question="The annual growth rate is 0.4%. What will the value be in a year?")
    assert not [i for i in issues if "now" in i], issues


def test_extra_checks_default_off_keeps_m2_baseline_behaviour():
    """C5b/C6 默认关——基线（三开关全 False）的校验集合不含建议级检查。"""
    import inspect

    from model.pipeline.dsl import validate

    assert inspect.signature(validate).parameters["extra_checks"].default is False


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


def test_c7_dodge_ignores_would_phrased_counterfactuals(toy_db):
    """would have/be 是价格反事实的问句语气，不是时间位移——不该触发。"""
    issues = _validate_conv(
        toy_db, "SELECT Age FROM singer",
        "If the price was increased by 10%, what would the total be?")
    assert not [i for i in issues if "displaced" in i], issues


def test_c7_all_silent_by_default(toy_db):
    """convention_checks 默认关——各消融档位与基线行为不变。"""
    import inspect
    from model.pipeline.dsl import validate

    assert inspect.signature(validate).parameters[
        "convention_checks"].default is False
