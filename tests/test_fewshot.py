"""Few-shot retrieval 基础数据契约测试。"""

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

import config
from model.fewshot.types import FewShotExample, SelectedExample, SelectionRecord


def _record_with_three_examples() -> SelectionRecord:
    return SelectionRecord(
        target_key="target-key",
        corpus="archer_en_train",
        encoder="sentence-transformers/all-mpnet-base-v2",
        k=3,
        examples=tuple(
            SelectedExample(
                example=FewShotExample(
                    source_id=f"en_train:{index}",
                    db_id="bike_1",
                    question=f"Reference question {index}?",
                    sql=f"SELECT {index}",
                ),
                distance=float(index),
            )
            for index in range(3)
        ),
    )


def _selection_payload(
    *, examples: list[dict] | None = None, k: int = 3, example_count: int | None = None
) -> dict:
    example_count = k if example_count is None else example_count
    examples = examples or [
        {
            "source_id": f"en_train:{index}",
            "db_id": "bike_1",
            "question": f"Reference question {index}?",
            "sql": f"SELECT {index}",
            "distance": float(index),
        }
        for index in range(example_count)
    ]
    return {
        "format_version": 1,
        "corpus": "archer_en_train",
        "corpus_sha256": "a" * 64,
        "encoder": "sentence-transformers/all-mpnet-base-v2",
        "k": k,
        "records": [{"target_key": "target-key", "examples": examples}],
    }


def test_fewshot_contract_and_path():
    """下游能消费稳定、不可变的离线选择记录和集中数据目录。"""
    example = FewShotExample(
        source_id="en_train:7",
        db_id="bike_1",
        question="How many docks are unavailable?",
        sql="SELECT 1",
    )
    selected = SelectedExample(example=example, distance=0.25)
    record = SelectionRecord(
        target_key="abc",
        corpus="archer_en_train",
        encoder="sentence-transformers/all-mpnet-base-v2",
        k=3,
        examples=(selected,),
    )

    assert record.examples[0].example.source_id == "en_train:7"
    assert config.FEWSHOT_DIR.name == "fewshot"
    with pytest.raises(FrozenInstanceError):
        example.sql = "SELECT 2"


def test_sql_structure_features_ignore_identifiers_and_literals():
    from model.fewshot.structure import sql_structure_features

    left = sql_structure_features(
        "SELECT customer_id FROM orders WHERE amount > 10"
    )
    right = sql_structure_features(
        "SELECT student_id FROM grades WHERE score > 90"
    )

    assert left
    assert left == right


def test_sql_structure_features_distinguish_grouped_aggregation():
    from model.fewshot.structure import sql_structure_features

    plain = sql_structure_features("SELECT city FROM people")
    grouped = sql_structure_features(
        "SELECT city, COUNT(*) FROM people GROUP BY city"
    )

    assert grouped["clause:group"] == 1
    assert grouped["aggregate:count"] == 1
    assert grouped["projection_count"] == 2
    assert plain != grouped


def test_sql_structure_features_cover_join_nesting_set_order_and_limit():
    from model.fewshot.structure import sql_structure_features

    features = sql_structure_features(
        """
        SELECT a.id
        FROM a JOIN b ON a.id = b.a_id
        WHERE a.id IN (SELECT c.a_id FROM c)
        UNION
        SELECT d.id FROM d
        ORDER BY id
        LIMIT 5
        """
    )

    assert features["join:inner"] == 1
    assert features["subquery"] >= 1
    assert features["setop:union"] == 1
    assert features["clause:order"] == 1
    assert features["clause:limit"] == 1


def test_sql_structure_features_invalid_sql_is_empty():
    from model.fewshot.structure import sql_structure_features

    assert not sql_structure_features("")
    assert not sql_structure_features("SELECT FROM WHERE")


def test_sql_structure_features_accept_sqlite_backtick_identifiers():
    from model.fewshot.structure import sql_structure_features

    features = sql_structure_features(
        "SELECT `Name` FROM `country` WHERE `LifeExpectancy` >= 1.5 * "
        "(SELECT `LifeExpectancy` FROM `country` WHERE `Name` = 'Zambia')"
    )

    assert features["query:select"] == 2
    assert features["subquery"] == 1


def test_multiset_jaccard_counts_feature_multiplicity():
    from collections import Counter

    from model.fewshot.structure import multiset_jaccard

    assert multiset_jaccard(Counter({"join": 2}), Counter({"join": 1})) == 0.5
    assert multiset_jaccard(Counter(), Counter()) == 0.0


