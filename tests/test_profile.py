"""库画像生成器：打真实库（只读），断言四类规则的命中与不命中。

打真库而不是造玩具库，是因为这些规则的价值全在"在真实 schema 上不误报"——
玩具库测不出 Average/Percentage 的子串陷阱，也测不出事件表与快照表的区别。
"""

from pathlib import Path

import pytest

from model.pipeline.profile import build_profile, numeric_columns

DB = Path(__file__).resolve().parents[1] / "database"

ALL_DBS = ["concert_singer", "world_1", "formula_1", "soccer_1", "bike_1",
           "wine_1", "hospital_1", "riding_club", "driving_school",
           "customers_and_products_contacts"]


def _profile(name: str) -> list[str]:
    return build_profile(DB / name / f"{name}.sqlite")


def test_stock_age_column_detected():
    """concert_singer.singer 有 Age 但无出生日期列 -> 必须报存量时点列。"""
    hits = [x for x in _profile("concert_singer") if "singer.Age" in x]
    assert len(hits) == 1, _profile("concert_singer")
    assert "birth" in hits[0]


def test_profile_states_facts_not_recipes():
    """画像只摆事实，不教公式/口径——泛化性红线（用户拍板）。

    禁止出现推导式（'=' 后跟算式）、"必须/应该"式指令。锚定到哪个时点
    是模型在声明层要自己表态的事，画像替它决定就成了往答案上暗示。
    """
    for name in ALL_DBS:
        for line in _profile(name):
            assert "回推" not in line and "必须" not in line, line
            assert " = " not in line, line


def test_profile_lines_are_english():
    """画像注入英文 prompt，条目必须是英文（不夹中文句子）。"""
    for name in ALL_DBS:
        for line in _profile(name):
            assert not any("一" <= ch <= "鿿" for ch in line), line


def test_average_is_not_mistaken_for_age():
    """'Average' 含子串 'age'，不得被当成年龄列。"""
    assert not [x for x in _profile("concert_singer") if "stadium.Average" in x]


def test_old_new_pair_detected():
    lines = _profile("world_1")
    assert [x for x in lines if "GNPOld" in x and "GNP" in x], lines


def test_empty_table_detected():
    lines = _profile("formula_1")
    assert [x for x in lines if "lapTimes" in x and "0 rows" in x], lines


def test_snapshot_table_detected():
    lines = _profile("soccer_1")
    assert [x for x in lines if "Player_Attributes" in x and "dated" in x], lines


def test_event_table_not_reported_as_snapshot():
    """results 的外键指向 3 张表 -> 事件表，不是快照表。"""
    assert not [x for x in _profile("formula_1")
                if "results" in x and "dated" in x]


def test_referenced_table_not_reported_as_snapshot():
    """races 被 7 张表引用 -> 它的行是独立实体（赛事），不是 circuit 的快照。

    单看"外键只指向一张表 + 每键多行"races 也命中——判别式必须再加一条：
    被其他表引用的表是实体表。真快照表（status/Player_Attributes/
    Team_Attributes）在 10 库里全部零被引用。
    """
    assert not [x for x in _profile("formula_1")
                if "races" in x and "dated" in x], _profile("formula_1")


@pytest.mark.parametrize("name", ALL_DBS)
def test_profile_stays_small(name):
    """画像必须短——长了就稀释注意力，也说明规则失控。"""
    lines = _profile(name)
    assert len(lines) <= 6, f"{name} 出了 {len(lines)} 条: {lines}"


@pytest.mark.parametrize("name", ALL_DBS)
def test_profile_lines_are_self_contained(name):
    """每条都要能独立读懂：非空、够长、不带换行（编号靠 render_profile）。"""
    for line in _profile(name):
        assert "\n" not in line and len(line) >= 10, line


def test_numeric_columns_excludes_ids_and_keeps_measures():
    cols = numeric_columns(DB / "concert_singer" / "concert_singer.sqlite")
    assert "Capacity" in cols["stadium"] and "Average" in cols["stadium"]
    assert "Stadium_ID" not in cols["stadium"]
