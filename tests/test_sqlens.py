"""SQLens 静态信号（arXiv 2506.04494 的 database-based signals）。"""

import sqlite3

import pytest
import sqlglot


def _tree(sql):
    return sqlglot.parse_one(sql, dialect="sqlite")


@pytest.fixture
def db(tmp_path):
    """两张表：city(Name, District)、country(Name, Population)。
    'Kang-won' 只在 city.District 里，不在任何 Name 列里。
    """
    p = tmp_path / "t.sqlite"
    conn = sqlite3.connect(p)
    conn.executescript("""
        CREATE TABLE country (Code TEXT PRIMARY KEY, Name TEXT, Population INT);
        CREATE TABLE city (ID INT PRIMARY KEY, Name TEXT, District TEXT,
                           CountryCode TEXT REFERENCES country(Code));
        INSERT INTO country VALUES ('KOR', 'South Korea', 46844000);
        INSERT INTO city VALUES (1, 'Chunchon', 'Kang-won', 'KOR');
        INSERT INTO city VALUES (2, 'Seoul', 'Seoul', 'KOR');
    """)
    conn.commit()
    conn.close()
    return p


# ---------------------------------------------------------------- S2（最简，先测）

def test_s2_flags_groupby_without_aggregate():
    from model.pipeline.dsl.checks import _s2_groupby_without_aggregate
    issues = _s2_groupby_without_aggregate(_tree("SELECT a FROM t GROUP BY a"))
    assert len(issues) == 1 and "GROUP BY" in issues[0]


def test_s2_silent_when_aggregate_present():
    from model.pipeline.dsl.checks import _s2_groupby_without_aggregate
    assert _s2_groupby_without_aggregate(
        _tree("SELECT a, COUNT(*) FROM t GROUP BY a")) == []


def test_s2_silent_without_groupby():
    from model.pipeline.dsl.checks import _s2_groupby_without_aggregate
    assert _s2_groupby_without_aggregate(_tree("SELECT a FROM t")) == []


# ---------------------------------------------------------------- S1

def test_s1_flags_literal_that_lives_in_another_column(db):
    from model.pipeline.dsl.checks import _s1_value_ambiguity
    from model.pipeline.dsl import load_schema_info
    tree = _tree("SELECT ID FROM city WHERE Name = 'Kang-won'")
    issues = _s1_value_ambiguity(tree, load_schema_info(db), db)
    assert len(issues) == 1
    assert "District" in issues[0]


def test_s1_silent_when_literal_is_in_the_used_column(db):
    from model.pipeline.dsl.checks import _s1_value_ambiguity
    from model.pipeline.dsl import load_schema_info
    tree = _tree("SELECT ID FROM city WHERE Name = 'Seoul'")
    assert _s1_value_ambiguity(tree, load_schema_info(db), db) == []


def test_s1_silent_when_literal_is_nowhere(db):
    """值哪儿都没有 => 是 C3 近邻检查的活，S1 不重复报。"""
    from model.pipeline.dsl.checks import _s1_value_ambiguity
    from model.pipeline.dsl import load_schema_info
    tree = _tree("SELECT ID FROM city WHERE Name = 'Atlantis'")
    assert _s1_value_ambiguity(tree, load_schema_info(db), db) == []


# ---------------------------------------------------------------- S3

def test_foreign_key_pairs_reads_schema(db):
    from model.pipeline.dsl.checks import foreign_key_pairs
    assert frozenset({"countrycode", "code"}) in foreign_key_pairs(db)


def test_s3_flags_join_not_on_foreign_key(db):
    from model.pipeline.dsl.checks import _s3_join_predicate
    tree = _tree("SELECT c.ID FROM city c JOIN country o ON c.Name = o.Name")
    issues = _s3_join_predicate(tree, db)
    assert len(issues) == 1 and "外键" in issues[0]


