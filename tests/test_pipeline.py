"""Tests for model/pipeline (plansql): templates, voting, end-to-end with a fake LLM."""

import pytest


# ---------------------------------------------------------------- templates

def test_render_fills_placeholders(tmp_path):
    from model.pipeline.templates import render_text

    text = "Q: {question}\nS: {schema}"
    assert render_text(text, {"question": "q1", "schema": "s1"}) == "Q: q1\nS: s1"


def test_render_rejects_unknown_placeholder_and_lists_allowed():
    from model.pipeline.templates import render_text

    with pytest.raises(ValueError) as e:
        render_text("Q: {quesiton}", {"question": "q1"})
    assert "quesiton" in str(e.value)   # 指出写错的名字
    assert "question" in str(e.value)   # 列出可用的名字


def test_render_leaves_other_braces_alone():
    from model.pipeline.templates import render_text

    # 提示词里的 JSON 示例、集合写法不应被当成占位符
    text = 'like {"a": 1} and {question}'
    assert render_text(text, {"question": "q"}) == 'like {"a": 1} and q'


"""voting ----------------------------------------------------------------"""


def _ok(rows, n_cols=1):
    from archer_eval.execution import ExecutionResult

    return ExecutionResult(ok=True, rows=rows, n_cols=n_cols)


def _fail():
    from archer_eval.execution import ExecutionResult

    return ExecutionResult(ok=False, error="boom")


def test_vote_majority_wins():
    from model.pipeline.stages.vote import pick_winner

    results = [_ok([(1,)]), _ok([(2,)]), _ok([(1,)])]
    assert pick_winner(results) == 0  # 结果 (1,) 占两票


def test_vote_ignores_row_order_and_float_noise():
    from model.pipeline.stages.vote import pick_winner

    a = _ok([(1.0000000001,), (2.0,)])
    b = _ok([(2.0,), (1.0,)])         # 行序不同 + 浮点噪声，应视为同一结果
    c = _ok([(9.0,)])
    assert pick_winner([c, a, b]) == 1  # a、b 同组两票，取组内最早的下标 1


def test_vote_tie_prefers_earliest_candidate():
    from model.pipeline.stages.vote import pick_winner

    assert pick_winner([_ok([(1,)]), _ok([(2,)])]) == 0


def test_vote_failed_candidates_are_eliminated():
    from model.pipeline.stages.vote import pick_winner

    assert pick_winner([_fail(), _ok([(7,)])]) == 1


def test_vote_all_failed_falls_back_to_last():
    from model.pipeline.stages.vote import pick_winner

    # 全军覆没时返回最后一条候选（不返回空串，便于事后诊断），VA 自然记 0
    assert pick_winner([_fail(), _fail(), _fail()]) == 2


def test_shipped_templates_load_and_declare_expected_placeholders():
    from model.pipeline.templates import PLACEHOLDERS, load_template

    assert PLACEHOLDERS["planner.user"] == {"schema", "question"}
    assert PLACEHOLDERS["sqlgen.user"] == {"schema", "question", "plan"}
    assert PLACEHOLDERS["dslgen.user"] == {"schema", "question", "plan"}
    assert PLACEHOLDERS["dslgen.repair"] == {"issues"}
    for name in PLACEHOLDERS:
        assert load_template(name).strip()  # 所有模板文件齐全且非空


"""end-to-end（假 LLM + 临时小库）--------------------------------------"""


def _toy_db(tmp_path):
    import sqlite3

    db = tmp_path / "toy.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE singer (name TEXT, age INT)")
    conn.executemany("INSERT INTO singer VALUES (?, ?)", [("A", 20), ("B", 30)])
    conn.commit()
    conn.close()
    return db


def _fresh_plansql(monkeypatch, fake_chat, n_plans=1):
    """构造 plansql 实例，把 LLM 调用换成 fake_chat(system, user, **kw)。"""
    pytest.importorskip("openai")
    from model.pipeline.plansql import PlanSQLPro

    monkeypatch.setenv(PlanSQLPro.endpoint_spec["key_env"], "sk-test")
    generator = PlanSQLPro()
    generator.n_plans = n_plans
    monkeypatch.setattr(generator.endpoint, "chat", fake_chat)
    return generator


def _sample(question="How many singers?"):
    from archer_eval.data import Sample

    return Sample(db_id="toy", query="SELECT count(*) FROM singer", question=question)


