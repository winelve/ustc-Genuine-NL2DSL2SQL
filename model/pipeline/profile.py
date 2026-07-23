"""库画像：只读 schema + 数据分布，产出少量**程序能确定**的事实条目。

只出四类，绝不猜语义：
  存量时点列 / 时间成对列 / 多版本快照表 / 空表

两条红线（用户拍板，泛化性优先）：
1. **只摆事实，不教公式、不给做法**——锚定到哪个时点、取最新还是聚合，
   是模型在声明层必须自己表态的事；画像替它决定就成了往答案上暗示，
   知识层的消融也就量不出"模型自己能不能用对事实"。
2. 条目注入英文 prompt，一律英文陈述句。

刻意不出"数值列对（比率候选）"——组合爆炸（soccer_1 的 Player_Attributes
一张表就有 1264 组），进 prompt 只会稀释注意力。比率线索改由
dsl._c6_ratio_hint 在校验时按需触发：题面有比率词、SQL 里又一个除法都没有，
才把该表的数值列摆出来。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

# (^|_)age(s)?($|_) —— 'Age'/'player_age' 命中，'Average'/'Percentage' 不命中
_AGE = re.compile(r"(^|_)ages?($|_)", re.I)
_BIRTH = re.compile(r"dob|birth", re.I)
_SNAPDATE = re.compile(r"^(date|time|timestamp|.*_date|.*_time)$", re.I)
_IDISH = re.compile(r"(^|_)id$|^id$", re.I)
_OLD_SUFFIX = ("old", "prev", "last", "_old", "_prev")
_NUMERIC = ("INT", "REAL", "NUM", "DOUB", "FLOA", "DEC")


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]


def _is_numeric(decl_type: str) -> bool:
    return any(k in (decl_type or "").upper() for k in _NUMERIC)


def numeric_columns(db_path: Path) -> dict[str, list[str]]:
    """表名(小写) -> 非 ID、非主键的数值列原名。C6 与画像共用。"""
    conn = _connect(db_path)
    try:
        return {
            t.lower(): [
                r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')
                if _is_numeric(r[2]) and not r[5] and not _IDISH.search(r[1])
            ]
            for t in _tables(conn)
        }
    finally:
        conn.close()


def build_profile(db_path: Path) -> list[str]:
    """产出事实条目；每条自成一句，调用方负责编号（见 dsl.render_profile）。"""
    conn = _connect(db_path)
    try:
        tables = _tables(conn)
        # 被任何外键指到的表，其行是独立实体，不可能是别人的快照（见 _snapshot）
        referenced = {r[2].lower() for t in tables
                      for r in conn.execute(f'PRAGMA foreign_key_list("{t}")')}
        lines: list[str] = []
        for t in tables:
            cols = [(r[1], r[2], r[5]) for r
                    in conn.execute(f'PRAGMA table_info("{t}")')]
            n_rows = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if n_rows == 0:
                lines.append(f"Table {t} is empty: 0 rows.")
                continue
            lines += _stock_age(t, cols)
            lines += _old_new_pair(t, cols)
            lines += _snapshot(conn, t, cols, n_rows, referenced)
        return lines
    finally:
        conn.close()


def _stock_age(table: str, cols: list[tuple]) -> list[str]:
    """年龄类数值列 + 本表无出生日期列 => 该值锚在哪个时点，库里没说。"""
    if any(_BIRTH.search(c) for c, _, _ in cols):
        return []
    return [
        f"{table}.{c} is a stored number and {table} has no birth-date "
        f"column; nothing in the database says which point in time "
        f"the stored value refers to."
        for c, ty, _ in cols if _AGE.search(c) and _is_numeric(ty)
    ]


def _old_new_pair(table: str, cols: list[tuple]) -> list[str]:
    """X 与 XOld 同表 => 同一量的新旧两个取值并存。"""
    by_lower = {c.lower(): c for c, _, _ in cols}
    lines = []
    for c, _, _ in cols:
        for suffix in _OLD_SUFFIX:
            base = c.lower()[:-len(suffix)]
            if c.lower().endswith(suffix) and base in by_lower:
                lines.append(
                    f"{table}.{by_lower[base]} and {table}.{c} hold the same "
                    f"quantity at two different times, {c} being the older value.")
    return lines


def _snapshot(conn: sqlite3.Connection, table: str, cols: list[tuple],
              n_rows: int, referenced: set[str]) -> list[str]:
    """多版本快照表：有快照日期列 + 外键只指向一张表 + 每个外键多行
    + **没有任何表引用它**。

    前三条是"快照挂在单个实体上"（Player_Attributes -> Player），
    与事件表（results -> races/drivers/constructors）的判别式。
    最后一条堵住 races 这类假阳性：races 外键只指 circuits、每个
    circuitId 也有多行，但它被 results 等 7 张表引用——被引用说明
    每行是独立实体（一场比赛），不是 circuit 的历史快照。
    10 库里真快照表（status/Player_Attributes/Team_Attributes）零被引用。
    """
    if table.lower() in referenced:
        return []
    date_cols = [c for c, _, _ in cols if _SNAPDATE.match(c)]
    if not date_cols:
        return []
    fks = list(conn.execute(f'PRAGMA foreign_key_list("{table}")'))
    if len({r[2] for r in fks}) != 1:
        return []
    fk_cols = {r[3] for r in fks}
    for col, _, pk in cols:
        if pk or col not in fk_cols:
            continue
        n_keys = conn.execute(
            f'SELECT COUNT(DISTINCT "{col}") FROM "{table}"').fetchone()[0]
        if n_keys and n_rows / n_keys >= 2:
            return [f"Table {table} holds ~{n_rows / n_keys:.0f} dated rows "
                    f"(see column {date_cols[0]}) per {col}; one {col} "
                    f"corresponds to many rows, not one."]
    return []