def test_rank_fusion_combines_semantic_and_structure_ranks():
    from model.fewshot.structure import rank_fusion

    fused = rank_fusion(
        ("semantic-first", "balanced", "structure-first"),
        {
            "semantic-first": 0.1,
            "balanced": 1.0,
            "structure-first": 0.8,
        },
    )

    assert [candidate.source_id for candidate in fused] == [
        "balanced",
        "semantic-first",
        "structure-first",
    ]
    assert fused[0].semantic_rank == 2
    assert fused[0].structure_rank == 1


def test_rank_fusion_all_structure_ties_preserve_semantic_order():
    from model.fewshot.structure import rank_fusion

    semantic_order = ("z", "a", "m")
    fused = rank_fusion(
        semantic_order,
        {source_id: 0.0 for source_id in semantic_order},
    )

    assert [candidate.source_id for candidate in fused] == list(semantic_order)
    assert [candidate.structure_rank for candidate in fused] == [1, 2, 3]


def test_rank_fusion_is_deterministic_and_validates_inputs():
    from model.fewshot.structure import rank_fusion

    semantic_order = ("b", "a", "c")
    scores = {"b": 0.4, "a": 0.9, "c": 0.4}

    assert rank_fusion(semantic_order, scores) == rank_fusion(
        semantic_order, scores
    )
    with pytest.raises(ValueError, match="semantic_weight"):
        rank_fusion(semantic_order, scores, semantic_weight=1.1)
    with pytest.raises(ValueError, match="same source IDs"):
        rank_fusion(semantic_order, {"b": 0.4, "a": 0.9})
    with pytest.raises(ValueError, match="unique"):
        rank_fusion(("a", "a"), {"a": 0.4})


def _write_sfs_inputs(
    tmp_path: Path,
    *,
    target_rows: list[dict] | None = None,
    predictions: list | None = None,
    candidate_count: int = 4,
) -> tuple[Path, Path, Path]:
    from model.fewshot.store import sample_key

    target_rows = target_rows or [
        {"db_id": "target_db", "question": "Count rows by category.", "query": "SELECT 1"}
    ]
    predictions = predictions or [
        "SELECT category, COUNT(*) FROM target_table GROUP BY category"
    ]
    candidate_sql = [
        "SELECT name FROM people",
        "SELECT name FROM people WHERE age > 10",
        "SELECT city, COUNT(*) FROM people GROUP BY city",
        "SELECT COUNT(*) FROM people",
    ]
    examples = [
        {
            "source_id": f"en_train:{index}",
            "db_id": "train_db",
            "question": f"Training question {index}",
            "sql": candidate_sql[index % len(candidate_sql)],
            "distance": float(index) / 10,
        }
        for index in range(candidate_count)
    ]
    unique_target_keys = list(
        dict.fromkeys(
            sample_key(row["db_id"], row["question"]) for row in target_rows
        )
    )
    selection = {
        "format_version": 1,
        "corpus": "archer_en_train",
        "corpus_sha256": "c" * 64,
        "encoder": "sentence-transformers/all-mpnet-base-v2",
        "k": candidate_count,
        "records": [
            {"target_key": target_key, "examples": examples}
            for target_key in unique_target_keys
        ],
    }
    selection_path = tmp_path / "semantic.json"
    targets_path = tmp_path / "targets.json"
    predictions_path = tmp_path / "predictions.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    targets_path.write_text(json.dumps(target_rows), encoding="utf-8")
    predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
    return selection_path, targets_path, predictions_path


def test_build_sfs_selection_reranks_and_records_provenance(tmp_path):
    from model.fewshot.offline import build_sfs_selection

    selection_path, targets_path, predictions_path = _write_sfs_inputs(tmp_path)
    output_path = tmp_path / "sfs.json"

    payload = build_sfs_selection(
        semantic_selection_path=selection_path,
        targets_path=targets_path,
        draft_predictions_path=predictions_path,
        output_path=output_path,
        candidate_k=4,
        k=2,
    )

    examples = payload["records"][0]["examples"]
    assert [example["source_id"] for example in examples] == [
        "en_train:0",
        "en_train:2",
    ]
    assert examples[1]["semantic_rank"] == 3
    assert examples[1]["structure_rank"] == 1
    assert examples[1]["structure_similarity"] > 0
    assert 0 <= examples[1]["fusion_score"] <= 1
    assert {
        key: payload["retrieval"][key]
        for key in (
            "candidate_k",
            "draft_predictions_sha256",
            "fallback_count",
            "semantic_selection_sha256",
            "semantic_weight",
            "strategy",
            "structure_features",
            "structure_weight",
            "targets_sha256",
        )
    } == {
        "candidate_k": 4,
        "draft_predictions_sha256": hashlib.sha256(
            predictions_path.read_bytes()
        ).hexdigest(),
        "fallback_count": 0,
        "semantic_selection_sha256": hashlib.sha256(
            selection_path.read_bytes()
        ).hexdigest(),
        "semantic_weight": 0.5,
        "strategy": "sfs-v1",
        "structure_features": "sqlglot-multiset-v1",
        "structure_weight": 0.5,
        "targets_sha256": hashlib.sha256(targets_path.read_bytes()).hexdigest(),
    }
    assert (
        payload["retrieval"]["mean_structure_similarity_sfs_top_k"]
        >= payload["retrieval"]["mean_structure_similarity_semantic_top_k"]
    )