def test_s3_silent_on_foreign_key_join(db):
    from model.pipeline.dsl.checks import _s3_join_predicate
    tree = _tree("SELECT c.ID FROM city c JOIN country o ON c.CountryCode = o.Code")
    assert _s3_join_predicate(tree, db) == []


def test_s3_silent_without_join(db):
    from model.pipeline.dsl.checks import _s3_join_predicate
    assert _s3_join_predicate(_tree("SELECT a FROM city"), db) == []


# ---------------------------------------------------------------- S4

def test_s4_flags_equality_against_multirow_subquery(db):
    from model.pipeline.dsl.checks import _s4_subquery_equality
    tree = _tree("SELECT Name FROM city WHERE CountryCode = "
                 "(SELECT CountryCode FROM city)")
    issues = _s4_subquery_equality(tree, db)
    assert len(issues) == 1 and "IN" in issues[0]


def test_s4_silent_on_single_row_subquery(db):
    from model.pipeline.dsl.checks import _s4_subquery_equality
    tree = _tree("SELECT Name FROM city WHERE CountryCode = "
                 "(SELECT Code FROM country WHERE Name = 'South Korea')")
    assert _s4_subquery_equality(tree, db) == []


def test_s4_silent_without_subquery(db):
    from model.pipeline.dsl.checks import _s4_subquery_equality
    assert _s4_subquery_equality(_tree("SELECT Name FROM city"), db) == []


# ---------------------------------------------------------------- S5

def test_s5_flags_predicate_matching_zero_rows(db):
    from model.pipeline.dsl.checks import _s5_empty_predicate
    from model.pipeline.dsl import load_schema_info
    tree = _tree("SELECT ID FROM city WHERE District = 'Atlantis'")
    issues = _s5_empty_predicate(tree, load_schema_info(db), db)
    assert len(issues) == 1 and "Atlantis" in issues[0]


def test_s5_silent_on_matching_predicate(db):
    from model.pipeline.dsl.checks import _s5_empty_predicate
    from model.pipeline.dsl import load_schema_info
    tree = _tree("SELECT ID FROM city WHERE District = 'Kang-won'")
    assert _s5_empty_predicate(tree, load_schema_info(db), db) == []


# ---------------------------------------------------------------- S6

def test_s6_flags_empty_result(db):
    from model.pipeline.dsl.checks import _s6_abnormal_result
    issues = _s6_abnormal_result("SELECT Name FROM city WHERE ID = 999", db)
    assert len(issues) == 1 and "空" in issues[0]


def test_s6_flags_all_null_column(db):
    from model.pipeline.dsl.checks import _s6_abnormal_result
    issues = _s6_abnormal_result(
        "SELECT AVG(Population) FROM country WHERE Code = 'ZZZ'", db)
    assert any("NULL" in x for x in issues)


def test_s6_silent_on_normal_result(db):
    from model.pipeline.dsl.checks import _s6_abnormal_result
    assert _s6_abnormal_result("SELECT Name FROM city", db) == []


def test_s6_silent_on_execution_error(db):
    """执行报错交给别的机制处理，S6 不重复报。"""
    from model.pipeline.dsl.checks import _s6_abnormal_result
    assert _s6_abnormal_result("SELECT nope FROM nowhere", db) == []


# ---------------------------------------------------------------- 统一入口

def test_sqlens_issues_returns_all_six_keys(db):
    from model.pipeline.dsl.checks import sqlens_issues
    from model.pipeline.dsl import load_schema_info
    sql = "SELECT Name FROM city"
    out = sqlens_issues(_tree(sql), sql, "list cities", load_schema_info(db), db)
    assert set(out) == {"S1", "S2", "S3", "S4", "S5", "S6"}
    assert all(isinstance(v, list) for v in out.values())


