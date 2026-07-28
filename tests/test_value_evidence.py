import json
import sqlite3
from pathlib import Path

import pytest


def _toy_db(tmp_path: Path) -> Path:
    db = tmp_path / "toy.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE account (
            account_id INTEGER PRIMARY KEY,
            frequency TEXT,
            opened_date TEXT
        );
        INSERT INTO account VALUES
            (1, 'POPLATEK TYDNE', '2020-01-01'),
            (2, 'POPLATEK MESICNE', '2020-01-02'),
            (3, 'POPLATEK PO OBRATU', '2020-01-03');
        """
    )
    conn.commit()
    conn.close()
    return db


def _selection_payload(*, records=None, strategy="chess-ir-mpnet-v1"):
    from model.fewshot.store import sample_key

    question = "How many weekly issuance accounts are there?"
    record = {
        "target_key": sample_key("toy", question),
        "db_id": "toy",
        "question": question,
        "keywords": ["weekly issuance", "frequency"],
        "values": [
            {
                "table": "account",
                "column": "frequency",
                "value": "POPLATEK TYDNE",
                "control_value": "POPLATEK MESICNE",
                "keyword": "weekly issuance",
                "edit_similarity": 0.4,
                "embedding_similarity": 0.72,
            }
        ],
        "contexts": [
            {
                "table": "account",
                "column": "frequency",
                "description": "Frequency of account statement issuance.",
                "score": 0.81,
            }
        ],
    }
    return {
        "format_version": 1,
        "strategy": strategy,
        "dataset": "toy_dev",
        "dataset_sha256": "1" * 64,
        "keywords_sha256": "2" * 64,
        "encoder": "sentence-transformers/all-mpnet-base-v2",
        "encoder_sha256": "3" * 64,
        "parameters": {
            "signature_size": 100,
            "n_gram": 3,
            "lsh_threshold": 0.01,
            "lsh_top_n": 10,
            "edit_threshold": 0.3,
            "embedding_threshold": 0.6,
            "max_values_per_column": 3,
            "max_values_total": 12,
            "max_context_columns": 8,
        },
        "records": [record] if records is None else records,
    }


def _write_selection(tmp_path: Path, payload=None) -> Path:
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(payload or _selection_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_value_evidence_store_loads_and_looks_up_by_sample(tmp_path):
    from model.value_evidence.store import ValueEvidenceStore

    store = ValueEvidenceStore.from_path(_write_selection(tmp_path))
    record = store.for_sample(
        "toy", "How many weekly issuance accounts are there?"
    )

    assert record is not None
    assert record.keywords == ("weekly issuance", "frequency")
    assert record.values[0].value == "POPLATEK TYDNE"
    assert record.contexts[0].column == "frequency"
    assert store.strategy == "chess-ir-mpnet-v1"
    assert len(store.artifact_sha256) == 64


def test_value_evidence_store_accepts_v2_strategy(tmp_path):
    from model.value_evidence.store import ValueEvidenceStore

    payload = _selection_payload(strategy="chess-ir-mpnet-v2")
    store = ValueEvidenceStore.from_path(_write_selection(tmp_path, payload))

    assert store.strategy == "chess-ir-mpnet-v2"


def test_value_evidence_store_rejects_duplicate_targets_and_values(tmp_path):
    from model.value_evidence.store import ValueEvidenceStore

    payload = _selection_payload()
    payload["records"].append(dict(payload["records"][0]))
    with pytest.raises(ValueError, match="duplicate target_key"):
        ValueEvidenceStore.from_path(_write_selection(tmp_path, payload))

    payload = _selection_payload()
    payload["records"][0]["values"].append(
        dict(payload["records"][0]["values"][0])
    )
    with pytest.raises(ValueError, match="duplicate retrieved value"):
        ValueEvidenceStore.from_path(_write_selection(tmp_path, payload))

    payload = _selection_payload()
    payload["records"][0]["values"][0]["control_value"] = (
        payload["records"][0]["values"][0]["value"]
    )
    with pytest.raises(ValueError, match="control_value must differ"):
        ValueEvidenceStore.from_path(_write_selection(tmp_path, payload))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("format_version", 2, "unsupported value evidence format_version"),
        ("dataset_sha256", "short", "64-character hexadecimal"),
        ("strategy", "other", "unsupported value evidence strategy"),
    ],
)
def test_value_evidence_store_rejects_invalid_metadata(
    tmp_path, field, value, message
):
    from model.value_evidence.store import ValueEvidenceStore

    payload = _selection_payload()
    payload[field] = value
    with pytest.raises(ValueError, match=message):
        ValueEvidenceStore.from_path(_write_selection(tmp_path, payload))


def test_render_value_schema_uses_ddl_and_relevant_or_control_value(tmp_path):
    from model.value_evidence.render import render_value_schema
    from model.value_evidence.store import ValueEvidenceStore

    store = ValueEvidenceStore.from_path(_write_selection(tmp_path))
    record = store.for_sample(
        "toy", "How many weekly issuance accounts are there?"
    )
    db = _toy_db(tmp_path)

    relevant = render_value_schema(db, record, mode="relevant")
    control = render_value_schema(db, record, mode="random")

    assert "CREATE TABLE account" in relevant
    assert "Retrieved database context" in relevant
    assert "Frequency of account statement issuance." in relevant
    assert "POPLATEK TYDNE" in relevant
    assert "POPLATEK MESICNE" not in relevant
    assert "POPLATEK MESICNE" in control
    assert "POPLATEK TYDNE" not in control
    assert "3 example rows" not in relevant
    assert relevant.replace("POPLATEK TYDNE", "<VALUE>") == control.replace(
        "POPLATEK MESICNE", "<VALUE>"
    )


def test_render_additive_value_schema_preserves_ct3_rows(tmp_path):
    from model.value_evidence.render import render_additive_value_schema
    from model.value_evidence.store import ValueEvidenceStore

    store = ValueEvidenceStore.from_path(_write_selection(tmp_path))
    record = next(iter(store.records.values()))

    rendered = render_additive_value_schema(
        _toy_db(tmp_path), record, mode="relevant"
    )

    assert "/* 3 example rows:" in rendered
    assert "POPLATEK TYDNE\t2020-01-01" in rendered
    assert "Retrieved database context" in rendered
    assert rendered.index("/* 3 example rows:") < rendered.index(
        "Retrieved database context"
    )


def test_render_value_schema_rejects_unknown_mode(tmp_path):
    from model.value_evidence.render import render_value_schema
    from model.value_evidence.store import ValueEvidenceStore

    record = next(
        iter(ValueEvidenceStore.from_path(_write_selection(tmp_path)).records.values())
    )
    with pytest.raises(ValueError, match="mode"):
        render_value_schema(_toy_db(tmp_path), record, mode="anything")


def test_value_evidence_trace_records_mode_and_injected_values(tmp_path):
    from model.value_evidence.render import value_evidence_trace
    from model.value_evidence.store import ValueEvidenceStore

    store = ValueEvidenceStore.from_path(_write_selection(tmp_path))
    record = next(iter(store.records.values()))

    trace = value_evidence_trace(
        selection="toy_chess_ir",
        store=store,
        record=record,
        mode="random",
    )

    assert trace["selection"] == "toy_chess_ir"
    assert trace["artifact_sha256"] == store.artifact_sha256
    assert trace["mode"] == "random"
    assert trace["keywords"] == ["weekly issuance", "frequency"]
    assert trace["values"][0]["value"] == "POPLATEK MESICNE"
    assert trace["values"][0]["relevant_value"] == "POPLATEK TYDNE"


def test_extract_unique_text_values_applies_chess_column_filters(tmp_path):
    from model.value_evidence.index import extract_unique_text_values

    db = tmp_path / "filter.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE items (
            item_pk TEXT PRIMARY KEY,
            id TEXT,
            row_UUID TEXT,
            display_name TEXT,
            category TEXT,
            source_url TEXT,
            opened_date TEXT,
            customer_id TEXT,
            amount REAL
        )
        """
    )
    conn.executemany(
        "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                f"pk-{i}",
                f"id-{i}",
                f"uuid-{i}",
                f"Item {i}",
                "A" if i % 2 else "B",
                f"https://example/{i}",
                "2020-01-01",
                f"C{i}",
                float(i),
            )
            for i in range(5)
        ],
    )
    conn.commit()
    conn.close()

    values = extract_unique_text_values(db)

    assert set(values["items"]) == {"display_name", "category"}
    assert values["items"]["category"] == ["A", "B"]
    assert "item_pk" not in values["items"]
    assert "id" not in values["items"]
    assert "row_UUID" not in values["items"]
    assert "source_url" not in values["items"]
    assert "opened_date" not in values["items"]
    assert "customer_id" not in values["items"]
    assert "amount" not in values["items"]


