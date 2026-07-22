"""Report output: one evaluation run -> results/<name>.json.

The report is self-describing, so writing it is a plain JSON dump:
`meta` / `summary` / `by_db` / `by_reasoning_type` hold the overview, and
`samples` holds one record per question (question text, reasoning type,
gold and predicted SQL, VA/EX/similarity, result shapes, errors).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def make_meta(data, predictions, db_dir, timeout_s: float) -> dict:
    return {
        "data": str(data),
        "predictions": str(predictions),
        "db_dir": str(db_dir),
        "timeout_s": timeout_s,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def report_name(dataset_alias: str, pred_name: str) -> str:
    """Unified results file naming: <dataset>_<pred>.

    A prediction name that already ends with the dataset alias
    (e.g. first_table_en_dev) is stripped to avoid en_dev_first_table_en_dev.
    """
    suffix = f"_{dataset_alias}"
    if pred_name.endswith(suffix):
        pred_name = pred_name[: -len(suffix)]
    return f"{dataset_alias}_{pred_name}"


def write_report(report: dict, out_dir: str | Path, name: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
