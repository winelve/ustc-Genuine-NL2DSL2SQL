"""对已有预测/trace 离线测量建议级检查器的精度，杜绝"数字凭空来"。

用法:
    python scripts/measure_checks.py --split train
    python scripts/measure_checks.py --split dev --pred predictions/... --results results/...

"useful" = 触发且该题原判错（提示有机会救）；"harmful" = 触发但原判对（白烧修复轮）。
调参纪律：只准对 train 的输出调正则/阈值，dev 只看不调。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sqlglot

import config
from model.pipeline.dsl import (Declarations, _c5b_anchor_sql, _c6_ratio_hint,
                                _c7_abs_difference, _c7_constants,
                                _c7_displaced_dodge)

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    # 对着 plandsl 基线（无知识/无检查）的 trace 离线测精度；
    # dev 固定用 -v1 快照（可复现的历史基准），train 只有当前一版。
    "dev": ("predictions/plandsl/pro-t-plandsl-v1_en_dev",
            "results/plandsl/en_dev_pro-t-plandsl-v1.json"),
    "train": ("predictions/plandsl/pro-t-plandsl_en_train",
              "results/plandsl/en_train_pro-t-plandsl.json"),
}


def last_declarations(trace_item: dict) -> dict | None:
    checks = None
    for cand in trace_item.get("candidates", []):
        if cand.get("checks"):
            checks = cand["checks"]
    if not checks:
        return None
    for r in reversed(checks.get("rounds") or []):
        if r.get("declarations"):
            return r["declarations"]
    return checks.get("declarations")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "train"], required=True)
    ap.add_argument("--pred")      # 不带扩展名的预测文件前缀，默认见 DEFAULTS
    ap.add_argument("--results")
    args = ap.parse_args()
    stem, res = DEFAULTS[args.split]
    stem, res = args.pred or stem, args.results or res

    data = json.load(open(ROOT / "data" / "en_data" / f"{args.split}.json",
                          encoding="utf-8"))
    preds = json.load(open(ROOT / f"{stem}.json", encoding="utf-8"))
    trace = json.load(open(ROOT / f"{stem}.trace.json", encoding="utf-8"))
    if not (len(data) == len(preds) == len(trace)):
        raise SystemExit(f"长度不齐: data={len(data)} preds={len(preds)} "
                         f"trace={len(trace)}——预测/trace 文件不完整，拒绝测量")
    match = {s["index"]: s["match"] for s in json.load(
        open(ROOT / res, encoding="utf-8"))["samples"]}

    hits: dict[str, list[int]] = {}
    for i, (item, sql, tr) in enumerate(zip(data, preds, trace)):
        try:
            tree = sqlglot.parse_one(sql, dialect="sqlite")
        except Exception:
            continue
        db = config.DB_DIR / item["db_id"] / f"{item['db_id']}.sqlite"
        q = item["question"]
        checks = {
            "C6": _c6_ratio_hint(tree, q, db),
            "C7-const": _c7_constants(tree),
            "C7-abs": _c7_abs_difference(tree, q),
        }
        raw = last_declarations(tr)
        if raw:
            try:
                decl = Declarations.model_validate(raw)
                checks["C5b"] = _c5b_anchor_sql(decl, tree, q)
                checks["C7-dodge"] = _c7_displaced_dodge(decl, q)
            except Exception:
                pass
        for name, issues in checks.items():
            if issues:
                hits.setdefault(name, []).append(i)

    for name in sorted(hits):
        idx = hits[name]
        useful = [i for i in idx if not match[i]]
        harmful = [i for i in idx if match[i]]
        print(f"{name}: 触发 {len(idx)} | useful {len(useful)} {useful} "
              f"| harmful {len(harmful)} {harmful}")


if __name__ == "__main__":
    main()
