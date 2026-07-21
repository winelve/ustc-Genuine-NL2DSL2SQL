"""End-to-end sanity: gold SQL evaluated against itself must score VA=EX=1.0."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from archer_eval.data import load_dataset, load_predictions
from archer_eval.evaluate import evaluate

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("data_file", ["data/en_data/dev.json", "data/zh_data/dev.json"])
def test_gold_as_prediction_scores_perfect(data_file):
    samples = load_dataset(ROOT / data_file)
    report = evaluate(samples, [s.query for s in samples], ROOT / "database")
    failures = [d for d in report["samples"] if not d["match"]]
    assert report["summary"]["VA"] == 1.0, failures[:5]
    assert report["summary"]["EX"] == 1.0, failures[:5]


def test_wrong_prediction_scores_zero_ex():
    samples = load_dataset(ROOT / "data/en_data/dev.json")[:3]
    preds = ["SELECT 12345 WHERE 1 = 0"] * 3
    report = evaluate(samples, preds, ROOT / "database")
    assert report["summary"]["VA"] == 1.0
    assert report["summary"]["EX"] == 0.0


def test_prediction_loader(tmp_path):
    p = tmp_path / "pred.json"
    p.write_text('["SELECT 1", {"predicted_sql": "SELECT 2"}]', encoding="utf-8")
    assert load_predictions(p) == ["SELECT 1", "SELECT 2"]
