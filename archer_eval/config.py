"""Global configuration: every path and default the framework uses.

Change paths here (or override via CLI flags); nothing else hard-codes them.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data"
DB_DIR = ROOT / "database"
PREDICTIONS_DIR = ROOT / "predictions"
RESULTS_DIR = ROOT / "results"

# Shorthand names accepted by --data on the command line.
DATASETS = {
    "en_train": DATA_DIR / "en_data" / "train.json",
    "en_dev": DATA_DIR / "en_data" / "dev.json",
    "zh_train": DATA_DIR / "zh_data" / "train.json",
    "zh_dev": DATA_DIR / "zh_data" / "dev.json",
}

DEFAULT_TIMEOUT_S = 30.0  # per-query wall-clock limit
FLOAT_PRECISION = 6       # decimals kept when comparing float cells


def resolve_dataset(name_or_path: str) -> Path:
    """Accept either a shorthand ('en_dev') or an explicit file path."""
    if name_or_path in DATASETS:
        return DATASETS[name_or_path]
    return Path(name_or_path)