def test_extract_unique_text_values_skips_high_cardinality_long_text(tmp_path):
    from model.value_evidence.index import extract_unique_text_values

    db = tmp_path / "large_text.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE docs (body TEXT, document_name TEXT)")
    rows = [
        (f"{i:03d}-" + "long paragraph " * 3, f"{i:03d}-" + "long name " * 3)
        for i in range(101)
    ]
    conn.executemany("INSERT INTO docs VALUES (?, ?)", rows)
    conn.commit()
    conn.close()

    values = extract_unique_text_values(db)

    assert "body" not in values["docs"]
    assert len(values["docs"]["document_name"]) == 101


def test_character_ngrams_matches_chess_three_gram_behavior():
    from model.value_evidence.index import character_ngrams, normalise_lsh_text

    assert character_ngrams("weekly", 3) == (
        "wee",
        "eek",
        "ekl",
        "kly",
    )
    assert character_ngrams("ab", 3) == ("ab",)
    assert normalise_lsh_text("Alabama") == normalise_lsh_text("ALABAMA")


def test_index_metadata_is_stable_and_records_database_checksum(tmp_path):
    from model.value_evidence.index import build_index_metadata

    db = _toy_db(tmp_path)
    first = build_index_metadata(
        db,
        unique_values={"account": {"frequency": ["A", "B"]}},
        signature_size=100,
        n_gram=3,
        lsh_threshold=0.01,
    )
    second = build_index_metadata(
        db,
        unique_values={"account": {"frequency": ["A", "B"]}},
        signature_size=100,
        n_gram=3,
        lsh_threshold=0.01,
    )

    assert first == second
    assert first["format_version"] == 1
    assert first["database_sha256"]
    assert first["value_count"] == 2


