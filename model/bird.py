"""BIRD 的模型档位——**唯一目标是跟官方榜单可比**。

对齐的是榜单上 `DeepSeek-R1 (Baseline)` 那一行（Single Trained Model 赛道，
Dev 61.67 / Test 60.93，New Dev，Self Consistency 空 = 单候选）：

| | 榜单那行 | 我们 |
|---|---|---|
| 骨干 | DeepSeek-R1（reasoning） | deepseek-v4-pro + thinking |
| 提示词 | 官方 baseline | `bird.official.official_prompt`，逐字复刻 |
| 外部知识 evidence | 给（BIRD 协议默认，主榜 Oracle 列全 ✔️） | 给 |
| 候选数 | 1 | 1 |
| 指标 | 官方 EX | 官方 EX（`python -m bird eval --official`） |

**骨干不同，所以 61.67 是参照点不是复现目标**，报数时必须写清楚。

Archer 侧的东西一律不掺：不走 pipeline，不注入约定表 K1–K11，不用带样本行的
CT-3 schema。这个档位与 `model/prompts.py`、`model/pipeline/` 零耦合。
"""

from __future__ import annotations

from pathlib import Path

from archer_eval.data import Sample
from bird.official import official_prompt
from model.api import APIModel, extract_sql


class BirdDirect(APIModel):
    """官方 baseline 口径的单次调用直出。

    与 `model.api.APIModel` 的两处不同，都是为了对齐官方脚本：

    - **不发 system message**——官方 `messages=[{"role": "user", ...}]` 只有一条；
    - **不发 temperature / stop / max_tokens**——官方那套 `stop=["--","\\n\\n",";","#"]`
      与 `max_tokens=512` 是给 completion 式短输出设的，thinking 模型遇到第一个
      空行就会被截断。thinking 模式本来也静默忽略采样参数，发了等于假装生效。

    偏离清单见 docs/BIRD.md。
    """

    name = "bird-pro-t-direct"
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-v4-pro"
    key_env = "DEEPSEEK_API_KEY"
    request_params = {"extra_body": {"thinking": {"type": "enabled"}}}

    # 官方协议逐题发 evidence（榜单 Oracle Knowledge 列）。设 False 走官方的
    # 无知识分支，供将来做"屏蔽外部知识"的消融——那个数**不可**跟榜单并排。
    use_evidence = True

    def predict(self, sample: Sample, db_path: Path) -> str:
        prompt = official_prompt(sample, db_path, evidence=self.use_evidence)
        reply = self._endpoint.chat_messages([{"role": "user", "content": prompt}])
        return extract_sql(reply)
