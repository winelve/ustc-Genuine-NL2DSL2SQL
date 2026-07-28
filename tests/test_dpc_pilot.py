import json

import pandas as pd
import pytest

from archer_eval.data import Sample
from model.dpc_pilot.prepare import (
    build_pilot_manifest,
    merge_dpc_results,
)
from model.dpc_pilot import runner as dpc_runner
from model.dpc_pilot.runner import DeterministicSlicer
from model.dpc_pilot.safe_executor import SafePythonExecutor


def _sample(index: int, difficulty: str) -> Sample:
    return Sample(
        db_id=f"db_{index % 2}",
        question=f"question {index}",
        query=f"gold {index}",
        commonsense_knowledge=f"evidence {index}",
        extras={"question_id": 100 + index, "difficulty": difficulty},
    )


def test_manifest_uses_only_pairwise_routes_and_puts_dsl_first():
    samples = [
        _sample(0, "simple"),
        _sample(1, "simple"),
        _sample(2, "moderate"),
        _sample(3, "challenging"),
    ]
    routes = [
        {"route": "pairwise"},
        {"route": "same_result"},
        {"route": "pairwise"},
        {"route": "pairwise"},
    ]

    manifest = build_pilot_manifest(
        samples=samples,
        routes=routes,
        direct_predictions=["d0", "d1", "d2", "d3"],
        dsl_predictions=["s0", "s1", "s2", "s3"],
        size=3,
        seed="fixed",
        sources={"dataset_sha256": "dataset"},
    )

    assert [record["index"] for record in manifest["records"]] == [0, 2, 3]
    assert manifest["candidate_map"] == {
        "100": ["s0", "d0"],
        "102": ["s2", "d2"],
        "103": ["s3", "d3"],
    }


def test_manifest_sampling_is_stable_and_stratified():
    samples = [
        *[_sample(i, "simple") for i in range(6)],
        *[_sample(i + 6, "moderate") for i in range(3)],
        _sample(9, "challenging"),
    ]
    routes = [{"route": "pairwise"} for _ in samples]
    kwargs = dict(
        samples=samples,
        routes=routes,
        direct_predictions=[f"d{i}" for i in range(10)],
        dsl_predictions=[f"s{i}" for i in range(10)],
        size=5,
        seed="pilot-v1",
        sources={},
    )

    first = build_pilot_manifest(**kwargs)
    second = build_pilot_manifest(**kwargs)

    assert first == second
    difficulties = [record["difficulty"] for record in first["records"]]
    assert difficulties.count("simple") == 3
    assert difficulties.count("moderate") == 1
    assert difficulties.count("challenging") == 1


def test_merge_dpc_results_changes_only_pilot_indices():
    baseline = ["s0", "s1", "s2", "s3"]
    manifest = {
        "records": [
            {"index": 1, "question_id": "101", "candidates": ["s1", "d1"]},
            {"index": 3, "question_id": "103", "candidates": ["s3", "d3"]},
        ]
    }
    completed = {
        "101": {"selected_sql": "d1"},
        "103": {"selected_sql": "s3"},
    }

    assert merge_dpc_results(baseline, manifest, completed) == [
        "s0",
        "d1",
        "s2",
        "s3",
    ]


def test_merge_rejects_sql_outside_the_two_candidates():
    manifest = {
        "records": [
            {"index": 0, "question_id": "100", "candidates": ["s0", "d0"]},
        ]
    }
    with pytest.raises(ValueError, match="not one of the fixed candidates"):
        merge_dpc_results(
            ["s0"],
            manifest,
            {"100": {"selected_sql": "gold leaked"}},
        )


def test_deterministic_slicer_keeps_physical_tables_not_cte_aliases():
    schema = {
        "customers": object(),
        "orders": object(),
        "unrelated": object(),
    }
    slicer = DeterministicSlicer(llm=object())

    sliced = slicer.run(
        candidate_sqls=[
            "WITH recent AS (SELECT customer_id FROM orders) "
            "SELECT c.name FROM customers AS c "
            "JOIN recent AS r ON r.customer_id = c.id",
        ],
        full_schema=schema,
    )

    assert list(sliced) == ["customers", "orders"]


def test_safe_executor_runs_normal_pandas_code():
    result = SafePythonExecutor.execute(
        {"sales": [{"amount": 2}, {"amount": 3}]},
        "result = pd.DataFrame({'total': [sales['amount'].sum()]})",
        timeout=5,
    )

    assert isinstance(result, pd.DataFrame)
    assert result.to_dict(orient="records") == [{"total": 5}]


