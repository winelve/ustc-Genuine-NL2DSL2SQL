"""蒸馏知识层：从 data/knowledge/<数据集>.json 读条目，渲染进 dslgen 的 system。

替代了原来手写的 conventions.py（K1-K11）。区别只在来源——条目由
scripts/distill.py 从 train 错题离线蒸馏，程序把关；三条红线不变：

1. **通用思路，不点具体库**——条目里不得出现任何库的表名/列名。黑名单
   从数据集自己的库动态提取（schema_vocabulary），换数据集自动换，不写死。
2. **证据 ≥ 2 题**——只出现过一次的模式不立项，那是巧合不是约定。
3. **条数 ≤ 12**——超了就是在往逐题答案滑。

与 evidence 的区别：evidence 是题目自带、每题不同、进 user；这里是整个
数据集共用一份、与具体哪道题无关、进 system（可命中 prompt cache）。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import config

_ROOT = Path(__file__).resolve().parents[2]


class KnowledgeError(ValueError):
    """知识条目不合规。蒸馏期与加载期都抛，绝不让违规条目进 prompt。"""


def knowledge_path_for(dataset: str) -> Path:
    """en_dev/en_train -> data/knowledge/en.json；bird_dev -> data/knowledge/bird.json。"""
    return _ROOT / "data" / "knowledge" / f"{dataset.split('_')[0]}.json"


def schema_vocabulary(dataset: str) -> set[str]:
    """该数据集所有库的表名 + 列名，小写去重。泛化黑名单的来源。"""
    db_dir = Path(config.db_dir_for(dataset))
    vocab: set[str] = set()
    for db_file in sorted(db_dir.glob("*/*.sqlite")):
        try:
            conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")]
            for t in tables:
                vocab.add(t.lower())
                for row in conn.execute(f'PRAGMA table_info("{t}")'):
                    vocab.add(row[1].lower())
        except sqlite3.Error:
            continue
        finally:
            conn.close()
    return vocab


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def check_items(items: list[dict], vocab: set[str], *, max_items: int,
                min_evidence: int) -> None:
    """三条红线，违规就抛 KnowledgeError。"""
    if len(items) > max_items:
        raise KnowledgeError(
            f"知识条数 {len(items)} 超过上限 {max_items}——条目越多越像逐题答案")
    for item in items:
        iid = item.get("id", "<无 id>")
        text = (item.get("text") or "").strip()
        if not text:
            raise KnowledgeError(f"条目 {iid} 的 text 为空")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or len(evidence) < min_evidence:
            raise KnowledgeError(
                f"条目 {iid} 的证据不足 {min_evidence} 题——"
                f"只出现一次的模式是巧合不是约定")
        hit = sorted({w.lower() for w in _WORD.findall(text)} & vocab)
        if hit:
            raise KnowledgeError(
                f"条目 {iid} 出现了库的表名/列名 {hit}——"
                f"知识必须是通用思路，不能点名具体的库")


def load_knowledge(path: str | Path) -> list[dict]:
    """读知识文件；不存在 = 没有知识，返回 []。加载期不再复查红线
    （蒸馏时已经把过关，重复查会让手工加白的条目无法生效）。"""
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("items", [])


def knowledge_block(items: list[dict]) -> str:
    """编号块；编号即 trace/审计里的引用键。空列表返回空串。"""
    return "\n".join(f"{it['id']}. {it['text']}" for it in items)