def test_build_sfs_selection_invalid_draft_falls_back_to_semantic_order(tmp_path):
    from model.fewshot.offline import build_sfs_selection

    selection_path, targets_path, predictions_path = _write_sfs_inputs(
        tmp_path,
        predictions=["SELECT FROM WHERE"],
    )
    payload = build_sfs_selection(
        semantic_selection_path=selection_path,
        targets_path=targets_path,
        draft_predictions_path=predictions_path,
        output_path=tmp_path / "sfs.json",
        candidate_k=4,
        k=3,
    )

    assert [
        example["source_id"] for example in payload["records"][0]["examples"]
    ] == ["en_train:0", "en_train:1", "en_train:2"]
    assert payload["retrieval"]["fallback_count"] == 1


def test_build_sfs_selection_is_byte_deterministic(tmp_path):
    from model.fewshot.offline import build_sfs_selection

    selection_path, targets_path, predictions_path = _write_sfs_inputs(tmp_path)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    kwargs = {
        "semantic_selection_path": selection_path,
        "targets_path": targets_path,
        "draft_predictions_path": predictions_path,
        "candidate_k": 4,
        "k": 2,
    }

    build_sfs_selection(output_path=first, **kwargs)
    build_sfs_selection(output_path=second, **kwargs)

    assert first.read_bytes() == second.read_bytes()


def test_build_sfs_selection_validates_alignment_pool_and_duplicate_drafts(tmp_path):
    from model.fewshot.offline import build_sfs_selection

    selection_path, targets_path, predictions_path = _write_sfs_inputs(tmp_path)
    predictions_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="prediction count"):
        build_sfs_selection(
            semantic_selection_path=selection_path,
            targets_path=targets_path,
            draft_predictions_path=predictions_path,
            output_path=tmp_path / "missing.json",
            candidate_k=4,
            k=2,
        )

    selection_path, targets_path, predictions_path = _write_sfs_inputs(
        tmp_path,
        candidate_count=3,
    )
    with pytest.raises(ValueError, match="fewer than candidate_k"):
        build_sfs_selection(
            semantic_selection_path=selection_path,
            targets_path=targets_path,
            draft_predictions_path=predictions_path,
            output_path=tmp_path / "short.json",
            candidate_k=4,
            k=2,
        )

    duplicate_targets = [
        {"db_id": "db", "question": "same", "query": "SELECT 1"},
        {"db_id": "db", "question": "same", "query": "SELECT 1"},
    ]
    selection_path, targets_path, predictions_path = _write_sfs_inputs(
        tmp_path,
        target_rows=duplicate_targets,
        predictions=["SELECT 1", "SELECT 2"],
    )
    with pytest.raises(ValueError, match="conflicting draft SQL"):
        build_sfs_selection(
            semantic_selection_path=selection_path,
            targets_path=targets_path,
            draft_predictions_path=predictions_path,
            output_path=tmp_path / "conflict.json",
            candidate_k=4,
            k=2,
        )


def test_rerank_sfs_cli_builds_artifact_and_reports_fallbacks(
    tmp_path, capsys
):
    from model.fewshot import offline

    selection_path, targets_path, predictions_path = _write_sfs_inputs(tmp_path)
    output_path = tmp_path / "sfs.json"

    assert offline.main(
        [
            "rerank-sfs",
            "--selection",
            str(selection_path),
            "--targets",
            str(targets_path),
            "--draft-predictions",
            str(predictions_path),
            "--output",
            str(output_path),
            "--candidate-k",
            "4",
            "--k",
            "2",
        ]
    ) == 0

    output = capsys.readouterr().out
    assert "1 unique records" in output
    assert "fallbacks=0" in output
    assert "semantic selection sha256:" in output
    assert "targets sha256:" in output
    assert output_path.exists()


