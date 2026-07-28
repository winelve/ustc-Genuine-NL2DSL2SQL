"""Render fixed CHESS-IR records without importing offline dependencies."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from archer_eval.execution import connect_ro

from .store import ValueEvidenceStore
from .types import RetrievedContext, RetrievedValue, ValueEvidenceRecord


MODES = {"relevant", "random"}


def schema_ddl(db_path: str | Path) -> str:
    conn = connect_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    return "\n\n".join(sql.strip() for _, sql in rows if sql)


def render_value_block(record: ValueEvidenceRecord, *, mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"value evidence mode must be one of {sorted(MODES)}")

    grouped: OrderedDict[
        tuple[str, str], dict[str, Any]
    ] = OrderedDict()
    for context in record.contexts:
        grouped[(context.table, context.column)] = {
            "context": context,
            "values": [],
        }
    for value in record.values:
        key = (value.table, value.column)
        grouped.setdefault(key, {"context": None, "values": []})
        grouped[key]["values"].append(value)

    if not grouped:
        return ""
    lines = ["/* Retrieved database context:"]
    for (table, column), packet in grouped.items():
        context: RetrievedContext | None = packet["context"]
        values: list[RetrievedValue] = packet["values"]
        head = f"- {table}.{column}"
        if context is not None:
            head += f": {_one_line(context.description)}"
        lines.append(head)
        if values:
            selected = [
                item.value if mode == "relevant" else item.control_value
                for item in values
            ]
            rendered = ", ".join(_sql_literal(value) for value in selected)
            lines.append(f"  Example values: {rendered}")
    lines.append("*/")
    return "\n".join(lines)


def render_value_schema(
    db_path: str | Path,
    record: ValueEvidenceRecord,
    *,
    mode: str,
) -> str:
    ddl = schema_ddl(db_path)
    block = render_value_block(record, mode=mode)
    return f"{ddl}\n\n{block}" if block else ddl


def render_additive_value_schema(
    db_path: str | Path,
    record: ValueEvidenceRecord,
    *,
    mode: str,
) -> str:
    """Append retrieved context to the unchanged CT-3 schema with sample rows."""
    from model.prompts import schema_with_rows

    baseline = schema_with_rows(db_path)
    block = render_value_block(record, mode=mode)
    return f"{baseline}\n\n{block}" if block else baseline


def value_evidence_trace(
    *,
    selection: str,
    store: ValueEvidenceStore,
    record: ValueEvidenceRecord,
    mode: str,
    schema_mode: str = "ddl-replacement",
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"value evidence mode must be one of {sorted(MODES)}")
    values = []
    for item in record.values:
        injected = item.value if mode == "relevant" else item.control_value
        values.append(
            {
                "table": item.table,
                "column": item.column,
                "value": injected,
                "relevant_value": item.value,
                "control_value": item.control_value,
                "keyword": item.keyword,
                "edit_similarity": item.edit_similarity,
                "embedding_similarity": item.embedding_similarity,
            }
        )
    contexts = [
        {
            "table": item.table,
            "column": item.column,
            "description": item.description,
            "score": item.score,
        }
        for item in record.contexts
    ]
    return {
        "selection": selection,
        "artifact_sha256": store.artifact_sha256,
        "strategy": store.strategy,
        "dataset": store.dataset,
        "dataset_sha256": store.dataset_sha256,
        "keywords_sha256": store.keywords_sha256,
        "encoder": store.encoder,
        "encoder_sha256": store.encoder_sha256,
        "parameters": dict(store.parameters),
        "mode": mode,
        "schema_mode": schema_mode,
        "keywords": list(record.keywords),
        "values": values,
        "contexts": contexts,
        "rendered_context_chars": len(render_value_block(record, mode=mode)),
    }


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
