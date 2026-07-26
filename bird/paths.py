"""BIRD 数据文件的位置与**数据集版本**——全项目只有这一个文件知道这两件事。

布局（`python -m bird fetch` + `python -m bird convert` 产出）：

    data/bird/
    ├── official/
    │   ├── dev_20251106.json  官方原始题目（计分用，见下），只读不改
    │   ├── dev_20240627.json  另一版官方题目，留作对照
    │   └── dev_tables.json    schema 元数据；官方 baseline 不用它，见 extras.py
    ├── dev.json               转换产物，= config.DATASETS["bird_dev"]
    ├── dev_databases/         11 个库，<db_id>/<db_id>.sqlite
    └── dev_databases.zip      库的恢复副本

## 两版 dev 对应榜单的两条线（**这一节是本文件存在的主要理由**）

BIRD 清洗过多次 dev，每次都在**同样的 question_id** 上换题面/换 gold。
两版题号一一对应、库完全相同，所以只换一个 json 就能切换——正因如此，
搞错了也不会报错，只会悄悄得到一个不可比的分数。故版本用 sha256 钉死。

| 版本 | 规模 | 榜单上谁在用 |
|---|---|---|
| **`dev_20251106`（计分用）** | simple 860 / moderate 443 / challenging 231 | **`DeepSeek-R1 (Baseline)` Dev 61.67**（Single Trained Model 赛道，标 "New Dev"） |
| `dev_20240627` | simple 925 / moderate 464 / challenging 145 | 主榜 EX 那张表：GPT-4 46.35、DeepSeek 56.13、AskData + GPT-4o 77.64 |

两版差异（逐题比对实测）：182 题问题被改写、450 条 gold SQL 被改、
gold 平均长度 161 → 278 字符、challenging 从 145 涨到 231。**dev-1106 明显更难**，
所以两版的分数**不可互比**，各自只跟同版的榜单行比。

本项目对齐 `DeepSeek-R1 (Baseline)`（reasoning 骨干 + 单模型 + 单次调用，
与我们的档位形态最接近），所以计分用 dev-1106。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import config


@dataclass(frozen=True)
class DevVersion:
    """一版官方 dev 题目文件：文件名 + 下载地址 + sha256。"""

    name: str
    filename: str
    url: str
    sha256: str
    counts: str

    @property
    def is_zip(self) -> bool:
        return self.url.endswith(".zip")


DEV_20251106 = DevVersion(
    name="dev_20251106",
    filename="dev_20251106.json",
    url=("https://huggingface.co/datasets/birdsql/bird_sql_dev_20251106"
         "/resolve/main/data/dev_20251106-00000-of-00001.json"),
    sha256="ffd8018378ddb1a8794753e0a31cfc81862ff7318a5184c22f3dc4ce03a03feb",
    counts="1534 题，simple 860 / moderate 443 / challenging 231，1377 题带 evidence",
)

DEV_20240627 = DevVersion(
    name="dev_20240627",
    filename="dev_20240627.json",
    url="https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip",   # 约 330 MB
    sha256="630272f2b1c44d8cef2c3b246f623355cf0bbc1e832c81061df895530dfc2f06",
    counts="1534 题，simple 925 / moderate 464 / challenging 145，1386 题带 evidence",
)

VERSIONS = {v.name: v for v in (DEV_20251106, DEV_20240627)}

# 计分用的那一版。改这一行 = 换考卷，改完必须重跑 gold-as-pred 与全部预测。
SCORING = DEV_20251106

# 包里 schema 元数据的成员名（只有 dev.zip 那版带它；库不变，两版通用）
DEV_TABLES_MEMBER = "dev_tables.json"


def bird_dir() -> Path:
    """`data/bird/`。"""
    return config.DATA_DIR / "bird"


def official_dir() -> Path:
    """官方原始文件目录。"""
    return bird_dir() / "official"


def dev_raw(version: DevVersion | None = None) -> Path:
    """某一版官方题目文件的落盘位置。"""
    return official_dir() / (version or SCORING).filename


def dev_dataset() -> Path:
    """转换产物（本项目数据集格式）。"""
    return config.DATASETS["bird_dev"]


def dev_databases_dir() -> Path:
    """SQLite 库根目录，布局 `<root>/<db_id>/<db_id>.sqlite`。两版共用。"""
    return config.DATASET_DB_DIRS["bird_dev"]


def tables_json() -> Path:
    """官方 schema 元数据（自然语言表/列名 + 主键 + 外键）。非官方口径专用。"""
    return official_dir() / DEV_TABLES_MEMBER


def description_dir(db_id: str, root: Path | None = None) -> Path:
    """某个库的列描述 CSV 目录。非官方口径专用。"""
    return (root or dev_databases_dir()) / db_id / "database_description"
