"""Command-line entry point for offline few-shot retrieval artifacts."""

from __future__ import annotations

from pathlib import Path
import sys


# Direct script execution puts ``scripts/`` rather than the repository root on
# sys.path.  Add the root so the documented Windows command works from a clone.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.fewshot.offline import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