def test_keyword_prompt_uses_question_and_evidence():
    from model.value_evidence.keywords import render_keyword_prompt

    prompt = render_keyword_prompt(
        "Which accounts are weekly?",
        "weekly refers to frequency = 'POPLATEK TYDNE'",
    )

    assert "Question: Which accounts are weekly?" in prompt
    assert "Hint: weekly refers to frequency = 'POPLATEK TYDNE'" in prompt
    assert "{QUESTION}" not in prompt
    assert "{HINT}" not in prompt
    assert "Only output the Python list" in prompt


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('["weekly issuance", "frequency"]', ["weekly issuance", "frequency"]),
        ("['weekly issuance', 'frequency']", ["weekly issuance", "frequency"]),
        (
            "```python\n['weekly issuance', 'frequency']\n```",
            ["weekly issuance", "frequency"],
        ),
        (
            '["weekly issuance", "weekly issuance", " frequency "]',
            ["weekly issuance", "frequency"],
        ),
    ],
)
def test_parse_keywords_accepts_chess_list_shapes(reply, expected):
    from model.value_evidence.keywords import parse_keywords

    assert parse_keywords(reply) == expected


@pytest.mark.parametrize("reply", ["not a list", '{"keyword": "x"}', "[1, 2]"])
def test_parse_keywords_rejects_invalid_output(reply):
    from model.value_evidence.keywords import parse_keywords

    with pytest.raises(ValueError, match="keyword"):
        parse_keywords(reply)