def test_sqlens_issues_survives_broken_database(tmp_path):
    """库打不开时静默返回空，绝不因为检查器自己出错而阻断主流程。"""
    from model.pipeline.dsl.checks import sqlens_issues
    bad = tmp_path / "nope.sqlite"
    sql = "SELECT a FROM t"
    out = sqlens_issues(_tree(sql), sql, "q", {}, bad)
    assert set(out) == {"S1", "S2", "S3", "S4", "S5", "S6"}
    assert all(v == [] for v in out.values())


def test_sqlens_issues_only_runs_enabled_signals(db, monkeypatch):
    """ENABLED_SQLENS 收窄后，未启用的信号即便本会触发也必须保持沉默。"""
    from model.pipeline.dsl import checks
    from model.pipeline.dsl import load_schema_info
    monkeypatch.setattr(checks, "ENABLED_SQLENS", ("S2",))
    sql = "SELECT ID FROM city WHERE Name = 'Kang-won'"   # S1 本会触发
    out = checks.sqlens_issues(_tree(sql), sql, "q", load_schema_info(db), db)
    assert out["S1"] == []
    assert set(out) == {"S1", "S2", "S3", "S4", "S5", "S6"}


def test_sqlens_issues_default_matches_enabled_sqlens(db):
    """不传 enabled 参数时（线上主流程的调用方式），必须精确复刻当前的
    ENABLED_SQLENS 闸门——S1 不在里面，即使这条 SQL 本会触发它，也必须沉默。
    这里刻意不 monkeypatch，用的是 checks.py 里真实的出厂 ENABLED_SQLENS。
    """
    from model.pipeline.dsl.checks import sqlens_issues
    from model.pipeline.dsl import load_schema_info
    sql = "SELECT ID FROM city WHERE Name = 'Kang-won'"   # S1 本会触发
    out = sqlens_issues(_tree(sql), sql, "q", load_schema_info(db), db)
    assert out["S1"] == []


def test_sqlens_issues_enabled_param_overrides_gate_for_offline_remeasurement(
        db, monkeypatch):
    """scripts/measure_checks.py 靠显式传 `enabled=ALL_SQLENS` 才能重测被
    ENABLED_SQLENS 挡住的信号（如 S1）——这条测试锁死这条后门确实能打开。
    monkeypatch 把 ENABLED_SQLENS 收得比默认更窄，证明起作用的是显式传参，
    不是恰好没被收窄。
    """
    from model.pipeline.dsl import checks
    from model.pipeline.dsl import load_schema_info
    monkeypatch.setattr(checks, "ENABLED_SQLENS", ("S2",))
    sql = "SELECT ID FROM city WHERE Name = 'Kang-won'"   # S1 本会触发
    out = checks.sqlens_issues(_tree(sql), sql, "q", load_schema_info(db), db,
                               enabled=checks.ALL_SQLENS)
    assert len(out["S1"]) == 1 and "District" in out["S1"][0]


def test_sqlens_issues_catches_probe_exception(tmp_path):
    """库不存在时，`SELECT a FROM t` 没有任何 WHERE 条件，S1/S3/S5 都在各自的
    `if not pairs/joins` 早退处提前返回，根本不会碰 sqlite3.connect——上面那条
    test_sqlens_issues_survives_broken_database 测的其实是"提前短路"这条路径，
    不是异常捕获路径。这里换一条带 `WHERE b = 'x'` 谓词的 SQL：`_s1_value_ambiguity`
    的 `pairs` 非空，会跳过早退、直接执行裸 `sqlite3.connect(...)`，在库不存在时
    真的抛出 `sqlite3.OperationalError`——这才是 sqlens_issues 里
    `try/except Exception` 实际需要接住的路径。
    """
    from model.pipeline.dsl.checks import sqlens_issues
    bad = tmp_path / "nope.sqlite"
    sql = "SELECT a FROM t WHERE b = 'x'"
    out = sqlens_issues(_tree(sql), sql, "q", {}, bad)
    assert set(out) == {"S1", "S2", "S3", "S4", "S5", "S6"}
    assert all(v == [] for v in out.values())
