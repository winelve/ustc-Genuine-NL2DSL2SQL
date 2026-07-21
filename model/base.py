"""模型接口契约：所有模型（GPT、T5、本地模型…）都实现这一个类。

实现者只需要做两件事：
  1. 给 `name` 赋一个短名（用于预测文件命名，如 first_table、gpt35_ct3）
  2. 实现 `predict()`：一条样本进，一条 SQL 出

必须遵守的约定（详见 docs/DEVELOPMENT.md）：
  - 返回值是**纯 SQL 字符串**，不能带解释文字、markdown 代码块标记；
  - 不要试图写数据库（评测阶段只读打开，写操作会直接判 VA=0）；
  - 某条样本生成失败时返回空串 ""（评测会记为不可执行），不要抛异常中断整批；
  - 论文主设定下不使用 sample.commonsense_knowledge（那是题目难度的一部分），
    只有做 §6.2 类分析实验时才用；
  - 样本的顺序、数量、落盘由 runner（python -m model）负责，实现者不用管。
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
        """默认逐条调用 predict；需要批量/并发调 API 的模型可以覆写它。"""
        preds = []
        for i, (sample, db_path) in enumerate(zip(samples, db_paths)):
            try:
                preds.append(self.predict(sample, db_path))
            except Exception as e:
                print(f"  [warn] sample {i} failed: {type(e).__name__}: {e}")
                preds.append("")
            if progress and (i + 1) % 20 == 0:
                print(f"  generated {i + 1}/{len(samples)}")
        return preds