def test_keyword_artifact_checkpoints_and_resumes(tmp_path):
    from archer_eval.data import Sample
    from model.value_evidence.keywords import build_keyword_artifact

    samples = [
        Sample(db_id="toy", query="SELECT 1", question=f"Question {i}")
        for i in range(4)
    ]
    output = tmp_path / "keywords.json"
    first_seen = []

    def first_extractor(sample):
        first_seen.append(sample.question)
        if sample.question == "Question 2":
            raise RuntimeError("temporary API error")
        return {
            "keywords": [sample.question],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        }

    with pytest.raises(RuntimeError, match="1 keyword extraction"):
        build_keyword_artifact(
            samples,
            output_path=output,
            dataset="toy_dev",
            dataset_sha256="a" * 64,
            extractor=first_extractor,
            chunk=2,
            concurrency=1,
        )

    second_seen = []

    def second_extractor(sample):
        second_seen.append(sample.question)
        return {
            "keywords": [sample.question],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        }

    payload = build_keyword_artifact(
        samples,
        output_path=output,
        dataset="toy_dev",
        dataset_sha256="a" * 64,
        extractor=second_extractor,
        chunk=2,
        concurrency=1,
    )

    assert first_seen == ["Question 0", "Question 1", "Question 2", "Question 3"]
    assert second_seen == ["Question 2"]
    assert len(payload["records"]) == 4
    assert payload["usage"]["total_tokens"] == 48
    assert output.exists()
    assert not output.with_suffix(".partial.jsonl").exists()


def test_keyword_artifact_deduplicates_identical_targets(tmp_path):
    from archer_eval.data import Sample
    from model.value_evidence.keywords import build_keyword_artifact

    sample = Sample(db_id="toy", query="SELECT 1", question="Same question")
    calls = []

    def extractor(got):
        calls.append(got.question)
        return {
            "keywords": ["Same"],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }

    payload = build_keyword_artifact(
        [sample, sample],
        output_path=tmp_path / "keywords.json",
        dataset="toy",
        dataset_sha256="a" * 64,
        extractor=extractor,
        concurrency=1,
    )

    assert calls == ["Same question"]
    assert len(payload["records"]) == 1
    assert payload["usage"]["total_tokens"] == 12


def test_keyword_variants_follow_chess_expansion():
    from model.value_evidence.retrieve import keyword_variants

    assert keyword_variants(
        ["weekly account issuance", "frequency = monthly"]
    ) == [
        ("weekly account issuance", "weekly account issuance"),
        ("weekly account issuance", "account issuance"),
        ("weekly account issuance", "weekly account"),
        ("weekly account issuance", "issuance"),
        ("weekly account issuance", "weekly"),
        ("frequency = monthly", "frequency = monthly"),
        ("frequency = monthly", "frequency ="),
        ("frequency = monthly", "frequency"),
        ("frequency = monthly", "= monthly"),
        ("frequency = monthly", "monthly"),
    ]


def test_postprocess_candidates_preserves_exact_and_applies_caps():
    from model.value_evidence.retrieve import postprocess_value_candidates

    candidates = [
        {
            "table": "account",
            "column": "frequency",
            "value": "weekly",
            "keyword": "weekly issuance",
            "substring": "weekly",
            "lsh_similarity": 1.0,
            "embedding_similarity": 0.2,
        },
        {
            "table": "account",
            "column": "frequency",
            "value": "monthly",
            "keyword": "monthly",
            "substring": "monthly",
            "lsh_similarity": 0.9,
            "embedding_similarity": 0.95,
        },
        {
            "table": "account",
            "column": "frequency",
            "value": "month",
            "keyword": "monthly",
            "substring": "monthly",
            "lsh_similarity": 0.8,
            "embedding_similarity": 0.94,
        },
        {
            "table": "account",
            "column": "district",
            "value": "North",
            "keyword": "north",
            "substring": "north",
            "lsh_similarity": 1.0,
            "embedding_similarity": 0.99,
        },
    ]

    selected = postprocess_value_candidates(
        candidates,
        edit_threshold=0.3,
        embedding_threshold=0.6,
        max_values_per_column=2,
        max_values_total=3,
    )

    assert {(item["column"], item["value"]) for item in selected} == {
        ("frequency", "weekly"),
        ("district", "North"),
        ("frequency", "monthly"),
    }
    weekly = next(item for item in selected if item["value"] == "weekly")
    assert weekly["exact_or_substring"] is True
    assert weekly["edit_similarity"] == 1.0


