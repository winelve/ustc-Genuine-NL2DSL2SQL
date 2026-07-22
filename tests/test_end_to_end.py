"""End-to-end sanity: gold SQL evaluated against itself must score VA=EX=1.0."""

import json

import pytest

import config
from archer_eval.data import load_dataset, load_predictions
from archer_eval.evaluate import evaluate
from archer_eval.report import make_meta, write_report

pytestmark = pytest.mark.skipif(
    not config.DB_DIR.exists(),
    reason="database/ missing: unzip data/database.zip or restore from Spider (see README)",
)


@pytest.mark.parametrize("dataset", ["en_dev", "zh_dev"])
def test_gold_as_prediction_scores_perfect(dataset):
    samples = load_dataset(config.DATASETS[dataset])
    report = evaluate(samples, [s.query for s in samples], config.DB_DIR)
    failures = [d for d in report["samples"] if not d["match"]]
    assert report["summary"]["VA"] == 1.0, failures[:5]
    assert report["summary"]["EX"] == 1.0, failures[:5]
    assert report["summary"]["SIM"] == 1.0, failures[:5]


def test_wrong_prediction_scores_zero_ex():
    samples = load_dataset(config.DATASETS["en_dev"])[:3]
    preds = ["SELECT 12345 WHERE 1 = 0"] * 3
    report = evaluate(samples, preds, config.DB_DIR)
    assert report["summary"]["VA"] == 1.0
    assert report["summary"]["EX"] == 0.0


def test_empty_prediction_scores_zero_va():
    """空串是生成失败的约定值；SQLite 会把它当合法 no-op，评测必须自己拦下。"""
    samples = load_dataset(config.DATASETS["en_dev"])[:2]
    report = evaluate(samples, ["", "   "], config.DB_DIR)
    assert report["summary"]["VA"] == 0.0
    assert all(r["pred_error"] for r in report["samples"])


def test_report_records_every_sample_in_full(tmp_path):
    samples = load_dataset(config.DATASETS["en_dev"])[:3]
    preds = ["SELECT 12345 WHERE 1 = 0", "SELEC nonsense", "SELECT count(*) FROM singer"]
    report = evaluate(samples, preds, config.DB_DIR)
    report = {"meta": make_meta("en_dev", "inline", config.DB_DIR, 30.0), **report}

    path = write_report(report, tmp_path, "en_dev_test")
    assert list(tmp_path.iterdir()) == [path]  # 只出一个 json，不再有 md

    written = json.loads(path.read_text(encoding="utf-8"))
    assert set(written) == {"meta", "summary", "by_db", "by_reasoning_type", "samples"}
    for m in [written["summary"], *written["by_db"].values()]:
        assert {"VA", "EX", "SIM"} <= set(m)

    recorded = written["samples"]
    assert [r["index"] for r in recorded] == [0, 1, 2]
    for r, sample, pred in zip(recorded, samples, preds):
        assert r["question"] == sample.question
        assert r["reasoning_type"] == sample.reasoning_type  # 原始细标签，如 "- + C H"
        assert r["gold_sql"] == sample.query
        assert r["pred_sql"] == pred

    # 预测执行失败：VA=0、相似度 0，gold 未执行所以形状留空
    assert recorded[1]["valid"] is False
    assert recorded[1]["pred_error"] and recorded[1]["similarity"] == 0.0
    assert recorded[1]["pred_shape"] is None and recorded[1]["gold_shape"] is None


def test_prediction_loader(tmp_path):
    p = tmp_path / "pred.json"
    p.write_text('["SELECT 1", {"predicted_sql": "SELECT 2"}]', encoding="utf-8")
    assert load_predictions(p) == ["SELECT 1", "SELECT 2"]
