"""模型接口：所有模型（GPT、T5、本地模型…）实现同一个类。

实现要求（详见 docs/DEVELOPMENT.md §3.2）：
  - 设定 `name`（用于预测文件命名）；实现 `predict()`：一条样本进，一条 SQL 出
  - 返回纯 SQL 字符串，不含解释文字或 markdown 代码块标记
  - 不写数据库（评测阶段只读打开，写操作会判 VA=0）
  - 单条失败返回空串 ""，不要抛异常中断整批
  - 论文主设定不使用 sample.commonsense_knowledge，仅分析实验用
  - 顺序、数量、落盘由 runner（python -m model）负责
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from archer_eval.data import Sample


class SQLGenerator(ABC):
    name: str = "base"

    @abstractmethod
    def predict(self, sample: Sample, db_path: Path) -> str:
        """为一条样本生成一条 SQLite SQL。"""

    def predict_all(
        self, samples: list[Sample], db_paths: list[Path], progress: bool = True
    ) -> list[str]:
        """默认逐条调用 predict；需要批量/并发调 API 的模型可覆写。"""
        preds = []
        for i, (sample, db_path) in enumerate(zip(samples, db_paths)):
            try:
                preds.append(self.predict(sample, db_path))
            except Exception as e:
                print(f"  sample {i} failed: {type(e).__name__}: {e}")
                preds.append("")
            if progress and (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(samples)}")
        return preds
