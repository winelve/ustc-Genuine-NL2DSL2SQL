"""最简可运行基线，演示 SQLGenerator 接口怎么实现。

对每道题一律返回 SELECT * FROM <库里第一张表>：
- VA 会接近 100%（语法总是合法的）
- EX 会接近 0%（结果基本不可能恰好等于 gold）
用途：验证 生成→落盘→评测 全流程通不通，以及作为分数下限参照。
"""

from __future__ import annotations

from pathlib import Path

from archer_eval.data import Sample
from archer_eval.execution import connect_ro
from model.base import SQLGenerator


class FirstTableBaseline(SQLGenerator):
    name = "first_table"

    def __init__(self) -> None:
        self._cache: dict[Path, str] = {}

    def _first_table(self, db_path: Path) -> str:
        if db_path not in self._cache:
            conn = connect_ro(db_path)
            try:
                row = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid LIMIT 1"
                ).fetchone()
            finally:
                conn.close()
            self._cache[db_path] = row[0]
        return self._cache[db_path]

    def predict(self, sample: Sample, db_path: Path) -> str:
        return f'SELECT * FROM "{self._first_table(db_path)}"'
