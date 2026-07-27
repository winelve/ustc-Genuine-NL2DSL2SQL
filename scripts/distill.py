"""从 train 错题离线蒸馏两样东西：知识条目（进 prompt）与检查规则（进检查器）。

两个子命令**互不知情**——产物是两份独立文件，各有各的把关方式：

    knowledge  程序把关（泛化黑名单 + 证据≥2 + 条数上限），无法测精度
    rules      程序把关 + **闸门**（在全 split 上回放，算 useful/harmful）

骨干默认与被测模型相同（deepseek-v4-pro + thinking）：蒸的是自己的错题，
零外部信息注入，消融干净。换更强的模型是另一个实验档位，产物里的
`distilled_by` 会记下来。

用法：
    python -m scripts.distill knowledge --split en_train --out data/knowledge/en.json
    python -m scripts.distill rules     --split en_train --out data/rules/en.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

from model.llm import ChatEndpoint
from model.pipeline.dsl.rules import (DECL_PREDICATES, NODE_WHITELIST, PREDICATES,
                                      RuleError, check_rule)
from model.pipeline.knowledge import KnowledgeError, check_items, schema_vocabulary
from model.pipeline.templates import render
from scripts.measure_checks import collect_hits, measure

ROOT = Path(__file__).resolve().parents[1]

BACKBONES = {
    "pro-t": dict(base_url="https://api.deepseek.com/v1", model="deepseek-v4-pro",
                  key_env="DEEPSEEK_API_KEY",
                  request_params={"extra_body": {"thinking": {"type": "enabled"}}}),
    "pro": dict(base_url="https://api.deepseek.com/v1", model="deepseek-v4-pro",
                key_env="DEEPSEEK_API_KEY"),
}

# 蒸馏对着哪一份预测的错题；与 measure_checks.py 的 DEFAULTS 同源，
# 换了这里也要换那里，否则闸门测的和蒸馏看的不是同一批题。
DEFAULT_PRED = "predictions/plandsl/pro-t-plandsl_en_train"
DEFAULT_RESULTS = "results/plandsl/en_train_pro-t-plandsl.json"


class DistillError(RuntimeError):
    """蒸馏失败（模型没给出可用 JSON 等）。"""


def wrong_cases(data_path: Path, pred_path: Path, results_path: Path) -> list[dict]:
    """判错的题，带题面 / 预测 SQL / 参考 SQL。"""
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    preds = json.loads(Path(pred_path).read_text(encoding="utf-8"))
    match = {s["index"]: s["match"]
             for s in json.loads(Path(results_path).read_text(encoding="utf-8"))["samples"]}
    return [
        {"index": i, "question": item["question"],
         "pred_sql": preds[i], "gold_sql": item["query"]}
        for i, item in enumerate(data)
        if i in match and not match[i] and i < len(preds)
    ]


def cases_block(cases: list[dict]) -> str:
    return "\n\n".join(
        f"#{c['index']}\n"
        f"  question: {c['question']}\n"
        f"  produced: {c['pred_sql']}\n"
        f"  reference: {c['gold_sql']}"
        for c in cases)


def parse_items(reply: str, key: str = "items") -> list[dict]:
    """从模型回复抽出 {key: [...]}；抽不出就抛，绝不静默返回空。

    knowledge 用默认 key="items"，rules 传 key="rules"——两条子命令共用
    同一套"找花括号 / 解析 JSON / 校验数组"逻辑，不各写一份。
    """
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        raise DistillError(f"回复里没有 JSON 对象:\n{reply[:400]}")
    try:
        data = json.loads(reply[start:end + 1])
    except json.JSONDecodeError as e:
        raise DistillError(f"JSON 解析失败: {e}\n{reply[:400]}") from e
    items = data.get(key)
    if not isinstance(items, list):
        raise DistillError(f"JSON 里没有 {key} 数组:\n{reply[:400]}")
    return items


def _endpoint(name: str) -> ChatEndpoint:
    if name not in BACKBONES:
        raise SystemExit(f"未知骨干 {name}，可用：{sorted(BACKBONES)}")
    return ChatEndpoint(**BACKBONES[name])


def _backbone_label(name: str) -> str:
    """骨干注册名 -> `distilled_by` 落盘标签。

    唯一出口：knowledge 与 rules 两条子命令都调它，同一个 pro-t 骨干
    在两份产物里记的标签不会分岔（一个带 -thinking 一个不带）。
    """
    spec = BACKBONES[name]
    thinking = "extra_body" in spec.get("request_params", {})
    return spec["model"] + ("-thinking" if thinking else "")


def _write(out: Path, payload: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"写入 {out}")


def cmd_knowledge(args) -> None:
    cases = wrong_cases(ROOT / "data" / "en_data" / f"{args.split.split('_')[1]}.json",
                        ROOT / f"{args.pred}.json", ROOT / args.results)
    print(f"{len(cases)} 道错题喂给 {args.backbone}")
    reply = _endpoint(args.backbone).chat_messages(
        [{"role": "user", "content": render(
            "distill.knowledge", cases=cases_block(cases),
            min_evidence=str(args.min_evidence), max_items=str(args.max_items))}],
        temperature=0.0)
    items = parse_items(reply)  # 默认 key="items"
    vocab = schema_vocabulary(args.split)
    kept, dropped = [], []
    for item in items:
        try:
            check_items([item], vocab, max_items=args.max_items,
                        min_evidence=args.min_evidence)
            kept.append(item)
        except KnowledgeError as e:
            dropped.append((item.get("id"), str(e)))
    for iid, why in dropped:
        print(f"  弃 {iid}: {why}")
    check_items(kept, vocab, max_items=args.max_items,
                min_evidence=args.min_evidence)
    _write(Path(args.out), {
        "dataset": args.split,
        "distilled_by": _backbone_label(args.backbone),
        "distilled_at": _dt.date.today().isoformat(),
        "source_pred": args.pred,
        "items": kept,
    })


def vocabulary_block() -> str:
    """把封闭谓词表渲染成给模型看的说明。**唯一出口是代码本身**——
    加了新谓词这里自动跟上，不会出现"文档说有、代码没有"。"""
    lines = [
        "  question <regex>            - the question text matches this regex",
        "  sql_has [Node, ...]         - the SQL's syntax tree contains any of these nodes",
        "  sql_lacks [Node, ...]       - the tree contains none of these nodes",
        "  sql_select_has Node         - the SELECT clause specifically contains this node",
        "  sql_has_literal [str, ...]  - the SQL contains any of these literal values",
        "  sql_select_count [op, n]    - number of output columns, op in > >= < <= == !=",
        "  uses_table <regex>          - some table name in the SQL matches",
        "  uses_column <regex>         - some column name in the SQL matches",
        "  decl_eq {path: value}       - the declaration table's field equals value,",
        "                                e.g. {\"time_context.displaced\": false}",
    ]
    assert set(PREDICATES) == {
        "question", "sql_has", "sql_lacks", "sql_select_has", "sql_has_literal",
        "sql_select_count", "uses_table", "uses_column", "decl_eq"}, \
        "谓词表变了，vocabulary_block 也要跟着改"
    return ("\n".join(lines) + "\n\nNode names allowed: "
            + ", ".join(sorted(NODE_WHITELIST)))


def _match_map(results: str) -> dict[int, bool]:
    return {s["index"]: s["match"] for s in
            json.loads((ROOT / results).read_text(encoding="utf-8"))["samples"]}


def _rule_hits(rules, *, split, pred) -> dict[str, list[int]]:
    data = json.loads((ROOT / "data" / "en_data"
                       / f"{split.split('_')[1]}.json").read_text(encoding="utf-8"))
    preds = json.loads((ROOT / f"{pred}.json").read_text(encoding="utf-8"))
    trace = json.loads((ROOT / f"{pred}.trace.json").read_text(encoding="utf-8"))
    return collect_hits(data, preds, trace, which="none", rules=rules)


def gate(rules: list[dict], *, split: str, pred: str, results: str,
         min_trigger: int, min_precision: float) -> tuple[list[dict], list[tuple]]:
    """在全 split 上回放每条规则，按 trigger/precision 收弃。

    闸门与 measure_checks.py 共用同一个 measure()——两处口径不会慢慢漂开。
    """
    stats = measure(_rule_hits(rules, split=split, pred=pred), _match_map(results))
    kept, dropped = [], []
    for rule in rules:
        s = stats.get(f"rule:{rule['id']}",
                      {"trigger": 0, "useful": 0, "harmful": 0, "precision": 0.0})
        summary = {k: s[k] for k in ("trigger", "useful", "harmful", "precision")}
        if s["trigger"] >= min_trigger and s["precision"] >= min_precision:
            rule["measured"] = summary
            kept.append(rule)
        else:
            dropped.append((rule["id"], summary))
    return kept, dropped


def cmd_rules(args) -> None:
    cases = wrong_cases(ROOT / "data" / "en_data" / f"{args.split.split('_')[1]}.json",
                        ROOT / f"{args.pred}.json", ROOT / args.results)
    print(f"{len(cases)} 道错题喂给 {args.backbone}")
    reply = _endpoint(args.backbone).chat_messages(
        [{"role": "user", "content": render(
            "distill.rules", cases=cases_block(cases),
            vocabulary=vocabulary_block(),
            min_evidence=str(args.min_evidence), max_items=str(args.max_items))}],
        temperature=0.0)
    raw = parse_items(reply, key="rules")
    legal = []
    for rule in raw:
        try:
            check_rule(rule)
            rule["needs_decl"] = bool(set(rule["when"]) & DECL_PREDICATES)
            legal.append(rule)
        except RuleError as e:
            print(f"  非法 {rule.get('id')}: {e}")
    kept, dropped = gate(legal, split=args.split, pred=args.pred,
                         results=args.results, min_trigger=args.min_trigger,
                         min_precision=args.min_precision)
    for rid, s in dropped:
        print(f"  未过闸 {rid}: 触发 {s['trigger']} useful {s['useful']} "
              f"harmful {s['harmful']} precision {s['precision']:.0%}")
    _write(Path(args.out), {
        "dataset": args.split,
        "distilled_by": _backbone_label(args.backbone),
        "distilled_at": _dt.date.today().isoformat(),
        "source_pred": args.pred,
        "gate": {"min_trigger": args.min_trigger, "min_precision": args.min_precision},
        "rules": kept,
    })


def main() -> None:
    ap = argparse.ArgumentParser(prog="distill")
    sub = ap.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("knowledge", help="蒸馏进 prompt 的知识条目")
    k.add_argument("--split", default="en_train")
    k.add_argument("--out", required=True)
    k.add_argument("--backbone", default="pro-t", choices=sorted(BACKBONES))
    k.add_argument("--pred", default=DEFAULT_PRED)
    k.add_argument("--results", default=DEFAULT_RESULTS)
    k.add_argument("--max-items", type=int, default=12)
    k.add_argument("--min-evidence", type=int, default=2)
    k.set_defaults(func=cmd_knowledge)

    r = sub.add_parser("rules", help="蒸馏进检查器的规则")
    r.add_argument("--split", default="en_train")
    r.add_argument("--out", required=True)
    r.add_argument("--backbone", default="pro-t", choices=sorted(BACKBONES))
    r.add_argument("--pred", default=DEFAULT_PRED)
    r.add_argument("--results", default=DEFAULT_RESULTS)
    r.add_argument("--max-items", type=int, default=12)
    r.add_argument("--min-evidence", type=int, default=2)
    r.add_argument("--min-trigger", type=int, default=5)
    r.add_argument("--min-precision", type=float, default=0.7)
    r.set_defaults(func=cmd_rules)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
