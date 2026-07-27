"""对已有预测/trace 离线测量任意检查的精度，杜绝"数字凭空来"。

用法:
    python scripts/measure_checks.py --split train --checks sqlens
    python scripts/measure_checks.py --split train --rules data/rules/en.json
    python scripts/measure_checks.py --split dev --checks archived \
        --pred predictions/... --results results/...

"useful" = 触发且该题原判错（提示有机会救）；"harmful" = 触发但原判对（白烧修复轮）。
调参纪律：只准对 train 的输出调正则/阈值，dev 只看不调。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sqlglot

import config
from model.pipeline.dsl import Declarations, load_schema_info
from model.pipeline.dsl.archived_checks import (_c5b_anchor_sql, _c6_ratio_hint,
                                                _c7_abs_difference, _c7_constants,
                                                _c7_displaced_dodge)
from model.pipeline.dsl.checks import ALL_SQLENS, sqlens_issues
from model.pipeline.dsl.rules import eval_rules, load_rules

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    # 对着 plandsl 基线（无知识/无检查）的 trace 离线测精度；
    # dev 固定用 -v1 快照（可复现的历史基准），train 只有当前一版。
    "dev": ("predictions/plandsl/pro-t-plandsl-v1_en_dev",
            "results/plandsl/en_dev_pro-t-plandsl-v1.json"),
    "train": ("predictions/plandsl/pro-t-plandsl_en_train",
              "results/plandsl/en_train_pro-t-plandsl.json"),
}


def measure(hits: dict[str, list[int]], match: dict[int, bool]) -> dict[str, dict]:
    """把「检查名 → 命中题号」变成 useful/harmful/precision 统计。

    纯函数，不碰文件系统——闸门（scripts/distill.py）与人工复算共用它，
    保证两处口径不会各写一套慢慢漂开。
    """
    out = {}
    for name, idx in hits.items():
        known = [i for i in idx if i in match]
        useful = [i for i in known if not match[i]]
        harmful = [i for i in known if match[i]]
        total = len(useful) + len(harmful)
        out[name] = {
            "trigger": len(known),
            "useful": len(useful),
            "harmful": len(harmful),
            "precision": (len(useful) / total) if total else 0.0,
            "useful_ids": useful,
            "harmful_ids": harmful,
        }
    return out


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


def collect_hits(data, preds, trace, *, which: str, rules: list[dict]) -> dict[str, list[int]]:
    """跑一遍所有选中的检查，返回「检查名 → 命中题号」。"""
    hits: dict[str, list[int]] = {}
    for i, (item, sql, tr) in enumerate(zip(data, preds, trace)):
        try:
            tree = sqlglot.parse_one(sql, dialect="sqlite")
        except Exception:
            continue
        db = config.DB_DIR / item["db_id"] / f"{item['db_id']}.sqlite"
        q = item["question"]
        raw = last_declarations(tr)
        decl_obj, decl_dict = None, None
        if raw:
            try:
                decl_obj = Declarations.model_validate(raw)
                decl_dict = raw
            except Exception:
                pass

        per_item: dict[str, list[str]] = {}
        if which in ("archived", "all"):
            per_item["C6"] = _c6_ratio_hint(tree, q, db)
            per_item["C7-const"] = _c7_constants(tree)
            per_item["C7-abs"] = _c7_abs_difference(tree, q)
            if decl_obj is not None:
                per_item["C5b"] = _c5b_anchor_sql(decl_obj, tree, q)
                per_item["C7-dodge"] = _c7_displaced_dodge(decl_obj, q)
        if which in ("sqlens", "all"):
            # 显式传 enabled=ALL_SQLENS：离线重测要覆盖全部六支（含未过闸、默认
            # 关闭的 S1-S4），不能被 sqlens_issues 的线上默认闸门 ENABLED_SQLENS
            # 结构性挡住——否则"归档但保留实现，留着换数据集后重测"就名存实亡。
            per_item.update(sqlens_issues(tree, sql, q, load_schema_info(db), db,
                                          enabled=ALL_SQLENS))
        if rules:
            for rule in rules:
                msgs = eval_rules([rule], tree=tree, question=q,
                                  decl=decl_dict, db_path=db)
                per_item[f"rule:{rule['id']}"] = msgs

        for name, issues in per_item.items():
            hits.setdefault(name, [])
            if issues:
                hits[name].append(i)
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "train"], required=True)
    ap.add_argument("--checks", choices=["archived", "sqlens", "all", "none"],
                    default="none", help="要测哪一族内建检查")
    ap.add_argument("--rules", help="规则库路径；给了就逐条测")
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

    rules = load_rules(args.rules) if args.rules else []
    stats = measure(collect_hits(data, preds, trace, which=args.checks, rules=rules),
                    match)
    for name in sorted(stats):
        s = stats[name]
        print(f"{name}: 触发 {s['trigger']} | useful {s['useful']} {s['useful_ids']} "
              f"| harmful {s['harmful']} {s['harmful_ids']} "
              f"| precision {s['precision']:.0%}")


if __name__ == "__main__":
    main()
