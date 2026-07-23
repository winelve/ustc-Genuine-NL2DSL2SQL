"""Tests for M2 dslsql: chat_messages, declaration schema, validators, DeclareStage, e2e."""

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
    """模型在"不适用"的槽位写 null 是常态，等价于空串，不该烧一轮修复。

    实测：en_dev 104 题里 38 题的第一轮就废在 time_context.reference=null 上
    （displaced=false 时模型自然写 null），整轮不产生任何声明、不做语义校验。
    """
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

    # 假设值只出现在等值过滤：反事实被当过滤条件（M1 复盘的典型病）
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
    assert validate(out, load_schema_info(toy_db), toy_db) == []

    out, _ = parse_output(
        '{"sql": "SELECT_BROKEN((", "declarations": {'
        '"time_context": {"displaced": false}, '
        '"outputs": [{"name": "x", "source": "column", "column": "singer.Name"}]}}')
    issues = validate(out, load_schema_info(toy_db), toy_db)
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
    from model.pipeline.plansql import DSLSQLPro

    db = tmp_path / "toy.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE singer (Name TEXT, Age INT, Song_Name TEXT)")
    conn.execute("INSERT INTO singer VALUES ('A', 20, 'G')")
    conn.commit()
    conn.close()

    monkeypatch.setenv(DSLSQLPro.endpoint_spec["key_env"], "sk-test")
    generator = DSLSQLPro()

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
