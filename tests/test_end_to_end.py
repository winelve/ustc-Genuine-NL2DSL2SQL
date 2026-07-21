"""End-to-end sanity: gold SQL evaluated against itself must score VA=EX=1.0."""

import pytest

import config
from archer_eval.data import load_dataset, load_predictions
from archer_eval.evaluate import evaluate

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


def test_wrong_prediction_scores_zero_ex():
    samples = load_dataset(config.DATASETS["en_dev"])[:3]
    preds = ["SELECT 12345 WHERE 1 = 0"] * 3
    report = evaluate(samples, preds, config.DB_DIR)
    assert report["summary"]["VA"] == 1.0
    assert report["summary"]["EX"] == 0.0


def test_prediction_loader(tmp_path):
    p = tmp_path / "pred.json"
    p.write_text('["SELECT 1", {"predicted_sql": "SELECT 2"}]', encoding="utf-8")
    assert load_predictions(p) == ["SELECT 1", "SELECT 2"]