def test_safe_executor_allows_pure_helper_and_redundant_pandas_import():
    result = SafePythonExecutor.execute(
        {"sales": [{"amount": 2}, {"amount": 3}]},
        """
import pandas as pd

def summarize(frame):
    return pd.DataFrame({"total": [frame["amount"].sum()]})

result = summarize(sales)
""",
        timeout=5,
    )

    assert isinstance(result, pd.DataFrame)
    assert result.to_dict(orient="records") == [{"total": 5}]


@pytest.mark.parametrize(
    "code",
    [
        "import os\nresult = pd.DataFrame()",
        "result = pd.read_csv('secret.csv')",
        "result = sales.__class__",
        "result = open('secret.txt').read()",
    ],
)
def test_safe_executor_rejects_code_with_external_access(code):
    result = SafePythonExecutor.execute(
        {"sales": [{"amount": 2}]},
        code,
        timeout=5,
    )

    assert isinstance(result, str)
    assert result.startswith("Error: Unsafe generated Python:")


def test_solver_messages_receive_the_safe_execution_contract():
    original = [
        {
            "role": "system",
            "content": (
                "You are a Python data scientist expert in Pandas. "
                "Write a solution."
            ),
        },
        {"role": "user", "content": "question"},
    ]

    adjusted = dpc_runner.apply_solver_execution_contract(original)

    assert adjusted is not original
    assert "Do not import modules" in adjusted[0]["content"]
    assert "pure helper functions" in adjusted[0]["content"]
    assert "Do not import modules" not in original[0]["content"]


def test_metrics_use_llm_owned_calls_from_official_worker_threads():
    class RecordedLlm:
        def get_usage(self):
            return {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
                "prompt_cache_hit_tokens": 20,
                "prompt_cache_miss_tokens": 100,
                "reasoning_tokens": 0,
            }

        def get_calls(self):
            return [
                {
                    "elapsed_seconds": 1.25,
                    "usage": {
                        "prompt_tokens": 120,
                        "completion_tokens": 30,
                        "total_tokens": 150,
                        "prompt_cache_hit_tokens": 20,
                        "prompt_cache_miss_tokens": 100,
                        "reasoning_tokens": 0,
                    },
                }
            ]

    metrics = dpc_runner.metrics_with_llm_calls(
        {
            "elapsed_seconds": 2.0,
            "api_calls": 0,
            "api_elapsed_seconds": 0.0,
            "usage": {field: None for field in dpc_runner.TOKEN_FIELDS},
            "calls": [],
        },
        RecordedLlm(),
    )

    assert metrics["elapsed_seconds"] == 2.0
    assert metrics["api_calls"] == 1
    assert metrics["api_elapsed_seconds"] == 1.25
    assert metrics["usage"]["total_tokens"] == 150
    assert metrics["calls"][0]["usage"]["prompt_tokens"] == 120


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("Challenger Won Duel (Votes: 1/1)", "ok"),
        ("Champion Retained (Votes: 1/1)", "ok"),
        ("Verification Error (All Data Failed)", "fallback"),
        ("Slicer Error: bad schema", "fallback"),
        ("No Challenger", "no_duel"),
    ],
)
def test_pipeline_status_exposes_internal_fallbacks(reason, expected):
    assert dpc_runner.classify_pipeline_status(reason) == expected


def test_old_checkpoint_records_are_rerun_after_accounting_fix():
    records = [
        {"question_id": "1"},
        {"question_id": "2"},
        {"question_id": "3"},
    ]
    completed = {
        "1": {"status": "ok"},
        "2": {"run_format": "bird-dpc-run-v2", "status": "ok"},
    }

    pending = dpc_runner.pending_records(records, completed)

    assert [record["question_id"] for record in pending] == ["1", "3"]


@pytest.mark.skipif(
    not (
        dpc_runner.DEFAULT_OFFICIAL_ROOT
        / "dpc"
        / "core"
        / "pipeline.py"
    ).exists(),
    reason="official DPC bootstrap checkout is not available",
)
def test_offline_self_test_runs_real_dpc_pipeline_without_api_key(
    monkeypatch,
):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = dpc_runner.run_offline_self_test()

    assert result["winner"] == "direct"
    assert result["selection_reason"].startswith("Challenger Won Duel")
    assert result["scripted_calls"] == 2
