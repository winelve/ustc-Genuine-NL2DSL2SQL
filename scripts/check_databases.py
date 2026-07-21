"""Verify every db_id referenced by the dataset has a usable SQLite file.

Usage:  python scripts/check_databases.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archer_eval import config
from archer_eval.data import load_dataset
from archer_eval.evaluate import find_db_file
from archer_eval.execution import execute_sql


def main() -> int:
    needed: dict[str, list[str]] = {}
    for name, path in config.DATASETS.items():
        for s in load_dataset(path):
            needed.setdefault(s.db_id, []).append(name)

    missing = []
    for db_id in sorted(needed):
        try:
            path = find_db_file("database", db_id)
        except FileNotFoundError:
            print(f"[MISSING] {db_id}  (needed by {sorted(set(needed[db_id]))})")
            missing.append(db_id)
            continue
        res = execute_sql(path, "SELECT count(*) FROM sqlite_master WHERE type='table'")
        status = f"{res.rows[0][0]} tables" if res.ok else f"UNREADABLE: {res.error}"
        print(f"[ok] {db_id:<35} {path.stat().st_size / 1024:>9.0f} KB  {status}")

    extra = sorted(
        d.name for d in Path("database").iterdir() if d.is_dir() and d.name not in needed
    )
    if extra:
        print(f"\nUnreferenced database folders: {extra}")
    if missing:
        print(f"\n{len(missing)} database(s) missing — download from Spider and place under database/<db_id>/")
        return 1
    print(f"\nAll {len(needed)} referenced databases present and readable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