def test_postprocess_candidates_deduplicates_and_uses_relative_column_scores():
    from model.value_evidence.retrieve import postprocess_value_candidates

    candidates = [
        {
            "table": "t",
            "column": "c",
            "value": "Alpha",
            "keyword": "Alfa",
            "substring": "Alfa",
            "lsh_similarity": 0.9,
            "embedding_similarity": 0.9,
        },
        {
            "table": "t",
            "column": "c",
            "value": "Alpha",
            "keyword": "Alpha",
            "substring": "Alpha",
            "lsh_similarity": 1.0,
            "embedding_similarity": 1.0,
        },
        {
            "table": "t",
            "column": "c",
            "value": "Alpho",
            "keyword": "Alpha",
            "substring": "Alpha",
            "lsh_similarity": 0.8,
            "embedding_similarity": 0.7,
        },
    ]

    selected = postprocess_value_candidates(candidates)

    assert [item["value"] for item in selected] == ["Alpha"]


def test_postprocess_candidates_v2_has_no_substring_filter_bypass():
    from model.value_evidence.retrieve import postprocess_value_candidates

    candidates = [
        {
            "table": "stadium",
            "column": "Name",
            "value": "Somerset Park",
            "keyword": "Somerset Park stadium",
            "substring": "Somerset Park",
            "lsh_similarity": 1.0,
            "embedding_similarity": 0.92,
        },
        {
            "table": "stadium",
            "column": "Name",
            "value": "Bayview Stadium",
            "keyword": "Somerset Park stadium",
            "substring": "stadium",
            "lsh_similarity": 0.8,
            "embedding_similarity": 0.58,
        },
        {
            "table": "stadium",
            "column": "Name",
            "value": "Forthbank Stadium",
            "keyword": "Somerset Park stadium",
            "substring": "stadium",
            "lsh_similarity": 0.8,
            "embedding_similarity": 0.75,
        },
    ]

    legacy = postprocess_value_candidates(candidates)
    strict = postprocess_value_candidates(
        candidates, preserve_substring_hits=False
    )

    assert {item["value"] for item in legacy} == {
        "Somerset Park",
        "Bayview Stadium",
        "Forthbank Stadium",
    }
    assert [item["value"] for item in strict] == ["Somerset Park"]


def test_merge_context_candidates_keeps_best_per_column():
    from model.value_evidence.retrieve import merge_context_candidates

    merged = merge_context_candidates(
        [
            {"table": "t", "column": "a", "description": "weak", "score": 0.4},
            {"table": "t", "column": "a", "description": "best", "score": 0.9},
            {"table": "t", "column": "b", "description": "other", "score": 0.8},
        ],
        max_columns=1,
    )

    assert merged == [
        {"table": "t", "column": "a", "description": "best", "score": 0.9}
    ]


def test_context_queries_combine_question_evidence_and_each_keyword():
    from model.value_evidence.retrieve import context_query_texts

    assert context_query_texts(
        {
            "question": "Which accounts are weekly?",
            "evidence": "weekly means frequency = W",
            "keywords": ["weekly", "frequency"],
        }
    ) == [
        "Which accounts are weekly? weekly",
        "weekly means frequency = W weekly",
        "Which accounts are weekly? frequency",
        "weekly means frequency = W frequency",
    ]


def test_choose_control_value_is_same_column_length_matched_and_stable():
    from model.value_evidence.retrieve import choose_control_value

    unique_values = {"t": {"c": ["AA", "BBBB", "CCCC", "DDDDDD"]}}
    first = choose_control_value(
        unique_values,
        table="t",
        column="c",
        relevant_value="BBBB",
        target_key="a" * 64,
        slot=0,
    )
    second = choose_control_value(
        unique_values,
        table="t",
        column="c",
        relevant_value="BBBB",
        target_key="a" * 64,
        slot=0,
    )

    assert first == second
    assert first in {"AA", "CCCC"}


