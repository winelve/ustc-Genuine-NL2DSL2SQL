"""BIRD 适配层测试：config 挂钩、数据集转换、官方提示词、官方口径评测、
官方脚本适配器、分数汇总、模型档位、断点续跑。

一律不打真实 API、不依赖 data/bird 下的大库——需要库时用 tmp_path 现造。
"""

import collections
import hashlib
import inspect
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

import config
from archer_eval.data import Sample


# ---------------------------------------------------------- config 挂钩

def test_bird_dev_registered():
    assert "bird_dev" in config.DATASETS
    assert config.DATASETS["bird_dev"] == config.DATA_DIR / "bird" / "dev.json"


def test_db_dir_for_bird_dev():
    assert config.db_dir_for("bird_dev") == config.DATA_DIR / "bird" / "dev_databases"


def test_db_dir_for_archer_falls_back_to_db_dir():
    """红线：Archer 侧必须逐字节回落到原来的 DB_DIR。"""
    for name in ("en_train", "en_dev", "zh_train", "zh_dev"):
        assert config.db_dir_for(name) == config.DB_DIR


def test_db_dir_for_unknown_and_none_fall_back():
    assert config.db_dir_for(None) == config.DB_DIR
    assert config.db_dir_for("no_such_dataset") == config.DB_DIR


def test_db_dir_for_path_sibling_of_registered_dataset(tmp_path):
    """data/bird/ 下的子集文件应自动沿用 bird 的库根目录。"""
    sibling = config.DATA_DIR / "bird" / "subset.json"
    assert config.db_dir_for(sibling) == config.db_dir_for("bird_dev")
    assert config.db_dir_for(tmp_path / "elsewhere.json") == config.DB_DIR


# ---------------------------------------------------------- 调用点不再硬编码

def _source(rel: str) -> str:
    return (Path(config.ROOT) / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", [
    "model/__main__.py",
    "model/prompts.py",
    "model/pipeline/__main__.py",
    "archer_eval/__main__.py",
])
def test_entrypoints_resolve_db_dir_by_dataset(rel):
    """红线：入口不许再硬编码 config.DB_DIR，必须走 db_dir_for。"""
    src = _source(rel)
    assert "db_dir_for" in src, f"{rel} 没有使用 config.db_dir_for"
    assert not re.search(r"config\.DB_DIR", src), f"{rel} 仍在硬编码 config.DB_DIR"


# ---------------------------------------------------------- dataset

def _write_raw(tmp_path):
    """造一个迷你官方题目文件（新版是扁平 json 数组）。"""
    src = tmp_path / "dev_raw.json"
    src.write_text(json.dumps([
        {"question_id": 0, "db_id": "toy", "question": "Q0",
         "evidence": "rate = a / b", "SQL": "SELECT 1", "difficulty": "simple"},
        {"question_id": 1, "db_id": "toy", "question": "Q1",
         "evidence": "  ", "SQL": "SELECT 2", "difficulty": "challenging"},
    ]), encoding="utf-8")
    return src


def test_convert_maps_official_fields(tmp_path):
    from bird.dataset import convert

    out = tmp_path / "dev.json"
    samples = convert(_write_raw(tmp_path), out)

    assert len(samples) == 2
    assert samples[0]["query"] == "SELECT 1"                      # SQL -> query
    assert samples[0]["commonsense_knowledge"] == "rate = a / b"  # evidence -> ck
    assert samples[0]["question_id"] == 0
    assert samples[0]["difficulty"] == "simple"
    assert json.loads(out.read_text(encoding="utf-8")) == samples


def test_convert_blank_evidence_becomes_none(tmp_path):
    from bird.dataset import convert

    samples = convert(_write_raw(tmp_path), tmp_path / "dev.json")
    assert samples[1]["commonsense_knowledge"] is None


def test_converted_file_loads_as_samples(tmp_path):
    """转换结果必须能被现有 load_dataset 直接吃下，额外字段进 extras。"""
    from archer_eval.data import load_dataset
    from bird.dataset import convert

    out = tmp_path / "dev.json"
    convert(_write_raw(tmp_path), out)
    samples = load_dataset(out)

    assert samples[0].db_id == "toy"
    assert samples[0].query == "SELECT 1"
    assert samples[0].extras["difficulty"] == "simple"
    assert samples[0].extras["question_id"] == 0


def test_summarize_counts_evidence_and_difficulty(tmp_path):
    from bird.dataset import convert, summarize

    text = summarize(convert(_write_raw(tmp_path), tmp_path / "dev.json"))
    assert "2 samples" in text and "1 with evidence" in text


