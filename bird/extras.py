"""BIRD 额外资料的读取与渲染 —— **官方 baseline 不使用这里的任何东西**。

> ⚠️ 用了这里的函数，跑出来的分数就**不能**跟 BIRD 榜单并排。
> 官方 baseline 的输入只有：全库 CREATE TABLE DDL + 题面 + evidence（见 `bird/official.py`）。
> 本文件保留下来是为了将来做**非官方消融**（"多给列描述/外键值多少分"），
> 所以它不进 `bird/__init__.py` 的默认导出，要用得显式 `from bird.extras import ...`。

两个来源：

1. `<db>/database_description/<table>.csv` —— 每列的自然语言全称、含义、数据格式、
   取值口径。实测 dev 集 798 列全部能匹配到 CSV 行，其中 652 列有 column_description、
   278 列有 value_description。
2. `dev_tables.json` —— 自然语言表/列名 + 主键 + 外键对。

三条容错规则都有实测依据，改动前先看 tests/test_bird.py：

- **编码**：71/75 个 CSV 是 utf-8-sig，4 个不是 → latin-1 回退；
- **表头**：有 1 个 CSV 多一个空列名 → strip 后丢弃空字段名；
- **匹配**：表名列名一律小写做键，值里保留库内原名。

**缺失是常态不是错误**：找不到库/表/列一律返回空容器或空字符串，绝不抛异常；
渲染函数没内容一律返回空串，调用方 `if block:` 即可。
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from bird import paths

_ENCODINGS = ("utf-8-sig", "latin-1")
_TRUNCATED = "\n... (truncated)"


# ---------------------------------------------------------------- 读取层


@dataclass(frozen=True)
class ColumnDoc:
    table: str                 # 库内真名
    column: str                # 库内真名
    nl_name: str = ""          # CSV 的 column_name（自然语言全称）
    description: str = ""      # column_description
    data_format: str = ""      # data_format
    value_description: str = ""


@dataclass(frozen=True)
class SchemaMeta:
    db_id: str
    tables: dict[str, str] = field(default_factory=dict)              # 真名 → 自然语言名
    columns: dict[str, dict[str, str]] = field(default_factory=dict)  # 表 → {列真名: 自然语言名}
    primary_keys: dict[str, list[str]] = field(default_factory=dict)  # 表 → 主键列
    foreign_keys: list[tuple[str, str, str, str]] = field(default_factory=list)


def _read_rows(path: Path) -> list[dict[str, str]]:
    """按编码回退读 CSV，清洗表头，返回 dict 行。读不出来返回空列表。"""
    for encoding in _ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
        reader = csv.reader(text.splitlines())
        try:
            header = [(h or "").strip() for h in next(reader)]
        except StopIteration:
            return []
        rows = []
        for raw in reader:
            row = {}
            for key, value in zip(header, raw):
                if key:  # 丢弃空列名（官方有 1 个 CSV 表头多一个空列）
                    row[key] = (value or "").strip()
            rows.append(row)
        return rows
    return []


def _load_column_docs(db_id: str, root: Path) -> dict[str, dict[str, ColumnDoc]]:
    desc_dir = paths.description_dir(db_id, root)
    if not desc_dir.is_dir():
        return {}

    docs: dict[str, dict[str, ColumnDoc]] = {}
    for csv_path in sorted(desc_dir.glob("*.csv")):
        table = csv_path.stem
        per_table: dict[str, ColumnDoc] = {}
        for row in _read_rows(csv_path):
            column = row.get("original_column_name", "")
            if not column:
                continue
            per_table[column.lower()] = ColumnDoc(
                table=table,
                column=column,
                nl_name=row.get("column_name", ""),
                description=row.get("column_description", ""),
                data_format=row.get("data_format", ""),
                value_description=row.get("value_description", ""),
            )
        if per_table:
            docs[table.lower()] = per_table
    return docs


@lru_cache(maxsize=None)
def _load_column_docs_cached(db_id: str, root: Path):
    return _load_column_docs(db_id, root)


def load_column_docs(db_id: str, root: Path | None = None) -> dict[str, dict[str, ColumnDoc]]:
    """`{表名小写: {列名小写: ColumnDoc}}`；找不到返回 `{}`。"""
    return _load_column_docs_cached(db_id, Path(root) if root else paths.dev_databases_dir())


def _load_schema_meta(db_id: str, tables_path: Path) -> SchemaMeta:
    try:
        entries = json.loads(tables_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SchemaMeta(db_id=db_id)

    entry = next((e for e in entries if e.get("db_id") == db_id), None)
    if entry is None:
        return SchemaMeta(db_id=db_id)

    originals = entry.get("table_names_original", [])
    nl_tables = entry.get("table_names", [])
    tables = {t: (nl_tables[i] if i < len(nl_tables) else t) for i, t in enumerate(originals)}

    cols_original = entry.get("column_names_original", [])
    cols_nl = entry.get("column_names", [])
    columns: dict[str, dict[str, str]] = {t: {} for t in originals}
    flat: list[tuple[str, str] | None] = []   # 列序号 → (表真名, 列真名)
    for i, (t_idx, col) in enumerate(cols_original):
        if t_idx < 0 or t_idx >= len(originals):
            flat.append(None)                  # "*" 这类占位
            continue
        table = originals[t_idx]
        nl = cols_nl[i][1] if i < len(cols_nl) else col
        columns[table][col] = nl
        flat.append((table, col))

    primary_keys: dict[str, list[str]] = {t: [] for t in originals}
    for key in entry.get("primary_keys", []):
        for idx in (key if isinstance(key, list) else [key]):
            if 0 <= idx < len(flat) and flat[idx]:
                table, col = flat[idx]
                primary_keys[table].append(col)

    foreign_keys: list[tuple[str, str, str, str]] = []
    for src_idx, dst_idx in entry.get("foreign_keys", []):
        if 0 <= src_idx < len(flat) and 0 <= dst_idx < len(flat) and flat[src_idx] and flat[dst_idx]:
            foreign_keys.append((*flat[src_idx], *flat[dst_idx]))

    return SchemaMeta(db_id=db_id, tables=tables, columns=columns,
                      primary_keys=primary_keys, foreign_keys=foreign_keys)


@lru_cache(maxsize=None)
def _load_schema_meta_cached(db_id: str, tables_path: Path):
    return _load_schema_meta(db_id, tables_path)


def load_schema_meta(db_id: str, tables_path: Path | None = None) -> SchemaMeta:
    """dev_tables.json 的元数据；找不到返回空 SchemaMeta。"""
    return _load_schema_meta_cached(
        db_id, Path(tables_path) if tables_path else paths.tables_json()
    )


# ---------------------------------------------------------------- 渲染层


def _clip(text: str, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + _TRUNCATED


def _wanted(tables: Iterable[str] | None) -> set[str] | None:
    return None if tables is None else {t.lower() for t in tables}


def _one_line(doc: ColumnDoc, with_values: bool) -> str:
    """把一个 ColumnDoc 渲染成一行；没有任何可说的内容则返回空串。"""
    meaning = doc.description or doc.nl_name
    value = doc.value_description if with_values else ""
    if not (meaning or value):
        return ""
    head = f"- `{doc.column}`"
    if doc.data_format:
        head += f" ({doc.data_format})"
    parts = [p for p in (meaning, value) if p]
    body = ". ".join(" ".join(p.split()) for p in parts)
    return f"{head}: {body}"


def column_descriptions_block(
    db_id: str,
    *,
    tables: Iterable[str] | None = None,
    with_values: bool = True,
    max_chars: int | None = None,
    root: Path | None = None,
) -> str:
    """列含义 + 取值口径，按表分组。全库平均 6k 字符，大库建议传 `tables` 或 `max_chars`。"""
    docs = load_column_docs(db_id, root)
    if not docs:
        return ""

    wanted = _wanted(tables)
    chunks = []
    for table in sorted(docs):
        if wanted is not None and table not in wanted:
            continue
        lines = [line for doc in docs[table].values()
                 if (line := _one_line(doc, with_values))]
        if lines:
            chunks.append(f"## {table}\n" + "\n".join(lines))
    return _clip("\n\n".join(chunks), max_chars)


def data_format_block(
    db_id: str, *, tables: Iterable[str] | None = None, root: Path | None = None
) -> str:
    """列 → 数据格式的紧凑清单，给类型转换（CAST）用。"""
    docs = load_column_docs(db_id, root)
    if not docs:
        return ""

    wanted = _wanted(tables)
    lines = []
    for table in sorted(docs):
        if wanted is not None and table not in wanted:
            continue
        for doc in docs[table].values():
            if doc.data_format:
                lines.append(f"- {doc.table}.{doc.column}: {doc.data_format}")
    return "\n".join(lines)


def schema_meta_block(
    db_id: str,
    *,
    with_nl_names: bool = True,
    with_keys: bool = True,
    tables_path: Path | None = None,
) -> str:
    """官方 schema 元数据：自然语言表/列名 + 主键 + 外键对（DDL 里没有的增量）。"""
    meta = load_schema_meta(db_id, tables_path)
    if not meta.tables:
        return ""

    chunks = []
    if with_nl_names:
        lines = []
        for table, nl_table in meta.tables.items():
            label = table if nl_table == table else f"{table} ({nl_table})"
            lines.append(f"## {label}")
            for col, nl_col in meta.columns.get(table, {}).items():
                lines.append(f"- {col}" + ("" if nl_col == col else f" ({nl_col})"))
        chunks.append("\n".join(lines))

    if with_keys:
        key_lines = []
        pks = [f"- {t}.{', '.join(cols)}" for t, cols in meta.primary_keys.items() if cols]
        if pks:
            key_lines.append("Primary keys:")
            key_lines += pks
        if meta.foreign_keys:
            key_lines.append("Foreign keys:")
            key_lines += [f"- {a}.{b} -> {c}.{d}" for a, b, c, d in meta.foreign_keys]
        if key_lines:
            chunks.append("\n".join(key_lines))

    return "\n\n".join(chunks)
