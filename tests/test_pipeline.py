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

    assert PLACEHOLDERS["planner.user"] == {"schema", "question", "profile"}
    assert PLACEHOLDERS["sqlgen.user"] == {"schema", "question", "plan"}
    assert PLACEHOLDERS["dslgen.user"] == {"schema", "question", "plan", "profile"}
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
    from model.pipeline.plansql import ProTPlan

    monkeypatch.setenv(ProTPlan.endpoint_spec["key_env"], "sk-test")
    generator = ProTPlan()
    generator.n_plans = n_plans
    monkeypatch.setattr(generator.endpoint, "chat", fake_chat)
    return generator


def _sample(question="How many singers?"):
    from archer_eval.data import Sample

    return Sample(db_id="toy", query="SELECT count(*) FROM singer", question=question)


def test_plansql_registered_in_models():
    from model import MODELS
    from model.pipeline.plansql import ProTPlan

    assert MODELS["pro-t-plan"] is ProTPlan


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


# ---------------------------------------------------------- 消融档位

def test_m3_variants_registered():
    from model import MODELS

    for name in ("pro-t-plandsl-prof", "pro-t-plandsl-prof-force",
                 "pro-t-plandsl-prof-force-chk"):
        assert name in MODELS, sorted(MODELS)


def test_m3_ablation_flags_are_strictly_nested():
    """a=给知识 / b=强制用 / c=加校验，逐档只加一个变量。"""
    from model.pipeline.plansql import ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk

    assert (ProTPlanDslProf.use_profile, ProTPlanDslProf.force_considered, ProTPlanDslProf.extra_checks) == (True, False, False)
    assert (ProTPlanDslProfForce.use_profile, ProTPlanDslProfForce.force_considered, ProTPlanDslProfForce.extra_checks) == (True, True, False)
    assert (ProTPlanDslProfForceChk.use_profile, ProTPlanDslProfForceChk.force_considered, ProTPlanDslProfForceChk.extra_checks) == (True, True, True)


def test_m2_baseline_keeps_all_m3_switches_off():
    """pro-t-plandsl 必须与已跑出的基线结果逐位一致，否则分差不可归因。"""
    from model.pipeline.plansql import DSLSQL, ProTPlanDsl

    for cls in (DSLSQL, ProTPlanDsl):
        assert (cls.use_profile, cls.force_considered, cls.extra_checks) == (False, False, False)


def test_m3_variants_share_the_m2_backbone():
    """消融只动开关，骨干必须同底，否则变量不唯一。"""
    from model.pipeline.plansql import ProTPlanDsl, ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk

    for cls in (ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk):
        assert cls.endpoint_spec == ProTPlanDsl.endpoint_spec
        assert cls.n_plans == ProTPlanDsl.n_plans
        assert cls.max_repairs == ProTPlanDsl.max_repairs


def test_preview_renders_every_shipped_template(capsys, monkeypatch):
    """预览工具必须能渲染所有模板——加占位符时最容易漏掉这里。"""
    import sys

    from model.pipeline.__main__ import main

    monkeypatch.setattr(sys, "argv",
                        ["model.pipeline", "--data", "en_dev", "--preview", "3"])
    main()
    out = capsys.readouterr().out
    assert "dslgen user" in out and "Facts derived from" in out
    assert "P1." in out and "singer.Age" in out      # 画像真的填进去了


def test_planner_message_byte_identical_when_profile_off():
    """use_profile=False 时 planner 消息必须与不带画像的基线逐字节相同。

    planner 提示词是对照组共用的；这条断言是"改消融不会污染基线"的
    唯一硬保证。基线模板正文写死在这里，改模板必须同步改这里并想清楚。
    """
    from model.pipeline.dsl import render_profile_block
    from model.pipeline.templates import render

    legacy = ("Database schema with sample rows:\n\n"
              "SCHEMA\n\n"
              "Question: Q\n\n"
              "Write the plan.\n")
    assert render("planner.user", schema="SCHEMA", question="Q",
                  profile=render_profile_block([])) == legacy


