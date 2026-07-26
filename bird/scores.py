"""把 `results/bird/*.json` 汇成一张 markdown 表。

    python -m bird scores

存在的意义：**分数不手打**。docs/BIRD.md 里的表格直接贴这个命令的输出，
任何时候都能重新生成，杜绝抄错和漂移。
"""

from __future__ import annotations

import json
from pathlib import Path

import config

_LEVELS = ("simple", "moderate", "challenging")
_HEADER = ("| 预测 | 口径 | n | EX | simple | moderate | challenging |\n"
           "|---|---|---:|---:|---:|---:|---:|")

# meta.protocol → 表里显示的口径名
_PROTOCOLS = {
    "bird-official-script": "官方脚本",
    "bird-official": "本项目实现",
}


def load_reports(results_dir: Path | None = None) -> list[dict]:
    """读 `results/bird/` 下所有报告，按文件名排序；读不动的跳过。"""
    results_dir = results_dir or config.RESULTS_DIR / "bird"
    reports = []
    for path in sorted(Path(results_dir).glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "summary" in report:
            report["_file"] = path.name
            reports.append(report)
    return reports


def _cell(metrics: dict | None) -> str:
    return f"{metrics['EX_pct']:.2f}" if metrics else "—"


def render(reports: list[dict]) -> str:
    """报告列表 → markdown 表格。没有报告时返回一句提示。"""
    if not reports:
        return "（results/bird/ 下还没有报告）"

    lines = [_HEADER]
    for report in reports:
        summary = report["summary"]
        meta = report.get("meta", {})
        protocol = _PROTOCOLS.get(meta.get("protocol", ""), meta.get("protocol", "?"))
        by_difficulty = report.get("by_difficulty", {})
        cells = " | ".join(_cell(by_difficulty.get(level)) for level in _LEVELS)
        lines.append(
            f"| {Path(report['_file']).stem} | {protocol} | {summary['n']} | "
            f"**{summary['EX_pct']:.2f}** | {cells} |")
    return "\n".join(lines)


def main(results_dir: Path | None = None) -> int:
    print(render(load_reports(results_dir)))
    return 0
