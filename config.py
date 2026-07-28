"""全局配置：路径、数据集注册、默认参数。

增量原则：
- 跨模块的稳定常量（路径、超时、精度）放这里；
- 模型/实验专属的参数不预留字段，等模型出现时随实现走
  （构造函数参数，或 configs/<实验名>.toml，用标准库 tomllib 读）；
- 密钥只走环境变量，不进任何配置文件。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent

DATA_DIR = ROOT / "data"
FEWSHOT_DIR = DATA_DIR / "fewshot"
DB_DIR = ROOT / "database"
PREDICTIONS_DIR = ROOT / "predictions"
RESULTS_DIR = ROOT / "results"

# --data 参数接受的数据集简写
DATASETS = {
    "en_train": DATA_DIR / "en_data" / "train.json",
    "en_dev": DATA_DIR / "en_data" / "dev.json",
    "zh_train": DATA_DIR / "zh_data" / "train.json",
    "zh_dev": DATA_DIR / "zh_data" / "dev.json",
    # BIRD dev（官方 2025-11-06 清洗版，1534 题）：
    # python -m bird fetch && python -m bird convert
    "bird_dev": DATA_DIR / "bird" / "dev.json",
    # BIRD 旧版 dev（2024-06-27）；与新版共用数据库，但题面和 gold 不同。
    "bird_dev_20240627": DATA_DIR / "bird" / "dev_20240627.json",
}

# 自带数据库的数据集，在这里登记它的 SQLite 根目录（布局同样是
# <root>/<db_id>/<db_id>.sqlite）；没登记的数据集一律用 DB_DIR。
DATASET_DB_DIRS = {
    "bird_dev": DATA_DIR / "bird" / "dev_databases",
    "bird_dev_20240627": DATA_DIR / "bird" / "dev_databases",
}


def db_dir_for(dataset: str | Path | None) -> Path:
    """数据集简写或路径 → 数据库根目录。

    传简写按 DATASET_DB_DIRS 查；传路径则看它跟哪个已登记数据集同目录——
    抽样子集（data/bird/dev_s100.json）因此能自动沿用同一批库。
    都不匹配一律回落 DB_DIR，保证 Archer 侧行为不变。
    """
    if dataset in DATASET_DB_DIRS:
        return DATASET_DB_DIRS[dataset]
    if dataset:
        parent = Path(dataset).resolve().parent
        for name, db_dir in DATASET_DB_DIRS.items():
            if name in DATASETS and DATASETS[name].parent == parent:
                return db_dir
    return DB_DIR


DEFAULT_TIMEOUT_S = 30.0  # 单条查询的墙钟超时
FLOAT_PRECISION = 6       # 浮点单元格比较时保留的小数位


# API MODEL config
API_CONCURRENCY = 10 # 并发的数量限制