def test_retrieval_dependency_manifest_targets_cpu_python_311_or_312():
    """Torch 2.5.1 的 Windows CPU wheel 必须从官方索引、独立兼容解释器取得。"""
    manifest = (Path(config.ROOT) / "requirements-fewshot.txt").read_text(encoding="utf-8")

    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in manifest
    assert "Python 3.11/3.12" in manifest


def test_retrieval_manifest_pins_transformers_compatible_with_torch_251():
    """本地可信 .bin 模型必须避开要求 Torch 2.6 的新版 Transformers。"""
    manifest = (Path(config.ROOT) / "requirements-fewshot.txt").read_text(encoding="utf-8")

    assert "transformers==4.46.3" in manifest.splitlines()


def test_retrieval_manifest_includes_sfs_parser_dependency():
    manifest = (Path(config.ROOT) / "requirements-fewshot.txt").read_text(
        encoding="utf-8"
    )

    assert "sqlglot==30.13.0" in manifest.splitlines()


def test_sample_key_is_stable_and_question_sensitive():
    from model.fewshot.store import sample_key

    assert sample_key("db", " Question?\n") == sample_key("db", "Question?")
    assert sample_key("db", "Question?\r\n") == sample_key("db", "Question?\n")
    assert sample_key("db", "Question?") != sample_key("db", "Other?")


def test_render_reference_examples_is_explicitly_non_output_format():
    from model.fewshot.render import render_reference_examples

    block = render_reference_examples(_record_with_three_examples())

    assert block.startswith(
        "### Retrieved examples (SQL semantic references only; they do not "
        "define the target output format)\n\n"
    )
    assert block.count("Reference question:") == 3
    assert "Reference SQL: SELECT" in block


def test_empty_selection_preserves_empty_prefix():
    from model.fewshot.render import render_reference_examples

    assert render_reference_examples(None) == ""


def test_ct3_prompt_without_examples_is_byte_identical(monkeypatch):
    """默认参数必须保留原 CT-3 user 消息的每一个字节。"""
    from archer_eval.data import Sample
    from model import prompts

    monkeypatch.setattr(prompts, "schema_with_rows", lambda _path: "CREATE TABLE t (a INT);")
    sample = Sample(db_id="toy", query="SELECT a FROM t", question="Return every a.")

    assert prompts.build_ct3_prompt(sample, Path("unused.sqlite")) == (
        "CREATE TABLE t (a INT);\n\n"
        "-- Using valid SQLite, answer the following questions for the tables provided above.\n"
        "-- Return every a.\n"
        "SELECT"
    )


def test_ct3_fewshot_prefix_is_before_target_schema(monkeypatch):
    """检索例只作前缀；目标 schema/题面仍保持原 CT-3 格式。"""
    from archer_eval.data import Sample
    from model import prompts

    monkeypatch.setattr(prompts, "schema_with_rows", lambda _path: "CREATE TABLE t (a INT);")
    sample = Sample(db_id="toy", query="SELECT a FROM t", question="Return every a.")

    prompt = prompts.build_ct3_prompt(
        sample, Path("unused.sqlite"), examples="EXAMPLE BLOCK"
    )

    assert prompt.startswith("EXAMPLE BLOCK\n\n")
    assert prompt.index("EXAMPLE BLOCK") < prompt.index("CREATE TABLE")
    assert prompt.endswith("-- Return every a.\nSELECT")


def test_selection_store_round_trip_and_lookup(tmp_path):
    from model.fewshot.store import SelectionStore, sample_key

    path = tmp_path / "selection.json"
    payload = _selection_payload()
    payload["records"][0]["target_key"] = sample_key("bike_1", "Target question?\n")
    path.write_text(json.dumps(payload), encoding="utf-8")

    store = SelectionStore.from_path(path)

    record = store.for_sample("bike_1", " Target question? ")
    assert record is not None
    assert record.corpus == "archer_en_train"
    assert record.encoder == "sentence-transformers/all-mpnet-base-v2"
    assert record.k == 3
    assert record.examples[2].example.source_id == "en_train:2"
    assert record.examples[2].distance == 2.0
    assert store.corpus_sha256 == "a" * 64
    assert store.for_sample("bike_1", "missing") is None


