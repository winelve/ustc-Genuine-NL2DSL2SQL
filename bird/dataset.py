"""取得官方 dev 题目文件，并转成本项目的数据集格式。

    python -m bird fetch                      # 计分那一版（bird/paths.py 的 SCORING）
    python -m bird fetch --version dev_20240627
    python -m bird convert                    # 官方 json → data/bird/dev.json

字段映射（其余字段进 `Sample.extras`）：

    SQL      -> query                   （archer_eval.data.load_dataset 认这个名字）
    evidence -> commonsense_knowledge    （BIRD 的外部知识；官方协议把它当输入）

两版 dev 的取法不同：dev-1106 在 HuggingFace 上是一个 940 KB 的裸 json；
dev-20240627 在官网 `dev.zip`（330 MB）里，只取包内那两个小文件——库若已解压
在 `dev_databases/` 就不动它，不为 740 KB 的题目重解 1.4 GB。
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

from bird import paths

_CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=900) as response:
        with dest.open("wb") as fh:
            while chunk := response.read(_CHUNK):
                fh.write(chunk)


def _member(archive: zipfile.ZipFile, name: str) -> str:
    """在包里按文件名找成员（官方把东西放在 dev_20240627/ 下面）。"""
    for member in archive.namelist():
        if Path(member).name == name:
            return member
    raise RuntimeError(f"包里没有 {name}（成员：{archive.namelist()}）")


def fetch(version: paths.DevVersion | None = None, out_dir: Path | None = None) -> Path:
    """下载某一版官方题目文件并校验哈希。

    哈希不符**不留下坏文件**，直接抛错——那意味着 BIRD 又清洗了一版，
    继续跑出来的分数就不能跟对应的榜单行并排了。
    """
    version = version or paths.SCORING
    out_dir = out_dir or paths.official_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        downloaded = Path(tmp) / "download"
        _download(version.url, downloaded)

        if version.is_zip:
            with zipfile.ZipFile(downloaded) as archive:
                payload = archive.read(_member(archive, "dev.json"))
                tables = archive.read(_member(archive, paths.DEV_TABLES_MEMBER))
            (out_dir / paths.DEV_TABLES_MEMBER).write_bytes(tables)
        else:
            payload = downloaded.read_bytes()

    got = hashlib.sha256(payload).hexdigest()
    if got != version.sha256:
        raise RuntimeError(
            f"{version.name} 的 sha256 不符：期望 {version.sha256}，实得 {got}。\n"
            "BIRD 可能又清洗了一版——先确认要对齐的榜单行用的是哪一份，"
            "再更新 bird/paths.py 里的版本记录。")

    dest = out_dir / version.filename
    dest.write_bytes(payload)
    return dest


def convert(src: Path | None = None, out: Path | None = None) -> list[dict]:
    """官方题目 json → 本项目格式，返回写出的样本列表。"""
    src = src or paths.dev_raw()
    out = out or paths.dev_dataset()
    raw = json.loads(src.read_text(encoding="utf-8"))

    samples = [
        {
            "db_id": item["db_id"],
            "question": item["question"],
            "query": item["SQL"],
            "commonsense_knowledge": (item.get("evidence") or "").strip() or None,
            "question_id": item["question_id"],
            "difficulty": item.get("difficulty", ""),
        }
        for item in raw
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")
    return samples


def summarize(samples: list[dict]) -> str:
    n_evidence = sum(bool(s["commonsense_knowledge"]) for s in samples)
    difficulty = dict(Counter(s["difficulty"] for s in samples))
    return (f"{len(samples)} samples, {n_evidence} with evidence, "
            f"{len({s['db_id'] for s in samples})} databases, difficulty={difficulty}")
