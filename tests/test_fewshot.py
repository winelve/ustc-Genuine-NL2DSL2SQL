"""Few-shot retrieval 基础数据契约测试。"""

from dataclasses import FrozenInstanceError
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


def test_retrieval_dependency_manifest_targets_cpu_python_311_or_312():
    """Torch 2.5.1 的 Windows CPU wheel 必须从官方索引、独立兼容解释器取得。"""
    manifest = (Path(config.ROOT) / "requirements-fewshot.txt").read_text(encoding="utf-8")

    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in manifest
    assert "Python 3.11/3.12" in manifest


def test_retrieval_manifest_pins_transformers_compatible_with_torch_251():
    """本地可信 .bin 模型必须避开要求 Torch 2.6 的新版 Transformers。"""
    manifest = (Path(config.ROOT) / "requirements-fewshot.txt").read_text(encoding="utf-8")

    assert "transformers==4.46.3" in manifest.splitlines()


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
    assert "{corpus,select,audit}" in result.stdout
