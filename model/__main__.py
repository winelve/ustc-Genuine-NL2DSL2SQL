"""Stage-1 runner: run a registered model, write a standard prediction file.

    python -m model --model first_table --data en_dev          # generate only
    python -m model --model first_table --data en_dev --eval   # generate then evaluate

The runner loads the dataset, resolves database paths, calls the model per
sample, keeps output aligned with the dataset, and writes
predictions/<model>_<data>.json. Model classes only implement predict().

**Checkpointing**: samples run in chunks and every finished chunk is appended to
predictions/<model>_<data>.partial.jsonl right away. Re-running the same command
skips whatever is already in there, so a crash / timeout / Ctrl-C in hour three of
a 1534-question run costs one chunk, not the whole run. The partial file is
deleted once the final prediction file is written. Use --chunk 0 to turn it off.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import config
from archer_eval.data import load_dataset, resolve_dataset
from archer_eval.evaluate import evaluate, find_db_file
from archer_eval.report import make_meta, report_name, write_report
from model import MODELS

DEFAULT_CHUNK = 50
TRACE_SCHEMA = "question-metrics-v1"

SWITCH_COLUMNS = ("plan", "声明层", "知识", "evidence", "L2规则", "SQLens", "重试")


def switch_matrix() -> list[tuple[str, dict]]:
    """每个注册档位开了哪些开关。从类属性直接读，不会与代码脱节。"""
    rows = []
    for name, cls in MODELS.items():
        has_dsl = hasattr(cls, "max_repairs")
        rows.append((name, {
            "plan": "✓" if getattr(cls, "n_plans", 0) and _uses_plan(cls) else "-",
            "声明层": "✓" if has_dsl else "-",
            "知识": "✓" if getattr(cls, "knowledge", False) else "-",
            "evidence": "✓" if getattr(cls, "evidence", False) else "-",
            "L2规则": "✓" if getattr(cls, "learned_rules", False) else "-",
            "SQLens": "✓" if getattr(cls, "sqlens_checks", False) else "-",
            "重试": str(getattr(cls, "max_repairs", "-")),
        }))
    return rows


def _uses_plan(cls) -> bool:
    """no-plan 档位（ProTDsl 系）在类上显式声明 use_plan=False；直接读类属性，
    不实例化——实例化会立即构造真实 ChatEndpoint，在没有 API key 的机器上
    会全部报错（虽有 except 兜底，但会把所有档位误判成 no-plan）。"""
    return getattr(cls, "use_plan", True)


def print_switches() -> None:
    rows = switch_matrix()
    width = max(len(n) for n, _ in rows) + 2
    print("档位".ljust(width) + "  ".join(c.rjust(8) for c in SWITCH_COLUMNS))
    for name, flags in rows:
        print(name.ljust(width) + "  ".join(
            flags[c].rjust(8) for c in SWITCH_COLUMNS))


def write_trace(traces, predictions_path: Path) -> Path | None:
    """把模型自报的调试记录写成预测文件旁的 .trace.json；没有就什么都不做。

    钩子约定：模型实例暴露 trace_records（与预测同序的 dict 列表）即可，
    评测器不感知这个文件（两段仍只通过预测文件通信）。
    """
    if not traces or not any(t is not None for t in traces):
        return None
    trace_path = predictions_path.with_name(predictions_path.stem + ".trace.json")
    trace_path.write_text(json.dumps(traces, ensure_ascii=False, indent=1), encoding="utf-8")
    return trace_path


def _checkpoint_path(predictions_path: Path) -> Path:
    return predictions_path.with_name(predictions_path.stem + ".partial.jsonl")


def _read_checkpoint(path: Path, stamp: dict) -> dict[int, dict]:
    """读断点文件。指纹对不上（换了数据集/题量）就当它不存在，绝不错位续跑。"""
    if not path.exists():
        return {}
    done: dict[int, dict] = {}
    header_seen = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue                      # 崩在半行上，丢掉这行即可
        if not header_seen:
            header_seen = True
            if record != stamp:
                print(f"note: {path.name} 是另一次运行留下的（指纹不符），忽略并重跑")
                return {}
            continue
        done[record["i"]] = record
    return done


def _run_with_checkpoint(
    generator, samples, db_paths, out: Path, chunk: int,
    *, alias: str = "", total: int | None = None,
) -> tuple[list, list]:
    """分块跑，每块落盘。返回 (predictions, traces)，都与 samples 同序。

    `total` = 数据集的完整题量（`--limit` 之前）。断点按**数据集下标**存，所以
    `--limit 500` 跑完再跑全量时，前 500 题直接复用，只补 500..total-1。
    断点文件只在整个数据集都跑完后才删。
    """
    total = len(samples) if total is None else total
    stamp = {
        "model": generator.name,
        "data": alias,
        "n": total,
        "trace_schema": TRACE_SCHEMA,
    }
    ckpt = _checkpoint_path(out)
    done = _read_checkpoint(ckpt, stamp) if chunk else {}
    done = {i: r for i, r in done.items() if i < len(samples)}   # 本次只关心这一段
    if done:
        print(f"resuming: 本段 {len(samples)} 题里已有 {len(done)} 题在 {ckpt.name} 里，跳过")
    elif chunk:
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        ckpt.write_text(json.dumps(stamp, ensure_ascii=False) + "\n", encoding="utf-8")

    todo = [i for i in range(len(samples)) if i not in done]
    size = chunk if chunk else max(len(todo), 1)

    for start in range(0, len(todo), size):
        batch = todo[start : start + size]
        if chunk:
            print(f"chunk {start // size + 1}/{-(-len(todo) // size)}  "
                  f"({len(done)}/{len(samples)} done)")
        preds = generator.predict_all([samples[i] for i in batch],
                                      [db_paths[i] for i in batch])
        traces = getattr(generator, "trace_records", None) or [None] * len(batch)

        lines = []
        for offset, i in enumerate(batch):
            record = {"i": i, "sql": preds[offset],
                      "trace": traces[offset] if offset < len(traces) else None}
            done[i] = record
            lines.append(json.dumps(record, ensure_ascii=False))
        if chunk:
            with ckpt.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")

    predictions = [done[i]["sql"] for i in range(len(samples))]
    trace_provider = getattr(generator, "trace_for_sample", None)
    trace_records = []
    for i, sample in enumerate(samples):
        trace = done[i].get("trace")
        if trace is None and callable(trace_provider):
            trace = trace_provider(sample)
        trace_records.append(trace)
    return predictions, trace_records


def main() -> None:
    parser = argparse.ArgumentParser(prog="model", description="Run a SQL generator on a dataset")
    parser.add_argument("--model", choices=sorted(MODELS),
                        help="registered model name (see model/__init__.py)")
    parser.add_argument("--data",
                        help=f"one of {', '.join(config.DATASETS)} or a JSON file path")
    parser.add_argument("--limit", type=int, help="only run the first N samples (smoke test)")
    parser.add_argument("--chunk", type=int, default=DEFAULT_CHUNK,
                        help="checkpoint every N samples (0 = no checkpointing)")
    parser.add_argument("--eval", action="store_true", help="evaluate right after generating")
    parser.add_argument("--list", action="store_true",
                        help="打印所有档位的开关矩阵后退出")
    args = parser.parse_args()

    if args.list:
        print_switches()
        return
    if not args.model or not args.data:
        parser.error("--model 与 --data 必填（或用 --list 查看档位）")

    data_path = resolve_dataset(args.data)
    samples = load_dataset(data_path)
    db_dir = config.db_dir_for(args.data)
    total = len(samples)
    if args.limit:
        samples = samples[: args.limit]

    generator = MODELS[args.model]()
    db_paths = [find_db_file(db_dir, s.db_id) for s in samples]
    print(f"{generator.name} on {data_path.name}: {len(samples)}/{total} samples")

    alias = args.data if args.data in config.DATASETS else data_path.stem
    out = config.PREDICTIONS_DIR / f"{generator.name}_{alias}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    predictions, traces = _run_with_checkpoint(generator, samples, db_paths, out,
                                               args.chunk, alias=alias, total=total)

    out.write_text(json.dumps(predictions, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}  ({len(predictions)}/{total})")

    if len(predictions) == total:
        _checkpoint_path(out).unlink(missing_ok=True)
    elif args.chunk:
        # 只跑了一段：断点留着，下次跑全量时这一段直接复用
        print(f"断点保留在 {_checkpoint_path(out).name}——"
              f"去掉 --limit 重跑本命令即可只补剩下的 {total - len(predictions)} 题")

    trace_path = write_trace(traces, out)
    if trace_path:
        print(f"wrote {trace_path}")

    if args.eval:
        report = evaluate(samples, predictions, db_dir, progress=True)
        report = {"meta": make_meta(data_path, out, db_dir, config.DEFAULT_TIMEOUT_S), **report}
        s = report["summary"]
        json_path = write_report(report, config.RESULTS_DIR, report_name(alias, generator.name))
        print(f"VA {s['VA']:.2%}  EX {s['EX']:.2%}  SIM {s['SIM']:.2%}")
        print(f"wrote {json_path}")


if __name__ == "__main__":
    main()