class _FakeResponse:
    """够用的 urlopen 替身：分块 read() + 上下文管理器。"""

    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_dev_zip(dev_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("dev_20240627/dev.json", dev_bytes)
        archive.writestr("dev_20240627/dev_tables.json", b"[]")
    return buf.getvalue()


def _version(tmp_name, payload, *, is_zip=False):
    from bird.paths import DevVersion

    return DevVersion(
        name=tmp_name,
        filename=f"{tmp_name}.json",
        url=("http://example.invalid/dev.zip" if is_zip else "http://example.invalid/dev.json"),
        sha256=hashlib.sha256(payload).hexdigest(),
        counts="test",
    )


def test_fetch_plain_json_version(tmp_path, monkeypatch):
    """计分那版（dev-1106）是 HuggingFace 上的裸 json。"""
    from bird import dataset

    payload = b'[{"question_id": 0}]'
    monkeypatch.setattr(dataset.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse(payload))

    dest = dataset.fetch(_version("v", payload), tmp_path)
    assert dest.read_bytes() == payload


def test_fetch_zip_version_also_extracts_tables(tmp_path, monkeypatch):
    """另一版在官网 dev.zip 里，顺带取出 schema 元数据。"""
    from bird import dataset

    payload = b'[{"question_id": 0}]'
    monkeypatch.setattr(dataset.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse(_fake_dev_zip(payload)))

    dest = dataset.fetch(_version("v", payload, is_zip=True), tmp_path)
    assert dest.read_bytes() == payload
    assert (tmp_path / "dev_tables.json").exists()


def test_fetch_rejects_wrong_sha256(tmp_path, monkeypatch):
    """哈希不符必须报错并且**不留下坏文件**——版本钉死是这一层的全部意义。"""
    from bird import dataset

    version = _version("v", b'[{"question_id": 0}]')
    monkeypatch.setattr(dataset.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse(b"another cleaning of dev"))
    with pytest.raises(RuntimeError, match="sha256"):
        dataset.fetch(version, tmp_path)
    assert not (tmp_path / version.filename).exists()


def test_scoring_version_is_the_one_deepseek_r1_used():
    """红线：计分用 dev-1106（对齐 DeepSeek-R1 61.67），两版都必须留着记录。"""
    from bird import paths

    assert paths.SCORING is paths.DEV_20251106
    assert set(paths.VERSIONS) == {"dev_20251106", "dev_20240627"}
    assert paths.DEV_20251106.sha256 != paths.DEV_20240627.sha256
    for version in paths.VERSIONS.values():
        assert len(version.sha256) == 64


@pytest.mark.skipif(
    not (config.DATA_DIR / "bird" / "official").exists(),
    reason="官方题目文件未就绪（python -m bird fetch）")
def test_local_official_files_match_their_pinned_hashes():
    from bird import dataset, paths

    for version in paths.VERSIONS.values():
        path = paths.dev_raw(version)
        if path.exists():
            assert dataset.sha256_of(path) == version.sha256, version.name


@pytest.mark.skipif(not (config.DATA_DIR / "bird" / "dev.json").exists(),
                    reason="数据集未转换（python -m bird convert）")
def test_converted_dataset_is_the_scoring_version():
    """红线：--data bird_dev 指向的必须是计分那一版，不能是另一版转出来的。"""
    from archer_eval.data import load_dataset
    from bird import paths

    samples = load_dataset(paths.dev_dataset())
    counts = collections.Counter(s.extras.get("difficulty") for s in samples)
    assert len(samples) == 1534
    assert counts["challenging"] == 231, "看起来是 dev_20240627 转出来的（challenging 145）"


# ---------------------------------------------------------- official prompt

def _toy_db(tmp_path):
    """造一个迷你库；同一个 tmp_path 里重复调用是幂等的。"""
    db_dir = tmp_path / "dbs" / "toy"
    db_dir.mkdir(parents=True, exist_ok=True)
    path = db_dir / "toy.sqlite"
    if path.exists():
        return tmp_path / "dbs"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    conn.execute("CREATE TABLE u (c INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(1, "x"), (2, "y"), (3, "z")])
    conn.commit()
    conn.close()
    return tmp_path / "dbs"


def _db_file(tmp_path):
    return _toy_db(tmp_path) / "toy" / "toy.sqlite"


def _sample(ck=None, question="Q"):
    return Sample(db_id="toy", query="SELECT 1", question=question,
                  commonsense_knowledge=ck)


def test_schema_ddl_block_has_all_tables(tmp_path):
    from bird.official import schema_ddl_block

    out = schema_ddl_block(_db_file(tmp_path))
    assert "CREATE TABLE t" in out and "CREATE TABLE u" in out
    assert out.count("\n\n") == 1                       # 两张表用一个空行连接


def test_schema_ddl_block_has_no_example_rows(tmp_path):
    """红线：官方 num_rows 不传，schema 块里**没有**样本行。"""
    from bird.official import schema_ddl_block

    out = schema_ddl_block(_db_file(tmp_path))
    assert "example rows" not in out
    assert "SELECT * FROM" not in out
    for value in ("'x'", "\tx", "1\t"):
        assert value not in out


def test_comment_block_with_evidence():
    from bird.official import comment_block

    out = comment_block("How many?", "rate = a / b")
    assert out == (
        "-- Using valid SQLite and understanding External Knowledge, "
        "answer the following questions for the tables provided above.\n"
        "-- How many?\n"
        "-- External Knowledge: rate = a / b"
    )


def test_comment_block_without_evidence():
    """无知识时走官方的另一条分支：措辞变短，且没有 External Knowledge 那行。"""
    from bird.official import comment_block

    for empty in (None, "", "   "):
        out = comment_block("How many?", empty)
        assert out == ("-- Using valid SQLite, answer the following questions "
                       "for the tables provided above.\n-- How many?\n")
        assert "External Knowledge" not in out


def test_official_prompt_block_order(tmp_path):
    from bird.official import COT_BLOCK, INSTRUCTION_BLOCK, official_prompt

    prompt = official_prompt(_sample("rate = a / b", "How many?"), _db_file(tmp_path))
    positions = [prompt.index(piece) for piece in (
        "CREATE TABLE t", "-- Using valid SQLite", "-- How many?",
        "-- External Knowledge:", COT_BLOCK.strip(), INSTRUCTION_BLOCK.strip())]
    assert positions == sorted(positions)
    assert prompt.endswith(INSTRUCTION_BLOCK)


def test_official_prompt_evidence_switch(tmp_path):
    from bird.official import official_prompt

    s = _sample("rate = a / b")
    assert "External Knowledge" in official_prompt(s, _db_file(tmp_path))
    assert "External Knowledge" not in official_prompt(s, _db_file(tmp_path), evidence=False)


def test_official_prompt_carries_no_unofficial_material(tmp_path):
    """红线：官方 baseline 不给列描述、不给外键、不给样本行、不给 few-shot。"""
    from bird.official import official_prompt

    prompt = official_prompt(_sample("rate = a / b"), _db_file(tmp_path))
    for banned in ("example rows", "Primary keys:", "Foreign keys:",
                   "column_description", "## ", "Example:"):
        assert banned not in prompt


# ---------------------------------------------------------- extras（非官方资料）

def _write_desc(root, db_id, table, text, encoding="utf-8-sig"):
    d = root / db_id / "database_description"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{table}.csv").write_text(text, encoding=encoding)
    return d


_GOOD_CSV = (
    "original_column_name,column_name,column_description,data_format,value_description\n"
    "CDSCode,CDSCode,CDSCode,text,\n"
    "Charter,charter school flag,whether the school is a charter,integer,\"0 = No\n"
    "1 = Yes\"\n"
    "NoDesc,,,text,\n"
)


def test_extras_are_not_exported_by_default():
    """红线：非官方资料不进 bird 的默认导出，免得有人顺手拼进官方 prompt。"""
    import bird

    for name in ("column_descriptions_block", "schema_meta_block", "load_column_docs"):
        assert name not in bird.__all__
        assert not hasattr(bird, name)


def test_load_column_docs_parses_fields(tmp_path):
    from bird.extras import load_column_docs

    _write_desc(tmp_path, "toy", "schools", _GOOD_CSV)
    docs = load_column_docs("toy", root=tmp_path)

    assert set(docs) == {"schools"}
    charter = docs["schools"]["charter"]
    assert charter.column == "Charter"           # 保留库内原名
    assert charter.nl_name == "charter school flag"
    assert charter.description == "whether the school is a charter"
    assert charter.data_format == "integer"
    assert "0 = No" in charter.value_description


def test_load_column_docs_falls_back_to_latin1(tmp_path):
    """实测有 4 个官方 CSV 不是 UTF-8，必须能读出来而不是炸掉。"""
    from bird.extras import load_column_docs

    body = ("original_column_name,column_name,column_description,data_format,"
            "value_description\nName,nom,caf\xe9 name,text,\n").encode("latin-1")
    d = tmp_path / "toy" / "database_description"
    d.mkdir(parents=True)
    (d / "t.csv").write_bytes(body)

    assert "caf" in load_column_docs("toy", root=tmp_path)["t"]["name"].description


def test_load_column_docs_tolerates_blank_header_column(tmp_path):
    """实测有 1 个官方 CSV 表头多一个空列名。"""
    from bird.extras import load_column_docs

    _write_desc(tmp_path, "toy", "t",
                "original_column_name,column_name,column_description,data_format,"
                "value_description,\nA, nl a , desc a ,text,,\n")
    doc = load_column_docs("toy", root=tmp_path)["t"]["a"]
    assert doc.nl_name == "nl a"      # 顺带验证首尾空白被 strip
    assert doc.description == "desc a"


def test_load_column_docs_missing_db_returns_empty(tmp_path):
    from bird.extras import load_column_docs

    assert load_column_docs("no_such_db", root=tmp_path) == {}


def _write_tables(tmp_path):
    path = tmp_path / "dev_tables.json"
    path.write_text(json.dumps([{
        "db_id": "toy",
        "table_names_original": ["users", "posts"],
        "table_names": ["users", "blog posts"],
        "column_names_original": [[-1, "*"], [0, "Id"], [0, "Name"], [1, "Id"], [1, "OwnerId"]],
        "column_names": [[-1, "*"], [0, "user id"], [0, "user name"],
                         [1, "post id"], [1, "owner id"]],
        "column_types": ["text", "integer", "text", "integer", "integer"],
        "primary_keys": [1, 3],
        "foreign_keys": [[4, 1]],
    }]), encoding="utf-8")
    return path


def test_load_schema_meta(tmp_path):
    from bird.extras import load_schema_meta

    meta = load_schema_meta("toy", tables_path=_write_tables(tmp_path))
    assert meta.tables == {"users": "users", "posts": "blog posts"}
    assert meta.columns["posts"]["OwnerId"] == "owner id"
    assert meta.primary_keys == {"users": ["Id"], "posts": ["Id"]}
    assert meta.foreign_keys == [("posts", "OwnerId", "users", "Id")]


def test_column_descriptions_block(tmp_path):
    from bird.extras import column_descriptions_block

    _write_desc(tmp_path, "toy", "schools", _GOOD_CSV)
    out = column_descriptions_block("toy", root=tmp_path)

    assert "## schools" in out and "`Charter`" in out and "(integer)" in out
    assert "0 = No" in out                     # value_description 默认带上
    assert "NoDesc" not in out                 # 三样都空的列不占篇幅
    assert column_descriptions_block("nope", root=tmp_path) == ""


def test_column_descriptions_block_switches(tmp_path):
    from bird.extras import column_descriptions_block

    _write_desc(tmp_path, "toy", "schools", _GOOD_CSV)
    _write_desc(tmp_path, "toy", "frpm", _GOOD_CSV)

    assert "0 = No" not in column_descriptions_block("toy", root=tmp_path, with_values=False)
    only = column_descriptions_block("toy", root=tmp_path, tables=["SCHOOLS"])  # 大小写不敏感
    assert "## schools" in only and "## frpm" not in only
    clipped = column_descriptions_block("toy", root=tmp_path, max_chars=40)
    assert clipped.endswith("... (truncated)")


def test_data_format_block(tmp_path):
    from bird.extras import data_format_block

    _write_desc(tmp_path, "toy", "schools", _GOOD_CSV)
    out = data_format_block("toy", root=tmp_path)
    assert "schools.Charter: integer" in out and "schools.CDSCode: text" in out
    assert data_format_block("nope", root=tmp_path) == ""


def test_schema_meta_block(tmp_path):
    from bird.extras import schema_meta_block

    path = _write_tables(tmp_path)
    out = schema_meta_block("toy", tables_path=path)
    assert "blog posts" in out and "posts.OwnerId -> users.Id" in out
    assert "blog posts" not in schema_meta_block("toy", tables_path=path, with_nl_names=False)
    assert schema_meta_block("nope", tables_path=path) == ""


# ---------------------------------------------------------- evaluate（官方口径）

def test_rows_match_is_order_insensitive_across_rows():
    from bird.evaluate import rows_match

    assert rows_match([(1, "a"), (2, "b")], [(2, "b"), (1, "a")])


def test_rows_match_is_order_sensitive_within_a_row():
    """官方是 set(list_of_tuples)：列序变了就是不同的元组。"""
    from bird.evaluate import rows_match

    assert not rows_match([(1, "a")], [("a", 1)])


def test_rows_match_collapses_duplicates():
    """官方用 set()，重复行被折叠——这是刻意复刻，不是 bug。"""
    from bird.evaluate import rows_match

    assert rows_match([(1,), (1,)], [(1,)])


def _bird_samples():
    return [
        Sample(db_id="toy", query="SELECT a FROM t WHERE a < 3", question="Q0",
               extras={"question_id": 0, "difficulty": "simple"}),
        Sample(db_id="toy", query="SELECT b FROM t ORDER BY a", question="Q1",
               extras={"question_id": 1, "difficulty": "moderate"}),
        Sample(db_id="toy", query="SELECT a, b FROM t WHERE a = 1", question="Q2",
               extras={"question_id": 2, "difficulty": "challenging"}),
    ]


def test_evaluate_bird_scores_and_stratifies(tmp_path):
    from bird.evaluate import evaluate_bird

    report = evaluate_bird(_bird_samples(), [
        "SELECT a FROM t WHERE a <= 2",    # 对（行序无关）
        "SELECT a FROM t",                 # 错（选错列）
        "SELECT a, b FROM t WHERE a = 1",  # 对
    ], _toy_db(tmp_path))

    assert report["summary"]["n"] == 3
    assert report["summary"]["n_match"] == 2
    assert report["by_difficulty"]["simple"]["EX"] == 1.0
    assert report["by_difficulty"]["moderate"]["EX"] == 0.0
    assert list(report["by_difficulty"]) == ["simple", "moderate", "challenging"]
    assert report["by_db"]["toy"]["n"] == 3
    assert report["samples"][0]["question_id"] == 0


def test_evaluate_bird_counts_broken_sql_as_zero(tmp_path):
    from bird.evaluate import evaluate_bird

    report = evaluate_bird(
        _bird_samples(),
        ["SELECT nope FROM t", "", "SELECT a, b FROM t WHERE a = 1"],
        _toy_db(tmp_path))

    assert report["summary"]["n_match"] == 1
    assert report["samples"][0]["error"]           # 记下报错，但不另设 VA
    assert report["samples"][1]["error"] == "empty prediction"


def test_evaluate_bird_has_no_tied_path():
    """红线：官方脚本不读 dev_tied_append.json，我们也不留这条支路。"""
    from bird import evaluate

    src = Path(evaluate.__file__).read_text(encoding="utf-8")
    assert "tied" not in src.lower()


def test_evaluate_bird_meta_declares_deviations(tmp_path):
    from bird.evaluate import evaluate_bird

    report = evaluate_bird(_bird_samples()[:1], ["SELECT a FROM t WHERE a < 3"],
                           _toy_db(tmp_path))
    assert report["meta"]["protocol"] == "bird-official"
    assert len(report["meta"]["deviations"]) == 3


def test_evaluate_bird_gold_failure_scores_zero(tmp_path):
    """gold 自己跑不出来的题（dev 已知 2 道）在官方口径下恒为 0。"""
    from bird.evaluate import evaluate_bird

    samples = [Sample(db_id="toy", query="SELECT bogus FROM t", question="Q",
                      extras={"question_id": 9, "difficulty": "simple"})]
    report = evaluate_bird(samples, ["SELECT a FROM t"], _toy_db(tmp_path))
    assert report["summary"]["n_match"] == 0
    assert report["samples"][0]["error"].startswith("gold:")


def test_evaluate_bird_shares_one_timeout_budget(tmp_path):
    """预测把预算耗光后，不再另给 gold 一份——对齐官方那一次 func_timeout。"""
    from bird.evaluate import evaluate_bird_sample

    sample = _bird_samples()[0]
    result = evaluate_bird_sample(sample, "SELECT a FROM t WHERE a < 3",
                                  _toy_db(tmp_path), timeout_s=0.0)
    assert result.match is False
    assert result.error is not None


def test_evaluate_bird_rejects_length_mismatch(tmp_path):
    from bird.evaluate import evaluate_bird

    with pytest.raises(ValueError):
        evaluate_bird(_bird_samples(), ["SELECT 1"], _toy_db(tmp_path))


# ---------------------------------------------------------- 官方脚本适配器

def test_vendored_official_script_is_present_and_unmodified():
    """红线：vendor 的官方脚本是判分的权威，判分那 3 行必须原样在。"""
    from bird.official_eval import adapter

    src = adapter.SCRIPT.read_text(encoding="utf-8")
    assert "set(predicted_res) == set(ground_truth_res)" in src
    assert "func_timeout" in src
    assert adapter.SCRIPT.with_name("SOURCE.md").exists()


def test_adapter_writes_official_input_formats(tmp_path):
    from bird.official_eval.adapter import SEPARATOR, write_inputs

    samples = [Sample(db_id="toy", query="SELECT a\n  FROM t", question="Q",
                      extras={"question_id": 0, "difficulty": "simple"})]
    pred_path, gold_path = write_inputs(samples, ["SELECT\n a FROM t"], tmp_path)

    assert json.loads(pred_path.read_text(encoding="utf-8")) == {
        "0": f"SELECT a FROM t{SEPARATOR}toy"}
    # gold 是按行读的：换行必须压掉，否则整份文件串行
    assert gold_path.read_text(encoding="utf-8") == "SELECT a FROM t\ttoy\n"


def test_strip_sql_comments_protects_string_literals():
    from bird.official_eval.adapter import strip_sql_comments

    assert strip_sql_comments("SELECT a -- keep only this\nFROM t").split() == [
        "SELECT", "a", "FROM", "t"]
    assert strip_sql_comments("SELECT /* block */ a FROM t").split() == [
        "SELECT", "a", "FROM", "t"]
    # 字面量里的 -- 和 /* 不是注释
    assert strip_sql_comments("SELECT '--x' FROM t") == "SELECT '--x' FROM t"
    assert strip_sql_comments("SELECT `a--b` FROM t") == "SELECT `a--b` FROM t"
    assert strip_sql_comments("SELECT 'it''s --ok' FROM t") == "SELECT 'it''s --ok' FROM t"


def test_adapter_flattens_comment_bearing_gold_without_truncating_it(tmp_path):
    """dev-1106 有 4 条 gold 带 `--` 行注释；压平前不去注释会把整条查询注释掉。"""
    from bird.official_eval.adapter import write_inputs

    gold = "SELECT a\nFROM t\nWHERE a > 1 -- only big ones\nORDER BY a"
    samples = [Sample(db_id="toy", query=gold, question="Q",
                      extras={"question_id": 0, "difficulty": "challenging"})]
    _, gold_path = write_inputs(samples, ["SELECT a FROM t"], tmp_path)

    line = gold_path.read_text(encoding="utf-8").splitlines()[0]
    assert line == "SELECT a FROM t WHERE a > 1 ORDER BY a\ttoy"
    assert "--" not in line


def test_adapter_writes_difficulty_file(tmp_path):
    from bird.official_eval.adapter import write_difficulty

    path = write_difficulty(_bird_samples(), tmp_path)
    assert [d["difficulty"] for d in json.loads(path.read_text(encoding="utf-8"))] == [
        "simple", "moderate", "challenging"]


_OFFICIAL_STDOUT = """start calculate
                     simple               moderate             challenging          total
count                860                  443                  231                  1534
======================================    ACCURACY    =====================================
accuracy             65.00                50.00                30.00                55.02
"""


def test_adapter_parses_official_table():
    from bird.official_eval.adapter import parse_output

    report = parse_output(_OFFICIAL_STDOUT)
    assert report["summary"]["n"] == 1534
    assert report["summary"]["EX_pct"] == 55.02
    assert report["summary"]["n_match"] == round(1534 * 0.5502)
    assert report["by_difficulty"]["simple"] == {"n": 860, "EX_pct": 65.0, "n_match": 559}


def test_adapter_refuses_to_guess_on_unparsable_output():
    from bird.official_eval.adapter import parse_output

    with pytest.raises(RuntimeError):
        parse_output("something went wrong")


# ---------------------------------------------------------- scores

def test_scores_renders_table(tmp_path):
    from bird.scores import load_reports, render

    (tmp_path / "a.json").write_text(json.dumps({
        "meta": {"protocol": "bird-official-script"},
        "summary": {"n": 1534, "n_match": 900, "EX_pct": 58.67},
        "by_difficulty": {"simple": {"n": 860, "EX_pct": 70.0},
                          "moderate": {"n": 443, "EX_pct": 45.0},
                          "challenging": {"n": 231, "EX_pct": 30.0}},
    }), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    table = render(load_reports(tmp_path))
    assert "| a | 官方脚本 | 1534 | **58.67** | 70.00 | 45.00 | 30.00 |" in table
    assert "broken" not in table


def test_scores_handles_empty_dir(tmp_path):
    from bird.scores import load_reports, render

    assert "还没有报告" in render(load_reports(tmp_path))


# ---------------------------------------------------------- 模型档位

class _FakeEndpoint:
    def __init__(self, reply="SELECT 1"):
        self.reply = reply
        self.calls = []

    def chat_messages(self, messages, **overrides):
        self.calls.append(messages)
        return self.reply

    def chat(self, system, user, **overrides):        # 不该被调用
        raise AssertionError("BIRD 档位必须走 chat_messages，官方没有 system message")


def _bird_model(reply="SELECT 1"):
    from model.bird import BirdDirect

    model = object.__new__(BirdDirect)
    model._endpoint = _FakeEndpoint(reply)
    return model


def test_bird_model_registered():
    from model import MODELS
    from model.bird import BirdDirect

    assert MODELS["bird-pro-t-direct"] is BirdDirect


def test_bird_model_sends_one_user_message_with_official_prompt(tmp_path, monkeypatch):
    from bird.official import official_prompt
    from model.fewshot.store import SelectionStore

    def forbid_selection_load(cls, path):
        raise AssertionError(f"baseline touched few-shot selection: {path}")

    monkeypatch.setattr(SelectionStore, "from_path", classmethod(forbid_selection_load))
    model = _bird_model("```sql\nSELECT a FROM t\n```")
    sample = _sample("rate = a / b")
    db_path = _db_file(tmp_path)
    sql = model.predict(sample, db_path)

    assert sql == "SELECT a FROM t"                    # markdown 围栏被剥掉
    messages = model._endpoint.calls[0]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    body = messages[0]["content"]
    assert body == official_prompt(sample, db_path)
    assert "CREATE TABLE t" in body
    assert "-- External Knowledge: rate = a / b" in body
    assert "example rows" not in body


def test_bird_model_evidence_switch(tmp_path):
    model = _bird_model()
    model.use_evidence = False
    model.predict(_sample("rate = a / b"), _db_file(tmp_path))
    assert "External Knowledge" not in model._endpoint.calls[0][0]["content"]


def test_bird_model_request_params_match_the_official_setup():
    """thinking 开着；不发 temperature / stop / max_tokens（偏离清单见 docs/BIRD.md）。"""
    from model.bird import BirdDirect

    assert BirdDirect.request_params == {"extra_body": {"thinking": {"type": "enabled"}}}
    assert BirdDirect.model == "deepseek-v4-pro"
    assert BirdDirect.use_evidence is True


def test_bird_direct_does_not_touch_archer_prompting():
    """红线：**榜单可比的那个直出档位**不掺 Archer 的 CT-3 提示词与约定表。

    作用域收窄过一次（原先查整个 model/bird.py）：`BirdProTDsl` 落进同一个
    文件后，"整份文件不许出现 CT-3"就不再成立——那一档的价值恰恰是把 Archer
    主线的声明层（含带样本行的 schema）原样搬到 BIRD 上测泛化。红线要守的是
    `BirdDirect` 与官方 baseline 逐字对齐，所以改成只查它自己的源码。
    """
    from model.bird import BirdDirect

    src = inspect.getsource(BirdDirect)
    assert "build_ct3_prompt" not in src
    assert "schema_with_rows" not in src
    assert "conventions" not in src


def test_bird_fewshot_variant_keeps_official_prompt_as_suffix(tmp_path):
    from bird.official import official_prompt
    from model.bird import BirdDirectFewShot
    from model.fewshot.store import SelectionStore, sample_key
    from model.fewshot.types import FewShotExample, SelectedExample, SelectionRecord

    sample = _sample("rate = a / b", question="Compute the rate.")
    db_path = _db_file(tmp_path)
    key = sample_key(sample.db_id, sample.question)
    record = SelectionRecord(
        target_key=key,
        corpus="bird_train",
        encoder="sentence-transformers/all-mpnet-base-v2",
        k=3,
        examples=tuple(
            SelectedExample(
                example=FewShotExample(
                    source_id=f"bird_train:{index}",
                    db_id="reference_db",
                    question=f"Reference question {index}?",
                    sql=f"SELECT {index}",
                ),
                distance=float(index),
            )
            for index in range(3)
        ),
    )
    model = object.__new__(BirdDirectFewShot)
    model._endpoint = _FakeEndpoint()
    model._fewshot_store = SelectionStore(records={key: record})

    model.predict(sample, db_path)

    messages = model._endpoint.calls[0]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    sent = messages[0]["content"]
    assert sent.startswith("### Retrieved examples")
    assert sent.endswith(official_prompt(sample, db_path))


def test_bird_fewshot_variant_is_single_variable_and_registered():
    from model import MODELS
    from model.bird import BirdDirect, BirdDirectFewShot

    assert MODELS["bird-pro-t-direct-fs"] is BirdDirectFewShot
    assert issubclass(BirdDirectFewShot, BirdDirect)
    assert {
        key for key in BirdDirectFewShot.__dict__ if not key.startswith("_")
    } == {"name", "fewshot_selection"}
    for attr in (
        "base_url",
        "model",
        "key_env",
        "request_params",
        "conventions",
        "use_evidence",
    ):
        assert getattr(BirdDirectFewShot, attr) == getattr(BirdDirect, attr), attr


# ------------------------------------------------- bird-pro-t-dsl（泛化臂）

def test_bird_dsl_registered():
    from model import MODELS
    from model.bird import BirdProTDsl

    assert MODELS["bird-pro-t-dsl"] is BirdProTDsl


def test_bird_dsl_fewshot_variant_is_single_variable_and_registered():
    from model import MODELS
    from model.bird import BirdProTDsl, BirdProTDslFewShot

    assert MODELS["bird-pro-t-dsl-fs"] is BirdProTDslFewShot
    assert issubclass(BirdProTDslFewShot, BirdProTDsl)
    assert {
        key for key in BirdProTDslFewShot.__dict__ if not key.startswith("_")
    } == {"name", "fewshot_selection"}
    assert BirdProTDslFewShot.evidence is True
    assert BirdProTDslFewShot.use_plan is False


def test_bird_dsl_switch_matrix_is_pro_t_dsl_plus_evidence():
    """唯一变量红线：相对主线 `pro-t-dsl` 只有 evidence 一处不同。

    逐个断言而不是"跟 ProTDsl 比 __dict__"——开关是继承来的类属性，比 dict
    会漏掉没被覆写的那些，而"某个开关被静默打开"正是这里要防的事
    （f086cee 修的就是归档分支漏转发开关）。
    """
    from model.bird import BirdProTDsl
    from model.pipeline.models import ProTDsl

    assert BirdProTDsl.evidence is True and ProTDsl.evidence is False
    assert BirdProTDsl.dataset == "bird_dev"
    assert BirdProTDsl.use_plan is False
    assert BirdProTDsl.max_repairs == 2
    for switch in ("knowledge", "learned_rules", "sqlens_checks",
                   "conventions", "extra_checks", "convention_checks",
                   "use_profile", "force_considered"):
        assert getattr(BirdProTDsl, switch) is False, switch
    # 骨干与 bird-pro-t-direct 同底（deepseek-v4-pro + thinking）
    assert BirdProTDsl.endpoint_spec["model"] == "deepseek-v4-pro"
    assert BirdProTDsl.endpoint_spec["request_params"] == {
        "extra_body": {"thinking": {"type": "enabled"}}}


def test_bird_dsl_goes_through_mainline_declare_stage_with_evidence_on():
    """走主线 DeclareStage（不是归档适配层），且 evidence 真的转发下去了。"""
    from model.bird import BirdProTDsl
    from model.pipeline.stages.declare import DeclareStage

    inst = BirdProTDsl.__new__(BirdProTDsl)
    inst.endpoint = object()
    stages = inst._stages()
    [declare] = [s for s in stages if isinstance(s, DeclareStage)]
    assert type(declare) is DeclareStage          # 归档层是子类，这里必须是本尊
    assert declare.evidence is True
    assert declare.use_plan is False
    assert declare.knowledge is False and declare.sqlens_checks is False
    assert declare._rules == []                   # learned_rules 关 => 不加载规则库


def test_bird_dsl_user_message_is_archer_baseline_plus_one_evidence_line():
    """消息级红线：evidence 只往 user 消息里加一行 `Evidence: ...`，别的逐字节不变。

    这条把"唯一变量"从类属性落到实际发出去的字节上——开关矩阵对了但模板渲染
    错了（比如 evidence 顺手改了 schema 段），单靠上一条测试看不出来。
    """
    from model.pipeline.context import PipelineContext
    from model.pipeline.stages.declare import DeclareStage
    from model.pipeline.templates import render

    ctx = PipelineContext(question="how many?", db_path=Path("."))
    ctx.evidence = "rate = a / b"
    ctx.schema = "CREATE TABLE t (a int);"

    on = DeclareStage(object(), 2, dataset="bird_dev", evidence=True, use_plan=False)
    off = DeclareStage(object(), 2, dataset="en_train", evidence=False, use_plan=False)
    body = dict(schema=ctx.schema, question=ctx.question)
    msg_on = render("dslgen.user.noplan", **body, evidence=on._evidence_block(ctx))
    msg_off = render("dslgen.user.noplan", **body, evidence=off._evidence_block(ctx))

    assert "Evidence: rate = a / b" in msg_on
    assert "Evidence" not in msg_off
    # 去掉那一行后两者逐字节相同
    assert msg_on.replace("Evidence: rate = a / b", "") == msg_off


def test_bird_dsl_system_message_is_the_untouched_baseline():
    """system 侧一个字都不该多——knowledge/conventions 全关时就是裸模板。"""
    from model.pipeline.stages.declare import DeclareStage
    from model.pipeline.templates import load_template

    stage = DeclareStage(object(), 2, dataset="bird_dev", evidence=True, use_plan=False)
    assert stage._system() == load_template("dslgen.system")


# ---------------------------------------------------------- 断点续跑

class _CountingGenerator:
    name = "fake"

    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.seen = []

    def predict_all(self, samples, db_paths, progress=True):
        out = []
        for s in samples:
            self.seen.append(s.question)
            if self.fail_at is not None and len(self.seen) > self.fail_at:
                raise RuntimeError("boom")
            out.append(f"SELECT '{s.question}'")
        return out


def _samples(n):
    return [Sample(db_id="toy", query="SELECT 1", question=f"q{i}") for i in range(n)]


def test_checkpoint_resumes_after_a_crash(tmp_path):
    from model.__main__ import _run_with_checkpoint

    out = tmp_path / "fake_data.json"
    samples, db_paths = _samples(6), [tmp_path] * 6

    crashing = _CountingGenerator(fail_at=4)
    with pytest.raises(RuntimeError):
        _run_with_checkpoint(crashing, samples, db_paths, out, chunk=2)

    resumed = _CountingGenerator()
    predictions, _ = _run_with_checkpoint(resumed, samples, db_paths, out, chunk=2)

    assert predictions == [f"SELECT 'q{i}'" for i in range(6)]
    assert resumed.seen == ["q4", "q5"]          # 前两块没有重跑


def test_limited_run_then_full_run_only_fills_the_rest(tmp_path):
    """先跑前 N 题、之后跑全量，前 N 题必须直接复用，不重跑、不重复计费。"""
    from model.__main__ import _run_with_checkpoint

    out = tmp_path / "fake_data.json"
    samples, db_paths = _samples(10), [tmp_path] * 10

    first = _CountingGenerator()
    head, _ = _run_with_checkpoint(first, samples[:4], db_paths[:4], out, chunk=2,
                                   alias="data", total=10)
    assert len(head) == 4 and first.seen == ["q0", "q1", "q2", "q3"]

    rest = _CountingGenerator()
    full, _ = _run_with_checkpoint(rest, samples, db_paths, out, chunk=2,
                                   alias="data", total=10)

    assert full == [f"SELECT 'q{i}'" for i in range(10)]
    assert rest.seen == [f"q{i}" for i in range(4, 10)]     # 前 4 题没有重跑


def test_checkpoint_ignores_a_run_with_a_different_fingerprint(tmp_path):
    from model.__main__ import _checkpoint_path, _run_with_checkpoint

    out = tmp_path / "fake_data.json"
    # 手工留下一个别的运行的断点（数据集不同）
    _checkpoint_path(out).write_text(
        json.dumps({"model": "fake", "data": "other", "n": 4})
        + '\n{"i": 0, "sql": "STALE"}\n',
        encoding="utf-8")

    fresh = _CountingGenerator()
    predictions, _ = _run_with_checkpoint(fresh, _samples(4), [tmp_path] * 4, out, chunk=2)
    assert "STALE" not in predictions
    assert len(fresh.seen) == 4


def test_checkpoint_disabled_writes_no_file(tmp_path):
    from model.__main__ import _checkpoint_path, _run_with_checkpoint

    out = tmp_path / "fake_data.json"
    predictions, _ = _run_with_checkpoint(_CountingGenerator(), _samples(3),
                                          [tmp_path] * 3, out, chunk=0)
    assert len(predictions) == 3
    assert not _checkpoint_path(out).exists()


# ---------------------------------------------------------- CLI

def _mini_dataset(tmp_path, query="SELECT a FROM t WHERE a < 3"):
    data = tmp_path / "mini.json"
    data.write_text(json.dumps([
        {"db_id": "toy", "question": "Q0", "query": query,
         "question_id": 0, "difficulty": "simple"},
    ]), encoding="utf-8")
    return data


def test_cli_eval_writes_report(tmp_path, capsys):
    from bird.__main__ import main

    db_dir = _toy_db(tmp_path)
    data = _mini_dataset(tmp_path)
    pred = tmp_path / "p.json"
    pred.write_text(json.dumps(["SELECT a FROM t WHERE a <= 2"]), encoding="utf-8")

    rc = main(["eval", "--data", str(data), "--pred", str(pred),
               "--db-dir", str(db_dir), "--out-dir", str(tmp_path / "out")])

    assert rc == 0
    report = json.loads((tmp_path / "out" / "mini_p.json").read_text(encoding="utf-8"))
    assert report["summary"]["n_match"] == 1
    assert report["meta"]["pred"] == str(pred)
    assert "EX" in capsys.readouterr().out


def test_cli_eval_gold_as_pred(tmp_path):
    from bird.__main__ import main

    rc = main(["eval", "--data", str(_mini_dataset(tmp_path)), "--gold-as-pred",
               "--db-dir", str(_toy_db(tmp_path)), "--out-dir", str(tmp_path / "out")])
    assert rc == 0
    report = json.loads((tmp_path / "out" / "mini_gold.json").read_text(encoding="utf-8"))
    assert report["summary"]["EX"] == 1.0


def test_cli_preview_prints_the_official_prompt(tmp_path, capsys, monkeypatch):
    from bird.__main__ import main

    db_dir = _toy_db(tmp_path)
    monkeypatch.setattr(config, "db_dir_for", lambda _: db_dir)
    assert main(["preview", "--data", str(_mini_dataset(tmp_path)), "--index", "0"]) == 0

    out = capsys.readouterr().out
    assert "CREATE TABLE t" in out
    assert "-- Using valid SQLite" in out


def test_cli_requires_exactly_one_prediction_source(tmp_path):
    from bird.__main__ import main

    with pytest.raises(SystemExit):
        main(["eval", "--data", str(_mini_dataset(tmp_path))])


def test_cli_rejects_prediction_count_mismatch(tmp_path):
    from bird.__main__ import main

    pred = tmp_path / "p.json"
    pred.write_text(json.dumps(["SELECT 1", "SELECT 2"]), encoding="utf-8")
    with pytest.raises(ValueError):
        main(["eval", "--data", str(_mini_dataset(tmp_path)), "--pred", str(pred),
              "--db-dir", str(_toy_db(tmp_path)), "--out-dir", str(tmp_path / "out")])
