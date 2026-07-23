"""tests/test_conventions.py — 约定表的红线与格式。"""
import re

from model.pipeline.conventions import CONVENTIONS, conventions_block


def test_conventions_capped_at_twelve():
    """条目 ≤12：超了说明在往逐题答案滑（立项红线）。"""
    assert 1 <= len(CONVENTIONS) <= 12


def test_every_convention_cites_train_evidence():
    """每条必须带 train 证据引用；dev 是考卷，dev-only 不立项。
    evidence 不得引用 dev 两库（world_1, concert_singer）。"""
    for c in CONVENTIONS:
        assert "train" in c.evidence, c.id
        assert not re.search(r"world_1|concert_singer", c.evidence), c.id


def test_conventions_text_is_english_prompt_ready():
    for c in CONVENTIONS:
        assert not any("一" <= ch <= "鿿" for ch in c.text), c.id
        assert "\n" not in c.text and len(c.text) >= 20, c.id


def test_conventions_do_not_name_dev_db_columns():
    """条目措辞必须泛化——不得出现 dev 两库的专属列名/表名。"""
    banned = re.compile(r"GNPOld|Song_release_year|Stadium|concert_singer|world_1",
                        re.I)
    for c in CONVENTIONS:
        assert not banned.search(c.text), c.id


def test_block_numbers_are_stable_reference_keys():
    block = conventions_block()
    for i, c in enumerate(CONVENTIONS, 1):
        assert f"K{i}. " in block
        assert c.id == f"K{i}"
