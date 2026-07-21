"""SQL execution against SQLite databases.

- Databases are opened read-only (mode=ro), so destructive predicted SQL
  (DROP/DELETE/UPDATE) fails instead of corrupting the data.
- A wall-clock timeout aborts runaway queries via sqlite's progress handler.
- text_factory tolerates non-UTF-8 bytes present in some Spider databases.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import DEFAULT_TIMEOUT_S


def connect_ro(db_path: str | Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> sqlite3.Connection:
    """Read-only connection with tolerant text decoding."""
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=timeout_s)
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    return conn


@dataclass
class ExecutionResult:
    ok: bool
    rows: list[tuple] = field(default_factory=list)
    n_cols: int = 0
    error: str | None = None

    @property
    def n_rows(self) -> int:
        return len(self.rows)


def execute_sql(
    db_path: str | Path, sql: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> ExecutionResult:
    db_path = Path(db_path)
    if not db_path.exists():
        return ExecutionResult(ok=False, error=f"database not found: {db_path}")

    try:
        conn = connect_ro(db_path, timeout_s)
    except sqlite3.Error as e:
        return ExecutionResult(ok=False, error=f"{type(e).__name__}: {e}")

    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 100_000)

    try:
        cur = conn.execute(sql)
        rows = [tuple(r) for r in cur.fetchall()]
        n_cols = len(cur.description) if cur.description else (len(rows[0]) if rows else 0)
        return ExecutionResult(ok=True, rows=rows, n_cols=n_cols)
    except Exception as e:  # sqlite3.Error, OverflowError from weird casts, etc.
        return ExecutionResult(ok=False, error=f"{type(e).__name__}: {e}")
    finally:
        conn.close()