def test_choose_control_value_rejects_singleton_column():
    from model.value_evidence.retrieve import choose_control_value

    with pytest.raises(ValueError, match="distinct control"):
        choose_control_value(
            {"t": {"c": ["only"]}},
            table="t",
            column="c",
            relevant_value="only",
            target_key="a" * 64,
            slot=0,
        )


def test_selection_rejects_context_embeddings_from_another_encoder(
    monkeypatch, tmp_path
):
    import model.value_evidence.retrieve as retrieve

    keyword_path = tmp_path / "keywords.json"
    keyword_path.write_text(
        json.dumps(
            {
                "dataset": "toy",
                "dataset_sha256": "a" * 64,
                "records": [
                    {
                        "target_key": "b" * 64,
                        "db_id": "toy",
                        "question": "Q",
                        "keywords": ["K"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeIndex:
        metadata = {"context_encoder_sha256": "1" * 64}
        contexts = [{"table": "t", "column": "c", "text": "description"}]

    monkeypatch.setattr(retrieve, "DatabaseIndex", lambda _path: FakeIndex())
    monkeypatch.setattr(retrieve, "encoder_checksum", lambda _path: "2" * 64)

    with pytest.raises(ValueError, match="context encoder checksum mismatch"):
        retrieve.build_selection_artifact(
            keyword_path,
            tmp_path / "indexes",
            tmp_path / "selection.json",
            encoder=object(),
            encoder_name="all-mpnet-base-v2",
            encoder_path=tmp_path / "encoder",
        )


def test_audit_selection_rejects_checksum_and_target_coverage(tmp_path):
    from model.fewshot.store import sample_key
    from model.value_evidence.offline import audit_selection
    from model.value_evidence.store import ValueEvidenceStore

    store = ValueEvidenceStore.from_path(_write_selection(tmp_path))
    present = sample_key("toy", "How many weekly issuance accounts are there?")

    with pytest.raises(ValueError, match="dataset checksum"):
        audit_selection(
            store,
            dataset="toy_dev",
            dataset_sha256="9" * 64,
            expected_target_keys={present},
        )
    with pytest.raises(ValueError, match="target coverage"):
        audit_selection(
            store,
            dataset="toy_dev",
            dataset_sha256="1" * 64,
            expected_target_keys={present, "f" * 64},
        )


def test_v2_model_and_audit_reject_mislabeled_or_weak_artifacts(tmp_path):
    from model.api import DeepSeekProThinkingValueEvidenceV2
    from model.fewshot.store import sample_key
    from model.value_evidence.offline import audit_selection
    from model.value_evidence.store import ValueEvidenceStore

    v1_store = ValueEvidenceStore.from_path(_write_selection(tmp_path))
    generator = DeepSeekProThinkingValueEvidenceV2.__new__(
        DeepSeekProThinkingValueEvidenceV2
    )
    with pytest.raises(ValueError, match="requires value evidence strategy"):
        generator._validate_value_evidence_store(v1_store)

    payload = _selection_payload(strategy="chess-ir-mpnet-v2")
    payload["parameters"]["embedding_threshold"] = 0.5
    weak_store = ValueEvidenceStore.from_path(
        _write_selection(tmp_path, payload)
    )
    present = sample_key("toy", payload["records"][0]["question"])
    with pytest.raises(ValueError, match="embedding_threshold"):
        audit_selection(
            weak_store,
            dataset="toy_dev",
            dataset_sha256="1" * 64,
            expected_target_keys={present},
            expected_strategy="chess-ir-mpnet-v2",
        )


def test_ct3_schema_override_preserves_baseline_path(monkeypatch, tmp_path):
    from archer_eval.data import Sample
    import model.prompts as prompts

    sample = Sample(db_id="toy", query="SELECT 1", question="How many?")
    monkeypatch.setattr(prompts, "schema_with_rows", lambda _path: "BASELINE SCHEMA")

    baseline = prompts.build_ct3_prompt(sample, tmp_path / "toy.sqlite")
    overridden = prompts.build_ct3_prompt(
        sample, tmp_path / "toy.sqlite", schema="VALUE SCHEMA"
    )

    assert baseline.startswith("BASELINE SCHEMA\n\n")
    assert overridden.startswith("VALUE SCHEMA\n\n")
    assert baseline.removeprefix("BASELINE SCHEMA") == overridden.removeprefix(
        "VALUE SCHEMA"
    )


def test_bird_schema_override_keeps_official_evidence_and_block_order(
    monkeypatch, tmp_path
):
    from archer_eval.data import Sample
    import bird.official as official

    sample = Sample(
        db_id="toy",
        query="SELECT 1",
        question="How many?",
        commonsense_knowledge="rate = numerator / denominator",
    )
    monkeypatch.setattr(official, "schema_ddl_block", lambda _path: "OFFICIAL DDL")

    baseline = official.official_prompt(sample, tmp_path / "toy.sqlite")
    overridden = official.official_prompt(
        sample, tmp_path / "toy.sqlite", schema="DDL PLUS VALUE"
    )

    assert baseline.startswith("OFFICIAL DDL\n\n")
    assert overridden.startswith("DDL PLUS VALUE\n\n")
    assert "-- External Knowledge: rate = numerator / denominator" in overridden
    assert overridden.index("DDL PLUS VALUE") < overridden.index("-- Using valid")
    assert overridden.index("-- Using valid") < overridden.index("Generate the SQLite")


def test_value_evidence_variants_are_registered_single_switches():
    from model import MODELS
    from model.api import (
        DeepSeekProThinking,
        DeepSeekProThinkingValueEvidence,
        DeepSeekProThinkingValueEvidenceRandom,
        DeepSeekProThinkingValueEvidenceV2,
        DeepSeekProThinkingValueEvidenceV2Random,
    )
    from model.bird import (
        BirdDirect,
        BirdDirectValueEvidence,
        BirdDirectValueEvidenceRandom,
        BirdProTDsl,
        BirdProTDslValueEvidence,
        BirdProTDslValueEvidenceRandom,
    )
    from model.pipeline.models import (
        ProTDsl,
        ProTDslValueEvidence,
        ProTDslValueEvidenceRandom,
    )

    expected = {
        "pro-t-direct-ve": DeepSeekProThinkingValueEvidence,
        "pro-t-direct-ve-r": DeepSeekProThinkingValueEvidenceRandom,
        "pro-t-direct-ve2": DeepSeekProThinkingValueEvidenceV2,
        "pro-t-direct-ve2-r": DeepSeekProThinkingValueEvidenceV2Random,
        "pro-t-dsl-ve": ProTDslValueEvidence,
        "pro-t-dsl-ve-r": ProTDslValueEvidenceRandom,
        "bird-pro-t-direct-ve": BirdDirectValueEvidence,
        "bird-pro-t-direct-ve-r": BirdDirectValueEvidenceRandom,
        "bird-pro-t-dsl-ve": BirdProTDslValueEvidence,
        "bird-pro-t-dsl-ve-r": BirdProTDslValueEvidenceRandom,
    }
    assert {name: MODELS[name] for name in expected} == expected
    for relevant, random, parent in (
        (
            DeepSeekProThinkingValueEvidence,
            DeepSeekProThinkingValueEvidenceRandom,
            DeepSeekProThinking,
        ),
        (
            DeepSeekProThinkingValueEvidenceV2,
            DeepSeekProThinkingValueEvidenceV2Random,
            DeepSeekProThinking,
        ),
        (ProTDslValueEvidence, ProTDslValueEvidenceRandom, ProTDsl),
        (BirdDirectValueEvidence, BirdDirectValueEvidenceRandom, BirdDirect),
        (
            BirdProTDslValueEvidence,
            BirdProTDslValueEvidenceRandom,
            BirdProTDsl,
        ),
    ):
        assert issubclass(relevant, parent)
        assert relevant.value_evidence_mode == "relevant"
        assert random.value_evidence_mode == "random"
        assert (
            relevant.value_evidence_selection
            == random.value_evidence_selection
        )
    assert DeepSeekProThinkingValueEvidenceV2.value_evidence_schema_mode == (
        "ct3-additive"
    )
    assert DeepSeekProThinkingValueEvidenceV2.value_evidence_selection == (
        "archer_en_dev_chess_ir_v2"
    )


def test_direct_value_evidence_fails_closed_when_target_missing():
    from archer_eval.data import Sample
    from model.api import DeepSeekProThinkingValueEvidence
    from model.value_evidence.store import ValueEvidenceStore

    sample = Sample(db_id="toy", query="SELECT 1", question="Missing?")
    generator = DeepSeekProThinkingValueEvidence.__new__(
        DeepSeekProThinkingValueEvidence
    )
    generator._value_evidence_store = ValueEvidenceStore(
        records={},
        dataset="toy",
        dataset_sha256="1" * 64,
        keywords_sha256="2" * 64,
        encoder="mpnet",
        encoder_sha256="3" * 64,
    )

    with pytest.raises(KeyError, match="value evidence"):
        generator._value_evidence_record(sample)


def test_direct_ve2_routes_through_additive_schema_and_traces_mode(
    monkeypatch, tmp_path
):
    from archer_eval.data import Sample
    import model.api as api
    from model.api import DeepSeekProThinkingValueEvidenceV2
    from model.value_evidence.store import ValueEvidenceStore

    sample = Sample(
        db_id="toy",
        query="SELECT 1",
        question="How many weekly issuance accounts are there?",
    )
    generator = DeepSeekProThinkingValueEvidenceV2.__new__(
        DeepSeekProThinkingValueEvidenceV2
    )
    generator._fewshot_store = None
    generator._value_evidence_store = ValueEvidenceStore.from_path(
        _write_selection(
            tmp_path,
            _selection_payload(strategy="chess-ir-mpnet-v2"),
        )
    )

    class Endpoint:
        def chat(self, _system, prompt):
            assert prompt.startswith("ADDITIVE SCHEMA\n\n")
            return "SELECT 1"

    generator._endpoint = Endpoint()
    monkeypatch.setattr(
        api,
        "render_additive_value_schema",
        lambda _path, _record, *, mode: f"ADDITIVE SCHEMA",
    )
    monkeypatch.setattr(
        api,
        "render_value_schema",
        lambda *_args, **_kwargs: pytest.fail("VE2 used v1 replacement"),
    )

    assert generator.predict(sample, tmp_path / "toy.sqlite") == "SELECT 1"
    trace = generator.trace_for_sample(sample)["value_evidence"]
    assert trace["strategy"] == "chess-ir-mpnet-v2"
    assert trace["schema_mode"] == "ct3-additive"


def test_dsl_value_evidence_replaces_sample_rows_and_records_trace(
    monkeypatch, tmp_path
):
    from archer_eval.data import Sample
    import model.pipeline.models as pipeline_models
    from model.pipeline.models import ProTDslValueEvidence
    from model.value_evidence.store import ValueEvidenceStore

    selection = _write_selection(tmp_path)
    store = ValueEvidenceStore.from_path(selection)
    sample = Sample(
        db_id="toy",
        query="SELECT 1",
        question="How many weekly issuance accounts are there?",
    )
    generator = ProTDslValueEvidence.__new__(ProTDslValueEvidence)
    generator._fewshot_store = None
    generator._value_evidence_store = store
    monkeypatch.setattr(
        pipeline_models,
        "render_value_schema",
        lambda _path, _record, *, mode: f"VALUE SCHEMA {mode}",
    )
    monkeypatch.setattr(
        pipeline_models,
        "schema_with_rows",
        lambda _path: pytest.fail("VE arm used random sample rows"),
    )

    context = generator._prepare_context(sample, tmp_path / "toy.sqlite")

    assert context.schema == "VALUE SCHEMA relevant"
    assert context.value_evidence_trace["mode"] == "relevant"
    assert context.to_trace()["value_evidence"]["values"][0]["value"] == (
        "POPLATEK TYDNE"
    )
