"""BIRD 适配层 CLI。

    python -m bird fetch                           # 下载官方题目和数据库压缩包
    python -m bird convert                                  # → data/bird/dev.json
    python -m bird preview --index 0                        # 看该题发出去的提示词
    python -m bird eval --pred predictions/xxx_bird_dev.json
    python -m bird eval --pred ... --official               # 用官方脚本报数
    python -m bird eval --pred ... --cross-check            # 两套实现必须一致
    python -m bird eval --gold-as-pred                      # 健全性（天花板）
    python -m bird scores                                   # 汇总成表

生成走原来的 runner：`python -m model --model bird-pro-t-direct --data bird_dev`。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import config
from archer_eval.data import load_dataset, load_predictions, resolve_dataset
from bird import dataset as dataset_mod
from bird import official, paths, scores
from bird.evaluate import evaluate_bird
from bird.official_eval.adapter import run_official

DEFAULT_OUT_DIR = config.RESULTS_DIR / "bird"


def _cmd_fetch(args) -> int:
    version = paths.VERSIONS[args.version]
    print(f"下载 {version.name}：{version.url}")
    dest = dataset_mod.fetch(version, args.out_dir)
    print(f"wrote {dest}  (sha256 ok: {version.sha256})")
    print("下一步：python -m bird convert")
    return 0


def _cmd_convert(args) -> int:
    version = paths.VERSIONS[args.version]
    src = args.src or paths.dev_raw(version)
    if not src.exists():
        print(f"官方题目文件不存在：{src}\n先跑 python -m bird fetch --version {version.name}")
        return 1
    if dataset_mod.sha256_of(src) != version.sha256:
        print(f"{src.name} 的 sha256 与 {version.name} 不符——考卷被换过，先查清楚再转换")
        return 1

    samples = dataset_mod.convert(src, args.out)
    out = args.out or paths.dev_dataset()
    print(f"wrote {out}  [{version.name}]  ({dataset_mod.summarize(samples)})")

    db_dir = paths.dev_databases_dir()
    if not db_dir.exists():
        print(f"note: {db_dir} 不存在——先解压 {paths.bird_dir() / 'dev_databases.zip'}")
    return 0


def _print_summary(report: dict, alias: str, label: str) -> None:
    s = report["summary"]
    print(f"\n{alias}  [{label}]: {s['n']} samples  EX {s['EX_pct']:.2f}%  "
          f"({s['n_match']}/{s['n']})")
    for level, m in report["by_difficulty"].items():
        print(f"  {level:<14} n={m['n']:<5} EX {m['EX_pct']:.2f}%")


def _cmd_eval(args, parser) -> int:
    if bool(args.pred) == args.gold_as_pred:
        parser.error("provide exactly one of --pred or --gold-as-pred")

    data_path = resolve_dataset(args.data)
    samples = load_dataset(data_path)
    if args.limit:
        samples = samples[: args.limit]

    if args.gold_as_pred:
        predictions = [s.query for s in samples]
        pred_name = "gold"
    else:
        predictions = load_predictions(args.pred)
        if args.limit:
            predictions = predictions[: args.limit]
        if len(predictions) != len(samples):
            raise ValueError(f"prediction count ({len(predictions)}) does not match "
                             f"dataset size ({len(samples)})")
        pred_name = Path(args.pred).stem

    db_dir = Path(args.db_dir) if args.db_dir else config.db_dir_for(args.data)
    alias = args.data if args.data in config.DATASETS else data_path.stem
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def write(report: dict, suffix: str) -> Path:
        report["meta"]["dataset"] = str(data_path)
        report["meta"]["pred"] = args.pred or "gold-as-pred"
        path = out_dir / f"{alias}_{pred_name}{suffix}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {path}")
        return path

    ours = official_report = None
    if not args.official or args.cross_check:
        ours = evaluate_bird(samples, predictions, db_dir, timeout_s=args.timeout, progress=True)
        _print_summary(ours, alias, "本项目实现")
        write(ours, "")

    if args.official or args.cross_check:
        official_report = run_official(
            samples, predictions, db_dir,
            work_dir=out_dir / f"_official_{pred_name}",
            timeout_s=args.timeout, num_cpus=args.num_cpus)
        _print_summary(official_report, alias, "官方脚本")
        write(official_report, ".official")

    if args.cross_check:
        a, b = ours["summary"], official_report["summary"]
        same = a["n_match"] == b["n_match"]
        print(f"\ncross-check: 本项目 {a['n_match']}/{a['n']} vs "
              f"官方 {b['n_match']}/{b['n']} → {'一致 ✅' if same else '不一致 ❌'}")
        if not same:
            return 1
    return 0


def _cmd_preview(args) -> int:
    samples = load_dataset(resolve_dataset(args.data))
    sample = samples[args.index]
    db_dir = config.db_dir_for(args.data)

    from archer_eval.evaluate import find_db_file
    prompt = official.official_prompt(sample, find_db_file(db_dir, sample.db_id),
                                      evidence=not args.no_evidence)
    print(f"# question_id={sample.extras.get('question_id', args.index)}  db={sample.db_id}  "
          f"difficulty={sample.extras.get('difficulty', '')}  "
          f"chars={len(prompt)}")
    print("=" * 78)
    print(prompt)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bird", description="BIRD 数据、提示词与官方口径评测")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser(
        "fetch",
        help="下载官方题目和数据库压缩包（校验 sha256）",
    )
    p_fetch.add_argument("--version", choices=sorted(paths.VERSIONS),
                        default=paths.SCORING.name, help="哪一版 dev（默认计分那版）")
    p_fetch.add_argument("--out-dir", type=Path, default=None)

    p_convert = sub.add_parser("convert", help="官方题目文件 → 本项目数据集格式")
    p_convert.add_argument("--version", choices=sorted(paths.VERSIONS),
                          default=paths.SCORING.name)
    p_convert.add_argument("--src", type=Path, default=None)
    p_convert.add_argument("--out", type=Path, default=None)

    p_eval = sub.add_parser("eval", help="按 BIRD 官方口径评测预测文件")
    p_eval.add_argument("--data", default="bird_dev", help="数据集简写或 JSON 路径")
    p_eval.add_argument("--pred", help="预测 JSON（与数据集同序）")
    p_eval.add_argument("--gold-as-pred", action="store_true", help="拿 gold 当预测，测天花板")
    p_eval.add_argument("--official", action="store_true",
                        help="用原样 vendor 的官方脚本报数（需要 func_timeout）")
    p_eval.add_argument("--cross-check", action="store_true",
                        help="两套实现都跑，逐题总数必须一致")
    p_eval.add_argument("--db-dir", default=None)
    p_eval.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p_eval.add_argument("--timeout", type=float, default=config.DEFAULT_TIMEOUT_S)
    p_eval.add_argument("--num-cpus", type=int, default=1,
                        help="官方脚本的进程数；调大会因抢磁盘导致重查询超时，分数不稳")
    p_eval.add_argument("--limit", type=int, help="只评前 N 条（冒烟）")

    p_prev = sub.add_parser("preview", help="打印某题实际发出去的官方提示词")
    p_prev.add_argument("--data", default="bird_dev")
    p_prev.add_argument("--index", type=int, default=0)
    p_prev.add_argument("--no-evidence", action="store_true", help="走官方的无知识分支")

    sub.add_parser("scores", help="results/bird/*.json → markdown 表")

    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        return _cmd_fetch(args)
    if args.cmd == "convert":
        return _cmd_convert(args)
    if args.cmd == "eval":
        return _cmd_eval(args, parser)
    if args.cmd == "scores":
        return scores.main()
    return _cmd_preview(args)


if __name__ == "__main__":
    raise SystemExit(main())
