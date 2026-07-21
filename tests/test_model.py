"""Tests for the generation-side interface (model package)."""

import pytest

import config
from archer_eval.data import load_dataset
from archer_eval.evaluate import evaluate, find_db_file
from model import MODELS
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
