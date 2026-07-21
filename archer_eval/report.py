"""Report output: one evaluation run -> <name>.json + <name>.md in results/.

- <name>.json : full machine-readable report
- <name>.md   : summary tables plus every failed sample with its
                question, gold SQL and predicted SQL
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from archer_eval.data import Sample


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


def _pct(x: float) -> str:
    return f"{x:.2%}"


def _metric_table(groups: dict[str, dict]) -> list[str]:
    lines = ["| 分组 | n | VA | EX |", "|---|---|---|---|"]
    for name, m in groups.items():
        lines.append(f"| {name} | {m['n']} | {_pct(m['VA'])} | {_pct(m['EX'])} |")
    return lines


def render_markdown(report: dict, samples: list[Sample], predictions: list[str]) -> str:
    meta = report["meta"]
    s = report["summary"]
    lines = [
        f"# {Path(meta['predictions']).name} on {Path(meta['data']).name}",
        "",
        f"- 时间: {meta['timestamp']}",
        f"- 样本: {s['n']}",
        f"- VA: {_pct(s['VA'])} ({s['n_valid']}/{s['n']} 可执行)",
        f"- EX: {_pct(s['EX'])} ({s['n_match']}/{s['n']} 结果正确)",
        "",
        "## 按数据库",
        "",
        *_metric_table(report["by_db"]),
        "",
        "## 按推理类型",
        "",
        *_metric_table(report["by_reasoning_type"]),
    ]

    failures = [r for r in report["samples"] if not r["match"]]
    lines += ["", f"## 错误样本 ({len(failures)})", ""]
    for r in failures:
        sample = samples[r["index"]]
        reason = (
            f"执行失败: {r['pred_error']}" if not r["valid"]
            else f"gold 执行失败: {r['gold_error']}" if r["gold_error"]
            else "结果不一致"
        )
        lines += [
            f"### #{r['index']} {r['db_id']} — {reason}",
            "",
            f"- 问题: {sample.question}",
            f"- gold: `{sample.query}`",
            f"- 预测: `{predictions[r['index']]}`",
            "",
        ]
    return "\n".join(lines) + "\n"


def write_report(
    report: dict, samples: list[Sample], predictions: list[str], out_dir: str | Path, name: str
) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{name}.json"
    md_path = out_dir / f"{name}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report, samples, predictions), encoding="utf-8")
    return json_path, md_path