def test_selection_store_loads_sfs_metadata_and_example_scores(tmp_path):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "sfs-selection.json"
    payload = _selection_payload()
    payload["retrieval"] = {
        "strategy": "sfs-v1",
        "structure_features": "sqlglot-multiset-v1",
        "semantic_selection_sha256": "b" * 64,
        "draft_predictions_sha256": "d" * 64,
        "targets_sha256": "e" * 64,
        "candidate_k": 30,
        "semantic_weight": 0.5,
        "structure_weight": 0.5,
        "fallback_count": 0,
    }
    for rank, example in enumerate(payload["records"][0]["examples"], start=1):
        example.update(
            {
                "semantic_rank": rank,
                "structure_rank": 4 - rank,
                "structure_similarity": rank / 4,
                "fusion_score": 1 - rank / 10,
            }
        )
    path.write_text(json.dumps(payload), encoding="utf-8")

    store = SelectionStore.from_path(path)
    selected = store.records["target-key"].examples[0]

    assert dict(store.retrieval) == payload["retrieval"]
    assert selected.semantic_rank == 1
    assert selected.structure_rank == 3
    assert selected.structure_similarity == 0.25
    assert selected.fusion_score == 0.9


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("semantic_rank", 0, "positive integer semantic_rank"),
        ("structure_rank", True, "positive integer structure_rank"),
        ("structure_similarity", float("nan"), "finite structure_similarity"),
        ("fusion_score", 1.5, "fusion_score.*within"),
    ],
)
def test_selection_store_rejects_invalid_sfs_example_scores(
    tmp_path, field, value, message
):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "invalid-sfs.json"
    payload = _selection_payload()
    payload["retrieval"] = {
        "strategy": "sfs-v1",
        "structure_features": "sqlglot-multiset-v1",
        "semantic_selection_sha256": "b" * 64,
        "draft_predictions_sha256": "d" * 64,
        "targets_sha256": "e" * 64,
        "candidate_k": 30,
        "semantic_weight": 0.5,
        "structure_weight": 0.5,
        "fallback_count": 0,
    }
    for rank, example in enumerate(payload["records"][0]["examples"], start=1):
        example.update(
            {
                "semantic_rank": rank,
                "structure_rank": rank,
                "structure_similarity": 0.5,
                "fusion_score": 0.5,
            }
        )
    payload["records"][0]["examples"][0][field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        SelectionStore.from_path(path)


def test_selection_store_rejects_unknown_retrieval_strategy(tmp_path):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "unknown-strategy.json"
    payload = _selection_payload()
    payload["retrieval"] = {"strategy": "future-sfs"}
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported retrieval strategy"):
        SelectionStore.from_path(path)


def test_selection_store_rejects_sfs_rank_outside_candidate_pool(tmp_path):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "invalid-rank.json"
    payload = _selection_payload()
    payload["retrieval"] = {
        "strategy": "sfs-v1",
        "structure_features": "sqlglot-multiset-v1",
        "semantic_selection_sha256": "b" * 64,
        "draft_predictions_sha256": "d" * 64,
        "targets_sha256": "e" * 64,
        "candidate_k": 3,
        "semantic_weight": 0.5,
        "structure_weight": 0.5,
        "fallback_count": 0,
    }
    for rank, example in enumerate(payload["records"][0]["examples"], start=1):
        example.update(
            {
                "semantic_rank": rank,
                "structure_rank": rank,
                "structure_similarity": 0.5,
                "fusion_score": 0.5,
            }
        )
    payload["records"][0]["examples"][0]["semantic_rank"] = 4
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="semantic_rank.*candidate_k"):
        SelectionStore.from_path(path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_selection_payload(k=2, example_count=3), "exactly k examples"),
        (
            _selection_payload(
                examples=[
                    {
                        "source_id": "en_train:0",
                        "db_id": "bike_1",
                        "question": "Question one?",
                        "sql": "SELECT 1",
                        "distance": 0.1,
                    },
                    {
                        "source_id": "en_train:0",
                        "db_id": "bike_1",
                        "question": "Question two?",
                        "sql": "SELECT 2",
                        "distance": 0.2,
                    },
                    {
                        "source_id": "en_train:2",
                        "db_id": "bike_1",
                        "question": "Question three?",
                        "sql": "SELECT 3",
                        "distance": 0.3,
                    },
                ]
            ),
            "duplicate source_id",
        ),
        (
            _selection_payload(
                examples=[
                    {
                        "source_id": "en_train:0",
                        "db_id": "bike_1",
                        "question": "Question one?",
                        "sql": "   ",
                        "distance": 0.1,
                    },
                    {
                        "source_id": "en_train:1",
                        "db_id": "bike_1",
                        "question": "Question two?",
                        "sql": "SELECT 2",
                        "distance": 0.2,
                    },
                    {
                        "source_id": "en_train:2",
                        "db_id": "bike_1",
                        "question": "Question three?",
                        "sql": "SELECT 3",
                        "distance": 0.3,
                    },
                ]
            ),
            "non-empty sql",
        ),
    ],
)
def test_selection_store_rejects_invalid_records(tmp_path, payload, message):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "invalid-selection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        SelectionStore.from_path(path)


