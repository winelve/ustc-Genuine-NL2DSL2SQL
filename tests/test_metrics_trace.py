"""Per-question generation timing and token accounting."""

from concurrent.futures import ThreadPoolExecutor

from model.metrics import question_metrics, record_api_call


def test_question_metrics_aggregates_calls_and_preserves_missing_fields():
    with question_metrics() as metrics:
        record_api_call(
            1.25,
            usage={"prompt_tokens": 10, "total_tokens": 12},
        )
        record_api_call(
            0.75,
            usage={"prompt_tokens": 20, "total_tokens": 23},
        )

    result = metrics.to_dict()
    assert result["elapsed_seconds"] >= 0
    assert result["api_calls"] == 2
    assert result["api_elapsed_seconds"] == 2.0
    assert result["usage"]["prompt_tokens"] == 30
    assert result["usage"]["total_tokens"] == 35
    assert result["usage"]["completion_tokens"] is None
    assert result["calls"][0]["usage"]["completion_tokens"] is None


def test_question_metrics_are_isolated_between_workers():
    def collect(tokens: int) -> dict:
        with question_metrics() as metrics:
            record_api_call(
                0.1,
                usage={
                    "prompt_tokens": tokens,
                    "completion_tokens": 1,
                    "total_tokens": tokens + 1,
                },
            )
        return metrics.to_dict()

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = pool.map(collect, [10, 20])

    assert left["usage"]["prompt_tokens"] == 10
    assert right["usage"]["prompt_tokens"] == 20
    assert left["api_calls"] == right["api_calls"] == 1