def test_planner_message_carries_profile_when_on():
    from model.pipeline.dsl import render_profile_block
    from model.pipeline.templates import render

    msg = render("planner.user", schema="SCHEMA", question="Q",
                 profile=render_profile_block(["存量时点列 singer.Age：…"]))
    assert "P1. 存量时点列 singer.Age" in msg
    assert msg.index("P1.") < msg.index("Question: Q")   # 画像必须在题面之前


def test_profile_reaches_planner_for_m3_but_not_for_m1_m2():
    from model.pipeline.plansql import ProTPlanDsl, ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk, ProTPlan

    for cls in (ProTPlan, ProTPlanDsl):
        assert cls.use_profile is False
    for cls in (ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk):
        assert cls.use_profile is True


def test_dslgen_system_byte_identical_when_conventions_off():
    """conventions=False 时 system 消息与基线完全一致，不能悄悄漂移。"""
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
    # 反投降条款必须在场：防止中性事实诱发模型放弃推理
    assert "not a valid stance" in system


def test_m3d_switch_matrix():
    """约定双臂：prose 臂只开 conventions，check 臂再开 convention_checks；
    画像/表态/C5bC6 三开关全关——约定轴与画像轴不叠加。"""
    from model.pipeline.plansql import ProTPlanDslConvCchk, ProTPlanDslConv

    for cls in (ProTPlanDslConv, ProTPlanDslConvCchk):
        assert (cls.use_profile, cls.force_considered, cls.extra_checks) \
            == (False, False, False)
    assert (ProTPlanDslConv.conventions, ProTPlanDslConv.convention_checks) == (True, False)
    assert (ProTPlanDslConvCchk.conventions, ProTPlanDslConvCchk.convention_checks) == (True, True)


def test_baseline_and_m3abc_keep_conventions_off():
    from model.pipeline.plansql import ProTPlanDsl, ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk

    for cls in (ProTPlanDsl, ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk):
        assert (cls.conventions, cls.convention_checks) == (False, False)


def test_noplan_variants_registered_and_single_variable():
    """no-plan 消融双臂：唯一差异 = conventions；其余开关全关（单变量红线）。"""
    from model import MODELS
    from model.pipeline.plansql import ProTDslConv, ProTDsl

    assert MODELS["pro-t-dsl"] is ProTDsl
    assert MODELS["pro-t-dsl-conv"] is ProTDslConv
    assert (ProTDsl.conventions, ProTDslConv.conventions) == (False, True)


def test_m3dx_noplan_adds_only_extra_checks():
    """pro-t-dsl-conv-chk = pro-t-dsl-conv + C5b/C6（建议级检查）。

    单变量：相对 pro-t-dsl-conv 唯一差异是 extra_checks；C7 保持关。"""
    from model import MODELS
    from model.pipeline.plansql import ProTDslConv, ProTDslConvChk

    assert MODELS["pro-t-dsl-conv-chk"] is ProTDslConvChk
    assert issubclass(ProTDslConvChk, ProTDslConv)
    assert ProTDslConvChk.extra_checks is True
    assert (ProTDslConvChk.conventions, ProTDslConvChk.convention_checks,
            ProTDslConvChk.use_profile, ProTDslConvChk.force_considered) \
        == (True, False, False, False)


def test_noplan_stage_composition_skips_planner():
    from model.pipeline.plansql import ProTDslConv, ProTDsl

    for cls in (ProTDsl, ProTDslConv):
        assert (cls.use_profile, cls.force_considered, cls.extra_checks,
                cls.convention_checks) == (False, False, False, False)
        # 阶段构成：无 PlanStage，DeclareStage 走 no-plan 模式
        inst = cls.__new__(cls)          # 绕过 __init__（不建真实 endpoint）
        inst.endpoint = object()
        names = [type(s).__name__ for s in inst._stages()]
        assert names == ["DeclareStage", "VoteStage"]
        assert inst._stages()[0].use_plan is False
