"""Verify every db_id referenced by the datasets has a usable SQLite file.

Usage:  python scripts/check_databases.py   (requires `pip install -e .` once)
"""

from pathlib import Path

import config
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
            path = find_db_file(config.DB_DIR, db_id)
        except FileNotFoundError:
            print(f"[missing] {db_id}  (needed by {sorted(set(needed[db_id]))})")
            missing.append(db_id)
            continue
        res = execute_sql(path, "SELECT count(*) FROM sqlite_master WHERE type='table'")
        status = f"{res.rows[0][0]} tables" if res.ok else f"unreadable: {res.error}"
        print(f"[ok] {db_id:<35} {path.stat().st_size / 1024:>9.0f} KB  {status}")

    extra = sorted(
        d.name for d in Path(config.DB_DIR).iterdir() if d.is_dir() and d.name not in needed
    )
    if extra:
        print(f"unreferenced database folders: {extra}")
    if missing:
        print(f"{len(missing)} database(s) missing; download from Spider into database/<db_id>/")
        return 1
    print(f"all {len(needed)} referenced databases present and readable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
