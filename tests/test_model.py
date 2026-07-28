"""Tests for the generation-side interface (model package)."""

from types import SimpleNamespace

import pytest

import config
from archer_eval.data import load_dataset
from archer_eval.evaluate import evaluate, find_db_file
from model import EXPERIMENT_MODELS, MAIN_MODELS, MODELS
from model.api import extract_sql
from model.base import SQLGenerator
from model.example import FirstTableBaseline

requires_db = pytest.mark.skipif(
    not config.DB_DIR.exists(),
    reason="database/ missing: unzip data/database.zip or restore from Spider (see README)",
)


def test_registry_names_match_classes():
    for name, cls in MODELS.items():
        assert issubclass(cls, SQLGenerator)
        assert cls.name == name


def test_final_registry_is_direct_dsl_by_fixed_fewshot_grid():
    assert set(MAIN_MODELS) == {
        "first_table",
        "pro-t-direct",
        "pro-t-direct-fs",
        "pro-t-dsl",
        "pro-t-dsl-fs",
        "bird-pro-t-direct",
        "bird-pro-t-direct-fs",
        "bird-pro-t-dsl",
        "bird-pro-t-dsl-fs",
    }
    assert MAIN_MODELS.keys().isdisjoint(EXPERIMENT_MODELS)
    assert MODELS == {**MAIN_MODELS, **EXPERIMENT_MODELS}


def test_chat_endpoint_without_key_fails_loudly(monkeypatch):
    pytest.importorskip("openai")
    from model.llm import ChatEndpoint

    monkeypatch.delenv("FAKE_KEY_ENV", raising=False)
    with pytest.raises(RuntimeError, match="FAKE_KEY_ENV"):
        ChatEndpoint(base_url="http://x", model="m", key_env="FAKE_KEY_ENV")


def test_chat_endpoint_sends_messages_and_params(monkeypatch):
    pytest.importorskip("openai")
    from model.llm import ChatEndpoint

    monkeypatch.setenv("FAKE_KEY_ENV", "sk-test")
    endpoint = ChatEndpoint(
        base_url="http://x", model="m", key_env="FAKE_KEY_ENV",
        request_params={"temperature": 0.0, "extra_body": {"a": 1}},
    )

    seen: dict = {}

    def create(**kwargs):
        seen.update(kwargs)
        message = SimpleNamespace(content="hello")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    endpoint._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    assert endpoint.chat("sys", "usr", temperature=0.7) == "hello"
    assert seen["model"] == "m"
    assert seen["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert seen["temperature"] == 0.7  # 单次调用的覆盖参数优先于 request_params
    assert seen["extra_body"] == {"a": 1}


def test_chat_endpoint_records_deepseek_usage(monkeypatch):
    pytest.importorskip("openai")
    from model.llm import ChatEndpoint
    from model.metrics import question_metrics

    monkeypatch.setenv("FAKE_KEY_ENV", "sk-test")
    endpoint = ChatEndpoint(base_url="http://x", model="m", key_env="FAKE_KEY_ENV")
    usage = SimpleNamespace(
        prompt_tokens=16,
        completion_tokens=10,
        total_tokens=26,
        prompt_cache_hit_tokens=6,
        prompt_cache_miss_tokens=10,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=4),
    )
    endpoint._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(
                        message=SimpleNamespace(content="SELECT 1")
                    )],
                    usage=usage,
                )
            )
        )
    )

    with question_metrics() as metrics:
        assert endpoint.chat("sys", "usr") == "SELECT 1"

    result = metrics.to_dict()
    assert result["api_calls"] == 1
    assert result["usage"] == {
        "prompt_tokens": 16,
        "completion_tokens": 10,
        "total_tokens": 26,
        "prompt_cache_hit_tokens": 6,
        "prompt_cache_miss_tokens": 10,
        "reasoning_tokens": 4,
    }


