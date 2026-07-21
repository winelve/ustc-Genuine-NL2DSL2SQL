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
DB_DIR = ROOT / "database"
PREDICTIONS_DIR = ROOT / "predictions"
RESULTS_DIR = ROOT / "results"

# --data 参数接受的数据集简写
DATASETS = {
    "en_train": DATA_DIR / "en_data" / "train.json",
    "en_dev": DATA_DIR / "en_data" / "dev.json",
    "zh_train": DATA_DIR / "zh_data" / "train.json",
    "zh_dev": DATA_DIR / "zh_data" / "dev.json",
}

DEFAULT_TIMEOUT_S = 30.0  # 单条查询的墙钟超时
FLOAT_PRECISION = 6       # 浮点单元格比较时保留的小数位


# API MODEL config
API_CONCURRENCY = 10 # 并发的数量限制