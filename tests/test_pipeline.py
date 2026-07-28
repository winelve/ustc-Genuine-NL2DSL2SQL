"""Tests for model/pipeline: templates, voting, end-to-end with a fake LLM."""

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
    """构造 plan pipeline 实例，把 LLM 调用换成 fake_chat(system, user, **kw)。"""
    pytest.importorskip("openai")
    from model.pipeline.models import ProTPlan

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
    from model.pipeline.models import ProTPlan

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


def test_runner_backfills_trace_for_resumed_checkpoint(tmp_path):
    """旧断点没有 trace 时，用模型的纯数据钩子补齐，不能重打付费 API。"""
    import json

    from model.__main__ import _checkpoint_path, _run_with_checkpoint

    sample = _sample()
    out = tmp_path / "direct-fs_en_dev.json"
    checkpoint = _checkpoint_path(out)
    checkpoint.write_text(
        "\n".join(
            (
                json.dumps({"model": "direct-fs", "data": "en_dev", "n": 1}),
                json.dumps({"i": 0, "sql": "SELECT 1", "trace": None}),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    class ResumedGenerator:
        name = "direct-fs"

        def predict_all(self, *_args, **_kwargs):
            raise AssertionError("completed checkpoint must not call the API")

        def trace_for_sample(self, got):
            assert got is sample
            return {"question": got.question, "fewshot": {"source_ids": ["train:1"]}}

    predictions, traces = _run_with_checkpoint(
        ResumedGenerator(),
        [sample],
        [tmp_path / "unused.sqlite"],
        out,
        chunk=20,
        alias="en_dev",
        total=1,
    )

    assert predictions == ["SELECT 1"]
    assert traces == [
        {"question": sample.question, "fewshot": {"source_ids": ["train:1"]}}
    ]


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
    from model.pipeline.archive import ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk

    assert (ProTPlanDslProf.use_profile, ProTPlanDslProf.force_considered, ProTPlanDslProf.extra_checks) == (True, False, False)
    assert (ProTPlanDslProfForce.use_profile, ProTPlanDslProfForce.force_considered, ProTPlanDslProfForce.extra_checks) == (True, True, False)
    assert (ProTPlanDslProfForceChk.use_profile, ProTPlanDslProfForceChk.force_considered, ProTPlanDslProfForceChk.extra_checks) == (True, True, True)


def test_m2_baseline_keeps_all_m3_switches_off():
    """pro-t-plandsl 必须与已跑出的基线结果逐位一致，否则分差不可归因。"""
    from model.pipeline.models import DSLSQL, ProTPlanDsl

    for cls in (DSLSQL, ProTPlanDsl):
        assert (cls.use_profile, cls.force_considered, cls.extra_checks) == (False, False, False)


def test_m3_variants_share_the_m2_backbone():
    """消融只动开关，骨干必须同底，否则变量不唯一。"""
    from model.pipeline.archive import (ProTPlanDslProf, ProTPlanDslProfForce,
                                        ProTPlanDslProfForceChk)
    from model.pipeline.models import ProTPlanDsl

    for cls in (ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk):
        assert cls.endpoint_spec == ProTPlanDsl.endpoint_spec
        assert cls.n_plans == ProTPlanDsl.n_plans
        assert cls.max_repairs == ProTPlanDsl.max_repairs


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
    from model.pipeline.archive import (ProTPlanDslProf, ProTPlanDslProfForce,
                                        ProTPlanDslProfForceChk)
    from model.pipeline.models import ProTPlan, ProTPlanDsl

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
    """conventions 换代后移出了 DeclareStage 基类，进了
    archive._ArchivedDeclareStage（归档档位与 models.py 的 ProTDslConv 系
    LOO 臂共用的适配层）——这条测试原本锁的是"conventions=True 时约定附录
    正确追加"这件事本身，不是锁在哪个类上，所以只换构造的类，断言不变。"""
    from model.pipeline.archive import _ArchivedDeclareStage
    from model.pipeline.conventions import CONVENTIONS
    from model.pipeline.templates import load_template

    stage = _ArchivedDeclareStage(endpoint=None, conventions=True)
    system = stage._system()
    assert system.startswith(load_template("dslgen.system"))
    for c in CONVENTIONS:
        assert f"{c.id}. " in system
    # 反投降条款必须在场：防止中性事实诱发模型放弃推理
    assert "not a valid stance" in system


def test_m3d_switch_matrix():
    """约定双臂：prose 臂只开 conventions，check 臂再开 convention_checks；
    画像/表态/C5bC6 三开关全关——约定轴与画像轴不叠加。"""
    from model.pipeline.archive import ProTPlanDslConvCchk, ProTPlanDslConv

    for cls in (ProTPlanDslConv, ProTPlanDslConvCchk):
        assert (cls.use_profile, cls.force_considered, cls.extra_checks) \
            == (False, False, False)
    assert (ProTPlanDslConv.conventions, ProTPlanDslConv.convention_checks) == (True, False)
    assert (ProTPlanDslConvCchk.conventions, ProTPlanDslConvCchk.convention_checks) == (True, True)


def test_baseline_and_m3abc_keep_conventions_off():
    from model.pipeline.archive import (ProTPlanDslProf, ProTPlanDslProfForce,
                                        ProTPlanDslProfForceChk)
    from model.pipeline.models import ProTPlanDsl

    for cls in (ProTPlanDsl, ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk):
        assert (cls.conventions, cls.convention_checks) == (False, False)


def test_noplan_variants_registered_and_single_variable():
    """no-plan 消融双臂：唯一差异 = conventions；其余开关全关（单变量红线）。"""
    from model import MODELS
    from model.pipeline.models import ProTDslConv, ProTDsl

    assert MODELS["pro-t-dsl"] is ProTDsl
    assert MODELS["pro-t-dsl-conv"] is ProTDslConv
    assert (ProTDsl.conventions, ProTDslConv.conventions) == (False, True)


def test_m3dx_noplan_adds_only_extra_checks():
    """pro-t-dsl-conv-chk = pro-t-dsl-conv + C5b/C6（建议级检查）。

    单变量：相对 pro-t-dsl-conv 唯一差异是 extra_checks；C7 保持关。"""
    from model import MODELS
    from model.pipeline.models import ProTDslConv, ProTDslConvChk

    assert MODELS["pro-t-dsl-conv-chk"] is ProTDslConvChk
    assert issubclass(ProTDslConvChk, ProTDslConv)
    assert ProTDslConvChk.extra_checks is True
    assert (ProTDslConvChk.conventions, ProTDslConvChk.convention_checks,
            ProTDslConvChk.use_profile, ProTDslConvChk.force_considered) \
        == (True, False, False, False)


def test_noplan_stage_composition_skips_planner():
    """阶段构成：无 PlanStage，DeclareStage(-家族) 走 no-plan 模式。

    ProTDslConv 走 archive._ArchivedDeclareStage（conventions=True 时的适配层），
    ProTDsl 走基类 DeclareStage——两者具体类型不同，所以用 isinstance 断言
    "恰好一个 DeclareStage 及其子类、没有 PlanStage、use_plan=False" 这个真正
    的不变量，而不是比较类名字符串（那样会漏判 _ArchivedDeclareStage）。
    """
    from model.pipeline.models import ProTDslConv, ProTDsl
    from model.pipeline.stages.declare import DeclareStage
    from model.pipeline.stages.plan import PlanStage

    for cls in (ProTDsl, ProTDslConv):
        assert (cls.use_profile, cls.force_considered, cls.extra_checks,
                cls.convention_checks) == (False, False, False, False)
        inst = cls.__new__(cls)          # 绕过 __init__（不建真实 endpoint）
        inst.endpoint = object()
        stages = inst._stages()
        assert not any(isinstance(s, PlanStage) for s in stages)
        declare = [s for s in stages if isinstance(s, DeclareStage)]
        assert len(declare) == 1 and declare[0].use_plan is False


# ------------------------------------------- 满配 leave-one-out 消融三臂

def test_loo_minus_conv_single_variable():
    """pro-t-dsl-chk = 满配 − conv：相对满配唯一差异 = conventions 关。"""
    from model import MODELS
    from model.pipeline.models import ProTDslChk, ProTDslConvChk

    assert MODELS["pro-t-dsl-chk"] is ProTDslChk
    assert (ProTDslChk.conventions, ProTDslConvChk.conventions) == (False, True)
    for attr in ("extra_checks", "convention_checks", "use_profile",
                 "force_considered", "max_repairs", "endpoint_spec", "n_plans"):
        assert getattr(ProTDslChk, attr) == getattr(ProTDslConvChk, attr), attr


def test_loo_minus_repair_single_variable():
    """pro-t-dsl-conv-chk-r0 = 满配 − 重试：唯一差异 = max_repairs 0。"""
    from model import MODELS
    from model.pipeline.models import ProTDslConvChk, ProTDslConvChkR0

    assert MODELS["pro-t-dsl-conv-chk-r0"] is ProTDslConvChkR0
    assert issubclass(ProTDslConvChkR0, ProTDslConvChk)
    assert (ProTDslConvChkR0.max_repairs, ProTDslConvChk.max_repairs) == (0, 2)
    for attr in ("conventions", "extra_checks", "convention_checks",
                 "use_profile", "force_considered", "endpoint_spec", "n_plans"):
        assert getattr(ProTDslConvChkR0, attr) == getattr(ProTDslConvChk, attr), attr


def test_loo_minus_dsl_is_direct_plus_conventions():
    """pro-t-direct-conv = 满配 − 声明层：裸直出 + 约定文本，
    相对 pro-t-direct 唯一差异 = conventions。"""
    from model import MODELS
    from model.api import DeepSeekProThinking, DeepSeekProThinkingConv

    assert MODELS["pro-t-direct-conv"] is DeepSeekProThinkingConv
    assert issubclass(DeepSeekProThinkingConv, DeepSeekProThinking)
    assert (DeepSeekProThinkingConv.conventions,
            DeepSeekProThinking.conventions) == (True, False)
    assert DeepSeekProThinkingConv.request_params == DeepSeekProThinking.request_params


def test_direct_system_byte_identical_when_conventions_off():
    """conventions=False 时直出 system 消息与基线逐字节相同，不能悄悄漂移。"""
    from model.api import SYSTEM_PROMPT, DeepSeekProThinking

    inst = DeepSeekProThinking.__new__(DeepSeekProThinking)   # 不建真实 endpoint
    assert inst._system() == SYSTEM_PROMPT


def test_direct_baseline_does_not_load_selection_or_change_prompt(monkeypatch):
    """fewshot_selection=None 时不读文件，发出的 user 消息逐字节不变。"""
    from pathlib import Path

    import model.api as api
    from model.fewshot.store import SelectionStore

    class FakeEndpoint:
        def __init__(self, **_kwargs):
            self.calls = []

        def chat(self, system, user, **overrides):
            self.calls.append((system, user, overrides))
            return "SELECT 1"

    def forbid_selection_load(cls, path):
        raise AssertionError(f"baseline touched few-shot selection: {path}")

    monkeypatch.setattr(api, "ChatEndpoint", FakeEndpoint)
    monkeypatch.setattr(api, "build_ct3_prompt", lambda _sample, _path: "BASELINE PROMPT")
    monkeypatch.setattr(SelectionStore, "from_path", classmethod(forbid_selection_load))

    generator = api.DeepSeekProThinking()
    assert generator.predict(_sample(), Path("unused.sqlite")) == "SELECT 1"
    assert generator._endpoint.calls == [
        (api.SYSTEM_PROMPT, "BASELINE PROMPT", {})
    ]


def test_direct_fewshot_loads_named_selection_and_prefixes_ct3(monkeypatch, tmp_path):
    """FS 档只从集中目录加载固定选择，并仍保持单次 API 调用。"""
    from pathlib import Path

    import config
    import model.api as api
    from model.fewshot.store import SelectionStore, sample_key
    from model.fewshot.types import FewShotExample, SelectedExample, SelectionRecord

    class FakeEndpoint:
        def __init__(self, **_kwargs):
            self.calls = []

        def chat(self, system, user, **overrides):
            self.calls.append((system, user, overrides))
            return "SELECT 1"

    sample = _sample()
    key = sample_key(sample.db_id, sample.question)
    record = SelectionRecord(
        target_key=key,
        corpus="archer_en_train",
        encoder="sentence-transformers/all-mpnet-base-v2",
        k=3,
        examples=tuple(
            SelectedExample(
                example=FewShotExample(
                    source_id=f"en_train:{index}",
                    db_id="reference_db",
                    question=f"Reference question {index}?",
                    sql=f"SELECT {index}",
                ),
                distance=float(index),
            )
            for index in range(3)
        ),
    )
    store = SelectionStore(records={key: record})
    loaded_paths = []

    def fake_from_path(cls, path):
        loaded_paths.append(path)
        return store

    def fake_build_prompt(_sample, _path, *, examples=""):
        return f"{examples}\n\nBASELINE PROMPT" if examples else "BASELINE PROMPT"

    monkeypatch.setattr(config, "FEWSHOT_DIR", tmp_path)
    monkeypatch.setattr(api, "ChatEndpoint", FakeEndpoint)
    monkeypatch.setattr(api, "build_ct3_prompt", fake_build_prompt)
    monkeypatch.setattr(SelectionStore, "from_path", classmethod(fake_from_path))

    generator = api.DeepSeekProThinkingFewShot()
    assert generator.predict(sample, Path("unused.sqlite")) == "SELECT 1"

    assert loaded_paths == [
        tmp_path / "selections" / "archer_en_dev_rsl_k3.json"
    ]
    assert len(generator._endpoint.calls) == 1
    sent = generator._endpoint.calls[0][1]
    assert sent.startswith("### Retrieved examples")
    assert sent.endswith("BASELINE PROMPT")


def test_direct_fewshot_predict_all_records_retrieval_trace(monkeypatch, tmp_path):
    """Direct FS 也必须逐题记录固定示例元数据，便于配对翻转分析。"""
    from pathlib import Path

    import model.api as api
    from model.fewshot.store import SelectionStore, sample_key
    from model.fewshot.types import FewShotExample, SelectedExample, SelectionRecord

    class FakeEndpoint:
        def chat(self, _system, _user, **_overrides):
            return "SELECT 1"

    sample = _sample()
    key = sample_key(sample.db_id, sample.question)
    record = SelectionRecord(
        target_key=key,
        corpus="archer_en_train",
        encoder="sentence-transformers/all-mpnet-base-v2",
        k=3,
        examples=tuple(
            SelectedExample(
                example=FewShotExample(
                    source_id=f"en_train:{index}",
                    db_id="reference_db",
                    question=f"Reference question {index}?",
                    sql=f"SELECT {index}",
                ),
                distance=index + 0.25,
            )
            for index in range(3)
        ),
    )
    generator = object.__new__(api.DeepSeekProThinkingFewShot)
    generator._endpoint = FakeEndpoint()
    generator._fewshot_store = SelectionStore(
        records={key: record}, corpus_sha256="b" * 64
    )
    generator.concurrency = 1
    monkeypatch.setattr(api, "build_ct3_prompt", lambda *_args, **_kwargs: "PROMPT")

    predictions = generator.predict_all(
        [sample], [Path("unused.sqlite")], progress=False
    )

    assert predictions == ["SELECT 1"]
    assert generator.trace_records == [
        {
            "question": sample.question,
            "fewshot": {
                "selection": "archer_en_dev_rsl_k3",
                "corpus": "archer_en_train",
                "corpus_sha256": "b" * 64,
                "encoder": "sentence-transformers/all-mpnet-base-v2",
                "k": 3,
                "source_ids": ["en_train:0", "en_train:1", "en_train:2"],
                "distances": [0.25, 1.25, 2.25],
            },
        }
    ]


def test_direct_fewshot_fails_when_fixed_selection_has_no_target():
    """固定选择缺题说明 artifact/数据集漂移，绝不能静默退回 baseline。"""
    from model.api import DeepSeekProThinkingFewShot
    from model.fewshot.store import SelectionStore, sample_key

    sample = _sample()
    generator = object.__new__(DeepSeekProThinkingFewShot)
    generator._fewshot_store = SelectionStore(records={})
    expected_key = sample_key(sample.db_id, sample.question)

    with pytest.raises(KeyError) as exc_info:
        generator._fewshot_examples(sample)

    message = str(exc_info.value)
    assert generator.fewshot_selection in message
    assert sample.db_id in message
    assert expected_key in message


def test_direct_fewshot_variant_is_single_variable_and_registered():
    from model import MODELS
    from model.api import DeepSeekProThinking, DeepSeekProThinkingFewShot

    assert MODELS["pro-t-direct-fs"] is DeepSeekProThinkingFewShot
    assert issubclass(DeepSeekProThinkingFewShot, DeepSeekProThinking)
    assert {
        key for key in DeepSeekProThinkingFewShot.__dict__ if not key.startswith("_")
    } == {"name", "fewshot_selection"}
    for attr in (
        "base_url",
        "model",
        "key_env",
        "request_params",
        "conventions",
    ):
        assert getattr(DeepSeekProThinkingFewShot, attr) == getattr(
            DeepSeekProThinking, attr
        ), attr


def test_direct_conv_system_carries_all_conventions():
    from model.api import SYSTEM_PROMPT, DeepSeekProThinkingConv
    from model.pipeline.conventions import CONVENTIONS

    inst = DeepSeekProThinkingConv.__new__(DeepSeekProThinkingConv)
    system = inst._system()
    assert system.startswith(SYSTEM_PROMPT)
    for c in CONVENTIONS:
        assert f"{c.id}. " in system
    # 反投降条款必须在场（同 dslgen 附录的约定）
    assert "not a valid answer" in system
    # 直出臂没有声明表，附录不得出现声明层专属词汇
    assert "Declaration" not in system and "declaration" not in system


# --------------------------------------------------------- evidence 注入口

def test_noplan_user_has_no_evidence_line_when_empty():
    """evidence 为空时整块消失——不留 "Evidence:" 空行。"""
    from model.pipeline.templates import render
    msg = render("dslgen.user.noplan", schema="S", question="Q", evidence="")
    assert "Evidence" not in msg
    assert "Q" in msg


def test_noplan_user_carries_evidence_when_present():
    from model.pipeline.templates import render
    msg = render("dslgen.user.noplan", schema="S", question="Q",
                 evidence="Evidence: eligible free rate = free / total")
    assert "eligible free rate = free / total" in msg


def test_noplan_template_dropped_profile_placeholder():
    """库画像已废，主线模板里不该再有它。"""
    from model.pipeline.templates import PLACEHOLDERS
    assert PLACEHOLDERS["dslgen.user.noplan"] == {"schema", "question", "evidence"}


def test_pipeline_context_carries_evidence():
    from pathlib import Path
    from model.pipeline.context import PipelineContext
    ctx = PipelineContext(question="Q", db_path=Path("x.sqlite"))
    assert ctx.evidence == ""
    ctx.evidence = "E"
    assert ctx.to_trace()["evidence"] == "E"


def test_dsl_fewshot_loads_fixed_selection_and_records_trace(monkeypatch, tmp_path):
    """DSL FS 在 stages 前绑定固定三例，并把可复现实验元数据写进 trace。"""
    import model.pipeline.models as pipeline_models
    from archer_eval.data import Sample
    from model.fewshot.store import SelectionStore, sample_key
    from model.fewshot.types import FewShotExample, SelectedExample, SelectionRecord
    from model.pipeline.models import ProTDslFewShot

    sample = Sample(db_id="target_db", query="SELECT 1", question="Target?")
    key = sample_key(sample.db_id, sample.question)
    record = SelectionRecord(
        target_key=key,
        corpus="archer_en_train",
        encoder="sentence-transformers/all-mpnet-base-v2",
        k=3,
        examples=tuple(
            SelectedExample(
                example=FewShotExample(
                    source_id=f"en_train:{index}",
                    db_id="reference_db",
                    question=f"Reference {index}?",
                    sql=f"SELECT {index}",
                ),
                distance=index + 0.25,
            )
            for index in range(3)
        ),
    )
    store = SelectionStore(records={key: record}, corpus_sha256="b" * 64)
    generator = ProTDslFewShot.__new__(ProTDslFewShot)
    generator._fewshot_store = store
    generator.trace_records = []
    generator.concurrency = 1
    seen_contexts = []

    class FinishStage:
        def run(self, ctx):
            seen_contexts.append(ctx)
            ctx.final_sql = "SELECT 1"

    monkeypatch.setattr(pipeline_models, "schema_with_rows", lambda _path: "SCHEMA")
    monkeypatch.setattr(generator, "_stages", lambda: [FinishStage()])

    predictions = generator.predict_all(
        [sample], [tmp_path / "target.sqlite"], progress=False
    )
    [ctx] = seen_contexts
    [trace] = generator.trace_records

    assert predictions == ["SELECT 1"]
    assert ctx.fewshot_block.startswith("### Retrieved examples")
    assert trace["fewshot"] == {
        "selection": "archer_en_dev_rsl_k3",
        "corpus": "archer_en_train",
        "corpus_sha256": "b" * 64,
        "encoder": "sentence-transformers/all-mpnet-base-v2",
        "k": 3,
        "source_ids": ["en_train:0", "en_train:1", "en_train:2"],
        "distances": [0.25, 1.25, 2.25],
    }
    assert ctx.final_sql == "SELECT 1"


def test_dsl_fewshot_preview_is_exact_initial_message_without_api(monkeypatch, tmp_path):
    """少一个 FS/证据，或混入 planner，都会让预览与正式首轮请求不一致。"""
    import model.pipeline.models as pipeline_models
    from archer_eval.data import Sample
    from model.bird import BirdProTDslFewShot
    from model.fewshot.store import SelectionStore, sample_key
    from model.fewshot.types import FewShotExample, SelectedExample, SelectionRecord

    sample = Sample(
        db_id="target_db",
        query="SELECT 1",
        question="Target question?",
        commonsense_knowledge="target evidence",
    )
    key = sample_key(sample.db_id, sample.question)
    record = SelectionRecord(
        target_key=key,
        corpus="bird_train",
        encoder="sentence-transformers/all-mpnet-base-v2",
        k=1,
        examples=(
            SelectedExample(
                example=FewShotExample(
                    source_id="bird_train:7",
                    db_id="reference_db",
                    question="Reference question?",
                    sql="SELECT reference_value",
                ),
                distance=0.25,
            ),
        ),
    )
    store = SelectionStore(records={key: record}, corpus_sha256="c" * 64)

    monkeypatch.setattr(
        SelectionStore, "from_path", classmethod(lambda cls, path: store)
    )
    monkeypatch.setattr(
        pipeline_models, "schema_with_rows", lambda _path: "CREATE TABLE target(a);"
    )
    monkeypatch.setattr(
        pipeline_models, "ChatEndpoint",
        lambda **_kwargs: pytest.fail("preview initialized the API client"),
    )

    generator = BirdProTDslFewShot.for_preview()
    messages = generator.preview_messages(sample, tmp_path / "target.sqlite")

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "Reference question?" in messages[1]["content"]
    assert "SELECT reference_value" in messages[1]["content"]
    assert "target evidence" in messages[1]["content"]
    assert "Target question?" in messages[1]["content"]
    assert "planner" not in messages[1]["content"].lower()
    assert "<planner" not in messages[1]["content"].lower()


def test_pipeline_preview_cli_prints_only_selected_models_actual_messages(
        monkeypatch, tmp_path, capsys):
    import model.pipeline.__main__ as preview_cli
    from archer_eval.data import Sample

    sample = Sample(db_id="db", query="SELECT 1", question="Q")

    class PreviewModel:
        @classmethod
        def for_preview(cls):
            return cls()

        def preview_messages(self, got_sample, db_path):
            assert got_sample is sample
            assert db_path == tmp_path / "db.sqlite"
            return [
                {"role": "system", "content": "EXACT SYSTEM"},
                {"role": "user", "content": "EXACT USER WITH FS"},
            ]

    monkeypatch.setattr(preview_cli, "MODELS", {"pro-t-dsl-fs": PreviewModel})
    monkeypatch.setattr(preview_cli, "load_dataset", lambda _path: [sample])
    monkeypatch.setattr(preview_cli, "resolve_dataset", lambda value: value)
    monkeypatch.setattr(preview_cli.config, "db_dir_for", lambda _data: tmp_path)
    monkeypatch.setattr(
        preview_cli, "find_db_file", lambda _db_dir, _db_id: tmp_path / "db.sqlite"
    )

    assert preview_cli.main([
        "--model", "pro-t-dsl-fs",
        "--data", "en_dev",
        "--preview", "0",
    ]) == 0
    output = capsys.readouterr().out
    assert "EXACT SYSTEM" in output
    assert "EXACT USER WITH FS" in output
    assert "planner system" not in output
    assert "sqlgen user" not in output
    assert "repair" not in output


def test_dsl_baseline_does_not_load_selection(monkeypatch):
    """fewshot_selection=None 是严格基线：构造时完全不碰选择文件。"""
    import model.pipeline.models as pipeline_models
    from model.fewshot.store import SelectionStore
    from model.pipeline.models import ProTDsl

    class FakeEndpoint:
        def __init__(self, **_kwargs):
            pass

    def forbid_selection_load(cls, path):
        raise AssertionError(f"baseline touched few-shot selection: {path}")

    monkeypatch.setattr(pipeline_models, "ChatEndpoint", FakeEndpoint)
    monkeypatch.setattr(SelectionStore, "from_path", classmethod(forbid_selection_load))

    generator = ProTDsl()
    assert generator._fewshot_store is None


def test_dsl_fewshot_missing_fixed_selection_fails_clearly(monkeypatch, tmp_path):
    import model.pipeline.models as pipeline_models
    from archer_eval.data import Sample
    from model.fewshot.store import SelectionStore, sample_key
    from model.pipeline.models import ProTDslFewShot

    sample = Sample(db_id="target_db", query="SELECT 1", question="Missing?")
    generator = ProTDslFewShot.__new__(ProTDslFewShot)
    generator._fewshot_store = SelectionStore(records={})
    monkeypatch.setattr(pipeline_models, "schema_with_rows", lambda _path: "SCHEMA")

    with pytest.raises(KeyError) as exc_info:
        generator._run(sample, tmp_path / "target.sqlite")

    message = str(exc_info.value)
    assert generator.fewshot_selection in message
    assert sample.db_id in message
    assert sample_key(sample.db_id, sample.question) in message


def test_dsl_fewshot_variant_is_single_variable_and_registered():
    from model import MODELS
    from model.pipeline.models import ProTDsl, ProTDslFewShot

    assert MODELS["pro-t-dsl-fs"] is ProTDslFewShot
    assert issubclass(ProTDslFewShot, ProTDsl)
    assert {
        key for key in ProTDslFewShot.__dict__ if not key.startswith("_")
    } == {"name", "fewshot_selection"}


def test_archer_arms_keep_evidence_off():
    """Archer 官方设定是 w/o knowledge（2024.eacl-long.6 §6.1）——不许开。"""
    from model.pipeline.models import (ProTDsl, ProTPlanDsl, ProTPlan)
    for cls in (ProTPlan, ProTPlanDsl, ProTDsl):
        assert getattr(cls, "evidence", False) is False


# ------------------------------------------------ 档位换代：学习式知识/规则阶梯

def test_new_arms_are_single_variable_ladder():
    """加法阶梯：每一档相对上一档只多开一个开关。"""
    from model.pipeline.models import (ProTDsl, ProTDslKnowledge,
                                       ProTDslKnowledgeRules,
                                       ProTDslKnowledgeRulesSqlens)

    def flags(cls):
        return (cls.knowledge, cls.learned_rules, cls.sqlens_checks)

    assert flags(ProTDsl) == (False, False, False)
    assert flags(ProTDslKnowledge) == (True, False, False)
    assert flags(ProTDslKnowledgeRules) == (True, True, False)
    assert flags(ProTDslKnowledgeRulesSqlens) == (True, True, True)


def test_new_arms_are_all_noplan(monkeypatch):
    """知识的阻断器是 plan 前站——新档位一律 no-plan。

    monkeypatch 打桩 API key：PlanSQL.__init__ 会立即构造真实 ChatEndpoint，
    没有密钥就抛 RuntimeError（见 tests/test_pipeline.py:113 同款打桩）。
    """
    pytest.importorskip("openai")
    from model.pipeline.models import (ProTDsl, ProTDslKnowledge,
                                       ProTDslKnowledgeRules,
                                       ProTDslKnowledgeRulesSqlens)
    from model.pipeline.stages.declare import DeclareStage

    monkeypatch.setenv(ProTDsl.endpoint_spec["key_env"], "sk-test")
    for cls in (ProTDslKnowledge, ProTDslKnowledgeRules, ProTDslKnowledgeRulesSqlens):
        stages = cls()._stages()
        declare = [s for s in stages if isinstance(s, DeclareStage)]
        assert len(declare) == 1 and declare[0].use_plan is False


def test_switch_matrix_covers_every_registered_model():
    from model import MODELS
    from model.__main__ import switch_matrix

    rows = {name for name, _ in switch_matrix()}
    assert rows == set(MODELS)


def test_archived_arms_still_instantiate(monkeypatch):
    """归档≠删除：老档位仍要能建起来并渲染消息。

    monkeypatch 打桩 API key，理由同 test_new_arms_are_all_noplan。
    """
    pytest.importorskip("openai")
    from model.pipeline.archive import (ProTPlanDslConv, ProTPlanDslConvCchk,
                                        ProTPlanDslProf, ProTPlanDslProfForce,
                                        ProTPlanDslProfForceChk)

    monkeypatch.setenv(ProTPlanDslProf.endpoint_spec["key_env"], "sk-test")
    for cls in (ProTPlanDslProf, ProTPlanDslProfForce, ProTPlanDslProfForceChk,
                ProTPlanDslConv, ProTPlanDslConvCchk):
        assert cls.name
        assert cls()._stages()


def test_conv_knowledge_probe_renders_both_appendices_in_order(monkeypatch):
    """conventions 与 knowledge 同时打开时，走 `ProTDsl._stages()` 归档分支
    渲染出的 system 仍然遵守"约定块在知识块之前"这条顺序不变量（与
    `_ArchivedDeclareStage` 直接构造时验证的是同一件事，这里额外确认走
    `_stages()` 这条真实路径也成立）。

    注意：这条测试**只**覆盖 `knowledge`（以及顺序），不覆盖
    `evidence`/`use_profile`/`force_considered`/`dataset` 的转发——那四个
    只在 `run()` 里被消费，这里从不调 `run()`；`dataset` 更是被下面
    monkeypatch 的 `load_knowledge` 完全无视。转发完整性由
    `test_archived_declare_stage_receives_every_forwarded_switch` 与
    `test_archived_dsl_stage_receives_every_forwarded_switch` 直接断言属性来锁，
    不靠这条测试的渲染结果。
    """
    from model.pipeline.models import ProTDsl
    from model.pipeline.stages import declare as declare_mod
    from model.pipeline.stages.declare import DeclareStage
    from model.pipeline.templates import load_template

    monkeypatch.setattr(declare_mod, "load_knowledge",
                        lambda *_a, **_k: [{"id": "D1", "text": "Generic rule."}])

    class _ConvKnowledgeProbe(ProTDsl):
        name = "test-only-conv-knowledge-probe"
        conventions = True
        knowledge = True

    inst = _ConvKnowledgeProbe.__new__(_ConvKnowledgeProbe)
    inst.endpoint = object()
    stages = inst._stages()
    [declare] = [s for s in stages if isinstance(s, DeclareStage)]
    system = declare._system()
    assert system.startswith(load_template("dslgen.system"))
    conventions_pos = system.index("K1.")
    knowledge_pos = system.index("D1. Generic rule.")
    assert conventions_pos < knowledge_pos


def test_archived_declare_stage_receives_every_forwarded_switch():
    """直接锁转发本身，不绕渲染/`run()`：把全部开关都设成能与默认值区分的
    非默认值，调 `ProTDsl._stages()` 拿到真正构造出来的
    `_ArchivedDeclareStage` 实例，逐个断言实例属性等于类上声明的值。

    这是修复轮 1 那条 `test_conv_knowledge_probe_renders_...`
    （原名 `test_stages_forwards_every_switch_to_archived_declare_stage`）
    的教训：它只调 `_system()`，`evidence`/`use_profile`/`force_considered`
    只在 `run()` 里被消费、`dataset` 被 monkeypatch 掉的 `load_knowledge`
    完全遮住，四个开关的转发丢了它也测不出来。断言属性本身就与"在 run() 里
    怎么被消费"无关，漏转发一个就会当场断言失败。
    """
    from model.pipeline.models import ProTDsl
    from model.pipeline.stages.declare import DeclareStage

    class _AllSwitchesProbe(ProTDsl):
        name = "test-only-all-switches-probe"
        dataset = "en_probe"
        knowledge = True
        evidence = True
        use_profile = True
        force_considered = True
        extra_checks = True
        conventions = True
        convention_checks = True

    inst = _AllSwitchesProbe.__new__(_AllSwitchesProbe)
    inst.endpoint = object()
    [declare] = [s for s in inst._stages() if isinstance(s, DeclareStage)]
    assert declare.dataset == "en_probe"
    assert declare.knowledge is True
    assert declare.evidence is True
    assert declare.use_profile is True
    assert declare.force_considered is True
    assert declare.extra_checks is True
    assert declare.conventions is True
    assert declare.convention_checks is True
    assert declare.use_plan is False   # ProTDsl 是 no-plan 档位


def test_archived_dsl_stage_receives_every_forwarded_switch():
    """同上，但站点是 `archive._ArchivedDsl._stages()`（带 plan 的归档族，
    `pro-t-plandsl-prof`/`pro-t-plandsl-conv` 系走这条）。不需要真实 API
    key——用 `__new__` 绕过 `__init__`，不触发 `ChatEndpoint` 构造。
    """
    from model.pipeline.archive import _ArchivedDsl
    from model.pipeline.stages.declare import DeclareStage

    class _AllSwitchesProbe(_ArchivedDsl):
        name = "test-only-all-switches-probe-2"
        dataset = "en_probe"
        knowledge = True
        evidence = True
        use_profile = True
        force_considered = True
        extra_checks = True
        conventions = True
        convention_checks = True
        # _ArchivedDsl 经 DSLSQL/ProTPlanDsl 继承到 PlanSQL.use_plan = True，
        # 与 _ArchivedDeclareStage.__init__ 的默认值 True 重合——不显式覆写成
        # False，下面 use_plan 那条断言就是空转的（删掉 archive.py 里的
        # use_plan=self.use_plan 转发，这条测试照样绿）。
        use_plan = False

    inst = _AllSwitchesProbe.__new__(_AllSwitchesProbe)
    inst.endpoint = object()
    [declare] = [s for s in inst._stages() if isinstance(s, DeclareStage)]
    assert declare.dataset == "en_probe"
    assert declare.knowledge is True
    assert declare.evidence is True
    assert declare.use_profile is True
    assert declare.force_considered is True
    assert declare.extra_checks is True
    assert declare.conventions is True
    assert declare.convention_checks is True
    assert declare.use_plan is False