def test_chat_endpoint_records_failed_call_and_reraises(monkeypatch):
    pytest.importorskip("openai")
    from model.llm import ChatEndpoint
    from model.metrics import question_metrics

    monkeypatch.setenv("FAKE_KEY_ENV", "sk-test")
    endpoint = ChatEndpoint(base_url="http://x", model="m", key_env="FAKE_KEY_ENV")

    def fail(**_kwargs):
        raise TimeoutError("too slow")

    endpoint._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fail))
    )

    with question_metrics() as metrics:
        with pytest.raises(TimeoutError, match="too slow"):
            endpoint.chat("sys", "usr")

    [call] = metrics.to_dict()["calls"]
    assert call["error"] == "TimeoutError"
    assert all(value is None for value in call["usage"].values())


def test_api_model_without_key_fails_loudly(monkeypatch):
    pytest.importorskip("openai")
    from model.api import DeepSeekFlash

    monkeypatch.delenv(DeepSeekFlash.key_env, raising=False)
    with pytest.raises(RuntimeError, match=DeepSeekFlash.key_env):
        DeepSeekFlash()


def _params_sent_by(cls, monkeypatch) -> dict:
    """跑一次 predict()，返回 chat.completions.create 实际收到的关键字参数。"""
    monkeypatch.setenv(cls.key_env, "sk-test")
    generator = cls()

    seen: dict = {}

    def create(**kwargs):
        seen.update(kwargs)
        message = SimpleNamespace(content="SELECT 1")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    generator._endpoint._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    sample = load_dataset(config.DATASETS["en_dev"])[0]
    db_path = find_db_file(config.DB_DIR, sample.db_id)
    assert generator.predict(sample, db_path) == "SELECT 1"
    return seen


@requires_db
def test_flash_requests_greedy_decoding_with_thinking_off(monkeypatch):
    pytest.importorskip("openai")
    from model.api import DeepSeekFlash

    sent = _params_sent_by(DeepSeekFlash, monkeypatch)
    assert sent["model"] == "deepseek-v4-flash"
    assert sent["temperature"] == 0.0
    # DeepSeek 服务端默认开思考，开着时 temperature 被静默忽略——必须显式关掉
    assert sent["extra_body"] == {"thinking": {"type": "disabled"}}


@requires_db
def test_thinking_variant_omits_sampling_params(monkeypatch):
    pytest.importorskip("openai")
    from model.api import DeepSeekFlashThinking

    sent = _params_sent_by(DeepSeekFlashThinking, monkeypatch)
    assert sent["extra_body"] == {"thinking": {"type": "enabled"}}
    # 思考模式下采样参数不生效，发出去只会造成"结果可复现"的假象
    assert "temperature" not in sent


@requires_db
def test_example_model_end_to_end():
    samples = load_dataset(config.DATASETS["en_dev"])[:4]
    db_paths = [find_db_file(config.DB_DIR, s.db_id) for s in samples]
    generator = FirstTableBaseline()
    preds = generator.predict_all(samples, db_paths, progress=False)

    assert len(preds) == len(samples)
    assert all(isinstance(p, str) and p.upper().startswith("SELECT") for p in preds)

    report = evaluate(samples, preds, config.DB_DIR)
    assert report["summary"]["VA"] == 1.0  # trivially valid SQL


def test_predict_all_survives_a_failing_sample():
    class Broken(SQLGenerator):
        name = "broken"

        def predict(self, sample, db_path):
            raise RuntimeError("boom")

    samples = load_dataset(config.DATASETS["en_dev"])[:2]
    preds = Broken().predict_all(samples, [None, None], progress=False)
    assert preds == ["", ""]


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("SELECT name FROM singer", "SELECT name FROM singer"),
        ("```sql\nSELECT name FROM singer\n```", "SELECT name FROM singer"),
        ("```\nSELECT name FROM singer\n```", "SELECT name FROM singer"),
        ("  SELECT name FROM singer\n", "SELECT name FROM singer"),
        ("", ""),
    ],
)
def test_extract_sql(reply, expected):
    assert extract_sql(reply) == expected
