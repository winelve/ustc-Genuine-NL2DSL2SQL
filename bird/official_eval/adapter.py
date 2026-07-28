"""把本项目的预测喂给**未经改动的**官方评测脚本，并读回它打印的数字。

    python -m bird eval --official --pred predictions/xxx_bird_dev.json

`evaluation.py` 是原样 vendor 的官方脚本（来源见 SOURCE.md），这里只做三件事：

1. 生成官方要的三个输入文件（格式见 SOURCE.md）；
2. **以子进程方式**调它（不 import——它的 `mp.Pool` 在 `__main__` 守卫里，
   Windows 的 spawn 只有作为顶层脚本运行才正常）；
3. 解析它打印的那张表。

**gold 与预测的空白都会被压成一行**：官方 `dev_gold.sql` 是按行读的，新版 dev
的 gold 大量带换行（CTE），不压就会串行。SQL 对空白不敏感，语义不受影响。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import config

SEPARATOR = "\t----- bird -----\t"
SCRIPT = Path(__file__).with_name("evaluation.py")
DATA_MODE = "dev"

_COUNT_LINE = re.compile(r"^count\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", re.MULTILINE)
_ACC_LINE = re.compile(
    r"^accuracy\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", re.MULTILINE)
_LEVELS = ("simple", "moderate", "challenging")


def _run_with_heartbeat(
    cmd: list[str],
    *,
    heartbeat_s: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """捕获官方输出，同时定期说明子进程仍在运行。"""
    started = time.monotonic()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8")
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=heartbeat_s)
            return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            elapsed = round(time.monotonic() - started)
            print(f"official-eval: 官方脚本仍在运行（已用时 {elapsed}s）", flush=True)


def strip_sql_comments(sql: str) -> str:
    """去掉 `--` 行注释与 `/* */` 块注释，**字符串字面量里的不动**。

    压成一行之前必须先做这一步：dev-1106 有 4 条 gold 带 `--` 行注释
    （#3/#11/#19/#32，全是 challenging），直接把换行换成空格会让 `--` 之后的整条
    查询都变成注释，官方脚本因此把它们判 0——那是格式问题，不是模型答错。
    注释对语义无影响，去掉是安全的。
    """
    out: list[str] = []
    quote = None
    i, n = 0, len(sql or "")
    while i < n:
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                if quote in "'\"" and i + 1 < n and sql[i + 1] == quote:
                    out.append(sql[i + 1])       # SQL 里 '' 是转义的单引号
                    i += 2
                    continue
                quote = None
            i += 1
        elif ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
        elif ch == "-" and sql.startswith("--", i):
            while i < n and sql[i] != "\n":
                i += 1
            out.append(" ")
        elif ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _one_line(sql: str) -> str:
    """官方的 `dev_gold.sql` 是一行一题，所以必须先去注释再压平。"""
    return " ".join(strip_sql_comments(sql or "").split())


def write_inputs(samples, predictions, work_dir: Path) -> tuple[Path, Path]:
    """写出 `predict_dev.json` 与 `dev_gold.sql`，返回两者路径。"""
    work_dir.mkdir(parents=True, exist_ok=True)

    pred_path = work_dir / f"predict_{DATA_MODE}.json"
    pred_path.write_text(
        json.dumps(
            {str(i): f"{_one_line(p)}{SEPARATOR}{s.db_id}"
             for i, (s, p) in enumerate(zip(samples, predictions))},
            ensure_ascii=False, indent=1),
        encoding="utf-8")

    gold_path = work_dir / f"{DATA_MODE}_gold.sql"
    gold_path.write_text(
        "".join(f"{_one_line(s.query)}\t{s.db_id}\n" for s in samples),
        encoding="utf-8")
    return pred_path, gold_path


def write_difficulty(samples, work_dir: Path) -> Path:
    """官方按 `--diff_json_path` 分难度，只用到每项的 `difficulty` 字段。"""
    path = work_dir / "difficulty.json"
    path.write_text(
        json.dumps([{"difficulty": s.extras.get("difficulty", "")} for s in samples],
                   ensure_ascii=False, indent=1),
        encoding="utf-8")
    return path


def parse_output(stdout: str) -> dict:
    """解析官方 `print_data` 打印的两行表格。解析不出来就抛错，绝不猜数字。"""
    counts = _COUNT_LINE.search(stdout)
    accs = _ACC_LINE.search(stdout)
    if not (counts and accs):
        raise RuntimeError(f"官方脚本的输出解析不了：\n{stdout}")

    n_all = int(counts.group(4))
    by_difficulty = {
        level: {"n": int(counts.group(i + 1)), "EX_pct": float(accs.group(i + 1))}
        for i, level in enumerate(_LEVELS)
    }
    for metrics in by_difficulty.values():
        metrics["n_match"] = round(metrics["n"] * metrics["EX_pct"] / 100)

    ex_pct = float(accs.group(4))
    return {
        "summary": {"n": n_all, "n_match": round(n_all * ex_pct / 100),
                    "EX": round(ex_pct / 100, 4), "EX_pct": ex_pct},
        "by_difficulty": by_difficulty,
    }


def run_official(
    samples,
    predictions,
    db_dir: Path,
    *,
    work_dir: Path,
    timeout_s: float = config.DEFAULT_TIMEOUT_S,
    num_cpus: int = 1,
) -> dict:
    """跑官方脚本，返回与 `bird.evaluate` 同形状的报告 dict。

    `num_cpus` 默认 1（官方脚本自己的默认值）。**别为了快调大**：30s 是墙钟超时，
    多进程并行会互相抢磁盘，让本来 20 多秒能跑完的重查询超时判 0，分数因此不稳定。
    实测 `--num-cpus 4` 比串行多挂 1 题（gold-as-pred，dev-1106）。
    """
    if len(samples) != len(predictions):
        raise ValueError(f"{len(samples)} samples but {len(predictions)} predictions")

    write_inputs(samples, predictions, work_dir)
    diff_path = write_difficulty(samples, work_dir)

    cmd = [
        sys.executable, str(SCRIPT),
        "--predicted_sql_path", f"{work_dir.as_posix()}/",
        "--ground_truth_path", f"{work_dir.as_posix()}/",
        "--data_mode", DATA_MODE,
        "--db_root_path", f"{Path(db_dir).as_posix()}/",
        "--diff_json_path", str(diff_path),
        "--num_cpus", str(num_cpus),
        "--meta_time_out", str(timeout_s),
    ]
    print("official-eval: 开始运行官方脚本（串行评测）", flush=True)
    proc = _run_with_heartbeat(cmd)
    if proc.returncode != 0:
        raise RuntimeError(
            f"官方脚本退出码 {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")

    report = parse_output(proc.stdout)
    # 官方脚本用 pool.apply_async 且没有 error_callback：子进程崩了会被静默吞掉，
    # 结果数变少而分母照算。这里守住——题数对不上就不认这个数。
    if report["summary"]["n"] != len(samples):
        raise RuntimeError(
            f"官方脚本只评了 {report['summary']['n']} 题，应为 {len(samples)}——"
            f"多半有子进程崩了。\n{proc.stdout}")

    report["meta"] = {
        "protocol": "bird-official-script",
        "script": str(SCRIPT),
        "source": "AlibabaResearch/DAMO-ConvAI bird/llm/src/evaluation.py (unmodified)",
        "timeout_s": timeout_s,
        "num_cpus": num_cpus,
        "db_dir": str(db_dir),
        "note": "官方脚本只打印分档百分比，没有逐题结果；逐题明细用 bird.evaluate",
    }
    report["stdout"] = proc.stdout
    return {"meta": report.pop("meta"), **report}