@pytest.mark.parametrize("format_version", [0, 2, True])
def test_selection_store_rejects_non_integer_or_unsupported_format_version(
    tmp_path, format_version
):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "invalid-version.json"
    payload = _selection_payload()
    payload["format_version"] = format_version
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported selection format_version"):
        SelectionStore.from_path(path)


def test_selection_store_rejects_malformed_json(tmp_path):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "malformed-selection.json"
    path.write_text('{"format_version":', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid selection JSON"):
        SelectionStore.from_path(path)


def test_selection_store_rejects_duplicate_target_key(tmp_path):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "duplicate-target.json"
    payload = _selection_payload()
    payload["records"].append(
        {"target_key": "target-key", "examples": payload["records"][0]["examples"]}
    )
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate target_key"):
        SelectionStore.from_path(path)


@pytest.mark.parametrize("distance", [float("nan"), float("inf"), float("-inf")])
def test_selection_store_rejects_non_finite_distance(tmp_path, distance):
    from model.fewshot.store import SelectionStore

    path = tmp_path / "non-finite-distance.json"
    payload = _selection_payload()
    payload["records"][0]["examples"][0]["distance"] = distance
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="finite distance"):
        SelectionStore.from_path(path)


def test_euclidean_selector_orders_nearest_and_excludes_self():
    """RSL 检索使用未归一化 embedding 的欧氏距离，并稳定排除泄漏项。"""
    np = pytest.importorskip("numpy")
    from model.fewshot.offline import select_top_k

    corpus = np.array([[0.0, 0.0], [1.0, 0.0], [4.0, 0.0]])
    target = np.array([[0.1, 0.0]])

    got = select_top_k(target, corpus, k=2, excluded={0})

    assert [index for index, _ in got[0]] == [1, 2]
    assert [distance for _, distance in got[0]] == pytest.approx([0.9, 3.9])


def test_euclidean_selector_uses_stable_index_order_for_ties():
    np = pytest.importorskip("numpy")
    from model.fewshot.offline import select_top_k

    corpus = np.array([[1.0, 0.0], [-1.0, 0.0], [2.0, 0.0]])
    target = np.array([[0.0, 0.0]])

    got = select_top_k(target, corpus, k=2, excluded=set())

    assert [index for index, _ in got[0]] == [0, 1]


def test_euclidean_selector_uses_target_blocks_and_matches_direct_distance(monkeypatch):
    np = pytest.importorskip("numpy")
    from model.fewshot import offline

    corpus = np.array(
        [[0.0, 0.0], [1.0, 1.0], [-1.0, -1.0], [3.0, 4.0]],
        dtype=float,
    )
    targets = np.array(
        [[0.0, 0.0], [0.5, 0.5], [-0.5, -0.5], [3.0, 4.0], [2.0, 2.0]],
        dtype=float,
    )
    calls = []
    direct_block = offline._euclidean_distance_block

    def tracked_block(target_block, corpus_embeddings):
        calls.append(len(target_block))
        return direct_block(target_block, corpus_embeddings)

    monkeypatch.setattr(offline, "TARGET_BLOCK_SIZE", 2)
    monkeypatch.setattr(offline, "_euclidean_distance_block", tracked_block)

    got = offline.select_top_k(targets, corpus, k=4, excluded=set())

    expected_distances = np.linalg.norm(
        targets[:, None, :] - corpus[None, :, :],
        axis=2,
    )
    expected = [
        [
            (int(index), float(row[index]))
            for index in np.argsort(row, kind="stable")
        ]
        for row in expected_distances
    ]
    assert calls == [2, 2, 1]
    for got_row, expected_row in zip(got, expected, strict=True):
        assert [index for index, _ in got_row] == [
            index for index, _ in expected_row
        ]
        assert [distance for _, distance in got_row] == pytest.approx(
            [distance for _, distance in expected_row]
        )


def test_euclidean_distance_block_clips_roundoff_and_returns_zero_for_identity():
    np = pytest.importorskip("numpy")
    from model.fewshot.offline import _euclidean_distance_block

    # Large and small components exercise cancellation in
    # ||a||² + ||b||² - 2a·b; the exact identical-vector distance is zero.
    vector = np.array([[1.0e12, 3.0, -1.0e12, 1.0e-6]], dtype=float)

    distances = _euclidean_distance_block(vector, vector)

    assert distances.shape == (1, 1)
    assert distances[0, 0] == 0.0