def test_plansql_registered_in_models():
    from model import MODELS
    from model.pipeline.plansql import PlanSQLPro

    assert MODELS["plansql-pro"] is PlanSQLPro


def test_single_plan_end_to_end(monkeypatch, tmp_path):
    db = _toy_db(tmp_path)
    calls = []

    def fake_chat(system, user, **kw):
        calls.append((system, user, kw))
        if "SQL:" not in user:  # sqlgen.user.md 以 "SQL:" 结尾，以此区分两个角色
            return "1. Count all rows in singer.\n2. Return the count."
        return "SELECT count(*) FROM singer"

    generator = _fresh_plansql(monkeypatch, fake_chat)
    assert generator.predict(_sample(), db) == "SELECT count(*) FROM singer"
    # planner 一次 + sqlgen 一次
    assert len(calls) == 2
    # planner 的 user 消息里有 schema 和题面
    assert "CREATE TABLE singer" in calls[0][1] and "How many singers?" in calls[0][1]
    # 单 plan 时 planner 用贪心解码
    assert calls[0][2].get("temperature") == 0.0
    # sqlgen 的 user 消息里带着 plan
    assert "Count all rows" in calls[1][1]
    assert calls[1][2].get("temperature") == 0.0


def test_multi_plan_votes_on_execution_results(monkeypatch, tmp_path):
    db = _toy_db(tmp_path)
    sqls = iter([
        "SELECT count(*) FROM singer",          # 结果 2
        "SELECT count(*) FROM singer WHERE 1",  # 结果 2（同组，两票）
        "SELECT 999",                           # 结果 999（一票）
    ])
    plan_calls = []

    def fake_chat(system, user, **kw):
        if "SQL:" not in user:
            plan_calls.append(kw)
            return "1. some plan"
        return next(sqls)

    generator = _fresh_plansql(monkeypatch, fake_chat, n_plans=3)
    assert generator.predict(_sample(), db) == "SELECT count(*) FROM singer"
    # 多 plan 时 planner 用多样性温度
    assert all(kw.get("temperature") == generator.plan_temperature for kw in plan_calls)


def test_all_candidates_fail_returns_last_sql(monkeypatch, tmp_path):
    db = _toy_db(tmp_path)

    def fake_chat(system, user, **kw):
        if "SQL:" not in user:
            return "1. some plan"
        return "SELECT nope FROM missing"

    generator = _fresh_plansql(monkeypatch, fake_chat)
    # 执行失败仍返回候选 SQL 而非空串（VA 记 0，但保留诊断线索）
    assert generator.predict(_sample(), db) == "SELECT nope FROM missing"


def test_predict_all_collects_aligned_trace(monkeypatch, tmp_path):
    import json

    db = _toy_db(tmp_path)

    def fake_chat(system, user, **kw):
        return "1. plan" if "SQL:" not in user else "SELECT count(*) FROM singer"

    generator = _fresh_plansql(monkeypatch, fake_chat)
    samples = [_sample("q1"), _sample("q2")]
    preds = generator.predict_all(samples, [db, db], progress=False)

    assert preds == ["SELECT count(*) FROM singer"] * 2
    trace = generator.trace_records
    assert len(trace) == 2 and trace[0]["question"] == "q1"
    assert trace[0]["plans"] and trace[0]["candidates"][0]["ok"] is True
    assert trace[0]["winner"] == 0
    json.dumps(trace)  # trace 必须可直接落盘


def test_runner_writes_trace_sidecar(tmp_path):
    import json

    from model.__main__ import write_trace

    out = tmp_path / "plansql-flash_en_dev.json"
    trace_path = write_trace([{"question": "q", "winner": 0}], out)
    assert trace_path == tmp_path / "plansql-flash_en_dev.trace.json"
    assert json.loads(trace_path.read_text(encoding="utf-8"))[0]["winner"] == 0
    # 没有 trace 的普通模型什么都不写
    assert write_trace([], out) is None and write_trace(None, out) is None


def test_predict_all_records_llm_failure_as_empty(monkeypatch, tmp_path):
    db = _toy_db(tmp_path)

    def fake_chat(system, user, **kw):
        raise RuntimeError("api down")

    generator = _fresh_plansql(monkeypatch, fake_chat)
    preds = generator.predict_all([_sample()], [db], progress=False)
    assert preds == [""]  # 框架约定：LLM 调用失败记空串
    assert generator.trace_records[0]["error"]
