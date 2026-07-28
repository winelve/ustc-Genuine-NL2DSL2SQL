"""BIRD benchmark 适配层（https://bird-bench.github.io/）。

    python -m bird fetch       # 下载官方题目和数据库压缩包（sha256 钉死）
    python -m bird convert     # → data/bird/dev.json，即 --data bird_dev
    python -m bird preview --index 0          # 看某题实际发出去的提示词
    python -m bird eval --pred predictions/<模型>_bird_dev.json
    python -m bird eval --official --pred ... # 用原样 vendor 的官方脚本报数
    python -m bird scores      # results/bird/*.json → markdown 表

模块分工：

- `paths`         数据文件在哪 + 数据集版本的 sha256
- `dataset`       下载与格式转换
- `official`      **官方 baseline 的提示词**（唯一知道它长什么样的地方）
- `official_eval` 原样 vendor 的官方评测脚本 + 输入输出适配器（报数以它为准）
- `evaluate`      同口径的本项目实现：快、只读、出逐题明细
- `scores`        结果汇总成表
- `extras`        列描述 / 外键等**非官方**资料 —— 官方 baseline 不用，故不在此导出

模型档位不在本包里：`MODELS` 注册在 `model/` 是框架铁律，BIRD 的档位在 `model/bird.py`。
"""

from bird.dataset import convert, fetch
from bird.evaluate import evaluate_bird, evaluate_bird_sample, rows_match
from bird.official import comment_block, official_prompt, schema_ddl_block

__all__ = [
    "fetch", "convert",
    "official_prompt", "schema_ddl_block", "comment_block",
    "evaluate_bird", "evaluate_bird_sample", "rows_match",
]
