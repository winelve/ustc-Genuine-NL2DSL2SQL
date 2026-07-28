import json
import sqlite3

from archer_eval.data import Sample


def _toy_db(tmp_path):
    path = tmp_path / "toy.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t(value INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(1,), (2,)])
    conn.commit()
    conn.close()
    return path


def test_router_skips_normalized_equal_sql_without_database(tmp_path):
    from model.selection.router import route_candidates

    decision = route_candidates(
        "SELECT 1",
        "  select   1;  ",
        tmp_path / "missing.sqlite",
    )

    assert decision.route == "same_sql"
    assert decision.winner == "dsl"
    assert decision.direct is None
    assert decision.dsl is None


def test_router_chooses_the_only_executable_candidate(tmp_path):
    from model.selection.router import route_candidates

    decision = route_candidates(
        "SELECT value FROM t",
        "SELECT nope FROM t",
        _toy_db(tmp_path),
    )

    assert decision.route == "direct_only_valid"
    assert decision.winner == "direct"
    assert decision.direct.ok is True
    assert decision.dsl.ok is False


def test_router_skips_candidates_with_equal_execution_results(tmp_path):
    from model.selection.router import route_candidates

    decision = route_candidates(
        "SELECT value FROM t ORDER BY value",
        "SELECT value FROM t ORDER BY value DESC",
        _toy_db(tmp_path),
    )

    assert decision.route == "same_result"
    assert decision.winner == "dsl"


def test_router_sends_different_results_to_pairwise(tmp_path):
    from model.selection.router import route_candidates

    decision = route_candidates(
        "SELECT value FROM t WHERE value = 1",
        "SELECT value FROM t WHERE value = 2",
        _toy_db(tmp_path),
    )

    assert decision.route == "pairwise"
    assert decision.winner is None
    assert decision.direct.n_rows == 1
    assert decision.dsl.n_cols == 1


def test_sql_normalization_does_not_emit_dialect_warnings(caplog):
    from model.selection.router import normalize_sql

    normalize_sql("SELECT GROUP_CONCAT(value ORDER BY value) FROM t")

    assert not caplog.records


def test_parse_pairwise_decision_accepts_strict_json():
    from model.selection.pairwise import parse_pairwise_reply

    decision = parse_pairwise_reply(json.dumps({
        "winner": "A",
        "confidence": "high",
        "violations_a": [],
        "violations_b": ["missing LIMIT"],
        "reason": "A matches the requested top-k.",
    }))

    assert decision.winner == "A"
    assert decision.confidence == "high"
    assert decision.violations_b == ("missing LIMIT",)


def test_parse_pairwise_decision_rejects_invalid_choice():
    import pytest

    from model.selection.pairwise import parse_pairwise_reply

    with pytest.raises(ValueError, match="winner"):
        parse_pairwise_reply(json.dumps({
            "winner": "C",
            "confidence": "high",
            "violations_a": [],
            "violations_b": [],
            "reason": "Neither.",
        }))


def test_low_confidence_pairwise_choice_falls_back_to_dsl():
    from model.selection.pairwise import resolve_pairwise_winner

    chosen = resolve_pairwise_winner(
        "A",
        "low",
        {"A": "direct", "B": "dsl"},
    )

    assert chosen == "dsl"


def test_select_all_calls_pairwise_only_for_different_results(tmp_path):
    from model.selection.runner import select_all

    db_path = _toy_db(tmp_path)
    samples = [
        Sample(db_id="toy", query="SELECT 1", question="Return one."),
        Sample(
            db_id="toy",
            query="SELECT value FROM t WHERE value = 1",
            question="Return the value one.",
            commonsense_knowledge="The requested value is exactly 1.",
        ),
    ]

    class FakeEndpoint:
        def __init__(self):
            self.messages = []

        def chat_messages(self, messages, **overrides):
            self.messages.append(messages)
            return json.dumps({
                "winner": "B",
                "confidence": "high",
                "violations_a": ["wrong filter"],
                "violations_b": [],
                "reason": "B uses the requested value.",
            })

    endpoint = FakeEndpoint()
    predictions, traces = select_all(
        samples=samples,
        db_paths=[db_path, db_path],
        direct_predictions=["SELECT 1", "SELECT value FROM t WHERE value = 1"],
        dsl_predictions=[" SELECT 1; ", "SELECT value FROM t WHERE value = 2"],
        endpoint=endpoint,
        concurrency=1,
        progress=False,
    )

    assert predictions == [" SELECT 1; ", "SELECT value FROM t WHERE value = 1"]
    assert [trace["route"] for trace in traces] == ["same_sql", "pairwise"]
    assert traces[1]["winner"] == "direct"
    assert traces[1]["candidate_mapping"] == {"A": "dsl", "B": "direct"}
    assert traces[1]["metrics"]["api_calls"] == 0
    assert len(endpoint.messages) == 1


def test_run_selection_writes_aligned_prediction_and_trace_files(tmp_path):
    from model.selection.__main__ import run_selection

    db_dir = tmp_path / "databases" / "toy"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "toy.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t(value INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()

    data_path = tmp_path / "dev.json"
    data_path.write_text(json.dumps([{
        "db_id": "toy",
        "query": "SELECT value FROM t",
        "question": "Return the value.",
        "commonsense_knowledge": "",
    }]), encoding="utf-8")
    direct_path = tmp_path / "direct.json"
    direct_path.write_text(json.dumps(["SELECT value FROM t"]), encoding="utf-8")
    dsl_path = tmp_path / "dsl.json"
    dsl_path.write_text(json.dumps([" SELECT value FROM t; "]), encoding="utf-8")
    out_path = tmp_path / "selected.json"

    predictions, traces = run_selection(
        data=str(data_path),
        direct_path=direct_path,
        dsl_path=dsl_path,
        out_path=out_path,
        db_dir=tmp_path / "databases",
        endpoint=object(),
        concurrency=1,
        progress=False,
    )

    assert predictions == [" SELECT value FROM t; "]
    assert json.loads(out_path.read_text(encoding="utf-8")) == predictions
    trace_path = tmp_path / "selected.trace.json"
    assert json.loads(trace_path.read_text(encoding="utf-8")) == traces
    assert traces[0]["route"] == "same_sql"
    assert len(traces[0]["sources"]["direct_sha256"]) == 64