def test_corpus_command_converts_archer_json_deterministically(tmp_path):
    from model.fewshot.offline import main

    source = tmp_path / "en_data" / "train.json"
    source.parent.mkdir()
    source.write_text(
        json.dumps(
            [
                {"db_id": "db", "question": "Question one?", "query": "SELECT 1"},
                {"db_id": "db", "question": "Question two?", "query": "SELECT 2"},
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "corpora" / "archer_en_train.json"

    assert (
        main(
            [
                "corpus",
                "--input",
                str(source),
                "--format",
                "archer-json",
                "--name",
                "archer_en_train",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    first_bytes = output.read_bytes()
    payload = json.loads(first_bytes)
    assert payload["name"] == "archer_en_train"
    assert payload["examples"][0] == {
        "source_id": "en_train:0",
        "db_id": "db",
        "question": "Question one?",
        "sql": "SELECT 1",
    }
    main(
        [
            "corpus",
            "--input",
            str(source),
            "--format",
            "archer-json",
            "--name",
            "archer_en_train",
            "--output",
            str(output),
        ]
    )
    assert output.read_bytes() == first_bytes


def test_select_command_excludes_target_with_matching_source_id(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    from model.fewshot import offline

    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "name": "tiny",
                "examples": [
                    {
                        "source_id": f"tiny:{index}",
                        "db_id": "db",
                        "question": f"Corpus {index}?",
                        "sql": f"SELECT {index}",
                    }
                    for index in range(3)
                ],
            }
        ),
        encoding="utf-8",
    )
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            [
                {
                    "source_id": "tiny:0",
                    "db_id": "db",
                    "question": "Target?",
                }
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "selection.json"

    monkeypatch.setattr(
        offline,
        "encode_texts",
        lambda texts, encoder: np.array(
            [[0.0], [1.0], [4.0], [0.1]], dtype=float
        ),
    )
    offline.build_selection(
        corpus_path=corpus_path,
        targets_path=targets_path,
        target_format="archer-json",
        encoder="fake-encoder",
        k=2,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    record = payload["records"][0]
    assert record["target_source_id"] == "tiny:0"
    assert [item["source_id"] for item in record["examples"]] == [
        "tiny:1",
        "tiny:2",
    ]


def test_select_command_shares_one_record_for_duplicate_targets(
    tmp_path, monkeypatch, capsys
):
    np = pytest.importorskip("numpy")
    from model.fewshot import offline

    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "name": "tiny",
                "examples": [
                    {
                        "source_id": f"tiny:{index}",
                        "db_id": "db",
                        "question": f"Corpus {index}?",
                        "sql": f"SELECT {index}",
                    }
                    for index in range(3)
                ],
            }
        ),
        encoding="utf-8",
    )
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            [
                {"db_id": "db", "question": "Repeated target?"},
                {"db_id": "other_db", "question": "Other target?"},
                {"db_id": " db ", "question": " Repeated target?\r\n"},
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "selection.json"
    encoded_texts = []

    def fake_encode(texts, encoder):
        encoded_texts.extend(texts)
        # Three corpus rows followed by two unique targets.
        return np.array([[0.0], [1.0], [2.0], [0.1], [1.9]], dtype=float)

    monkeypatch.setattr(offline, "encode_texts", fake_encode)

    assert offline.main(
        [
            "select",
            "--corpus",
            str(corpus_path),
            "--targets",
            str(targets_path),
            "--target-format",
            "bird-json",
            "--encoder",
            "fake-encoder",
            "--k",
            "1",
            "--output",
            str(output_path),
        ]
    ) == 0
    cli_output = capsys.readouterr().out
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert "2 unique records" in cli_output

    assert encoded_texts == [
        "Corpus 0?",
        "Corpus 1?",
        "Corpus 2?",
        "Repeated target?",
        "Other target?",
    ]
    assert len(payload["records"]) == 2
    assert [record["target_key"] for record in payload["records"]] == [
        offline.sample_key("db", "Repeated target?"),
        offline.sample_key("other_db", "Other target?"),
    ]
    assert payload["records"][0]["examples"][0]["source_id"] == "tiny:0"
    assert payload["records"][1]["examples"][0]["source_id"] == "tiny:2"


def test_select_rejects_defensive_target_key_collision(tmp_path, monkeypatch):
    from model.fewshot import offline

    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "name": "tiny",
                "examples": [
                    {
                        "source_id": "tiny:0",
                        "db_id": "db",
                        "question": "Corpus?",
                        "sql": "SELECT 1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            [
                {"db_id": "db", "question": "First?"},
                {"db_id": "db", "question": "Different?"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(offline, "sample_key", lambda db_id, question: "collision")

    with pytest.raises(ValueError, match="target_key collision"):
        offline.build_selection(
            corpus_path=corpus_path,
            targets_path=targets_path,
            target_format="bird-json",
            encoder="unused",
            k=1,
            output_path=tmp_path / "selection.json",
        )


def test_select_rejects_same_source_file_when_targets_have_no_source_ids(tmp_path):
    from model.fewshot.offline import build_selection

    source = tmp_path / "same.json"
    source.write_text(
        json.dumps([{"db_id": "db", "question": "Question?", "query": "SELECT 1"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="same file.*source_id"):
        build_selection(
            corpus_path=source,
            targets_path=source,
            target_format="archer-json",
            encoder="unused",
            k=3,
            output_path=tmp_path / "selection.json",
        )


@pytest.mark.parametrize("format_version", [True, 1.0])
def test_select_rejects_non_integer_corpus_format_version(
    tmp_path, format_version
):
    from model.fewshot.offline import build_selection

    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps(
            {
                "format_version": format_version,
                "name": "tiny",
                "examples": [
                    {
                        "source_id": "tiny:0",
                        "db_id": "db",
                        "question": "Corpus?",
                        "sql": "SELECT 1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    targets = tmp_path / "targets.json"
    targets.write_text(
        json.dumps([{"db_id": "db", "question": "Target?"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported corpus format_version"):
        build_selection(
            corpus_path=corpus,
            targets_path=targets,
            target_format="archer-json",
            encoder="unused",
            k=1,
            output_path=tmp_path / "selection.json",
        )


def test_corpus_conversion_rejects_duplicate_source_ids(tmp_path):
    from model.fewshot.offline import build_corpus

    source = tmp_path / "train.json"
    source.write_text(
        json.dumps(
            [
                {
                    "source_id": "duplicate",
                    "db_id": "db",
                    "question": "One?",
                    "query": "SELECT 1",
                },
                {
                    "source_id": "duplicate",
                    "db_id": "db",
                    "question": "Two?",
                    "query": "SELECT 2",
                },
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate source_id"):
        build_corpus(
            input_path=source,
            input_format="archer-json",
            name="archer_en_train",
            output_path=tmp_path / "corpus.json",
        )


def test_audit_reports_required_counts_and_deterministic_samples(tmp_path, capsys):
    from model.fewshot.offline import audit_selection

    selection = tmp_path / "selection.json"
    payload = _selection_payload()
    payload["records"][0]["target_source_id"] = "en_train:0"
    payload["records"].append(
        {
            "target_key": "aaa-first",
            "examples": payload["records"][0]["examples"][:2],
        }
    )
    selection.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_selection(selection)
    output = capsys.readouterr().out

    assert report["record_count"] == 2
    assert report["fewer_than_3"] == 1
    assert report["more_than_3"] == 0
    assert report["self_selection_count"] == 1
    assert report["distance"] == {
        "minimum": 0.0,
        "median": 1.0,
        "maximum": 2.0,
    }
    assert report["sample_selections"][0]["target_key"] == "aaa-first"
    assert "duplicated source IDs: 0" in output
    assert "distance min/median/max: 0.0 / 1.0 / 2.0" in output


def test_audit_reports_sfs_metadata_and_similarity(tmp_path, capsys):
    from model.fewshot.offline import audit_selection

    selection = tmp_path / "selection.json"
    payload = _selection_payload()
    payload["retrieval"] = {
        "strategy": "sfs-v1",
        "fallback_count": 2,
    }
    for index, example in enumerate(payload["records"][0]["examples"]):
        example["structure_similarity"] = index / 2
    selection.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_selection(selection)
    output = capsys.readouterr().out

    assert report["retrieval"]["strategy"] == "sfs-v1"
    assert report["structure_similarity"]["median"] == 0.5
    assert "retrieval strategy: sfs-v1" in output
    assert "structure similarity min/median/max: 0.0 / 0.5 / 1.0" in output


def test_direct_cli_help_works_without_loading_optional_dependencies():
    script = Path(config.ROOT) / "scripts" / "build_fewshot.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=config.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "{corpus,select,rerank-sfs,audit}" in result.stdout


def test_module_cli_help_invokes_main():
    result = subprocess.run(
        [sys.executable, "-m", "model.fewshot.offline", "--help"],
        cwd=config.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "{corpus,select,rerank-sfs,audit}" in result.stdout
