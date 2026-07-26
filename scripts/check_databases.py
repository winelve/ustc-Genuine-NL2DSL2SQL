"""Verify every db_id referenced by the datasets has a usable SQLite file.

Usage:  python scripts/check_databases.py   (requires `pip install -e .` once)
"""

from pathlib import Path

import config
from archer_eval.data import load_dataset
from archer_eval.evaluate import find_db_file
from archer_eval.execution import execute_sql


def _check_root(db_root: Path, needed: dict[str, list[str]]) -> list[str]:
    """校验一个数据库根目录，返回缺失的 db_id 列表。"""
    print(f"\n=== {db_root} ===")
    if not db_root.exists():
        print(f"[skip] 目录不存在（BIRD 的库需先解压 dev_databases.zip）")
        return sorted(needed)

    missing = []
    for db_id in sorted(needed):
        try:
            path = find_db_file(db_root, db_id)
        except FileNotFoundError:
            print(f"[missing] {db_id}  (needed by {sorted(set(needed[db_id]))})")
            missing.append(db_id)
            continue
        res = execute_sql(path, "SELECT count(*) FROM sqlite_master WHERE type='table'")
        status = f"{res.rows[0][0]} tables" if res.ok else f"unreadable: {res.error}"
        print(f"[ok] {db_id:<35} {path.stat().st_size / 1024:>9.0f} KB  {status}")

    extra = sorted(d.name for d in db_root.iterdir() if d.is_dir() and d.name not in needed)
    if extra:
        print(f"unreferenced database folders: {extra}")
    return missing


def main() -> int:
    # 数据集各有自己的库根目录（config.db_dir_for），按根目录分组统计。
    # 两边都有 formula_1 且内容不同，混在一起统计会串库。
    by_root: dict[Path, dict[str, list[str]]] = {}
    for name, path in config.DATASETS.items():
        if not path.exists():
            print(f"[skip] dataset {name}: {path} 不存在")
            continue
        needed = by_root.setdefault(config.db_dir_for(name), {})
        for s in load_dataset(path):
            needed.setdefault(s.db_id, []).append(name)

    missing = {root: _check_root(root, needed) for root, needed in by_root.items()}
    n_missing = sum(len(v) for v in missing.values())
    n_needed = sum(len(v) for v in by_root.values())

    print()
    if n_missing:
        for root, ids in missing.items():
            if ids:
                print(f"{len(ids)} database(s) missing under {root}: {ids}")
        return 1
    print(f"all {n_needed} referenced databases present and readable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
