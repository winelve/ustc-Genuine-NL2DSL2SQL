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
from model.pipeline.models import ProTDsl
from model.value_evidence.render import render_value_schema


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
        value_record = self._value_evidence_record(sample)
        schema = (
            render_value_schema(
                db_path, value_record, mode=self.value_evidence_mode
            )
            if value_record is not None
            else None
        )
        prompt = official_prompt(
            sample,
            db_path,
            evidence=self.use_evidence,
            schema=schema,
        )
        examples = self._fewshot_examples(sample)
        if examples:
            prompt = f"{examples}\n\n{prompt}"
        reply = self._endpoint.chat_messages([{"role": "user", "content": prompt}])
        return extract_sql(reply)


class BirdDirectFewShot(BirdDirect):
    name = "bird-pro-t-direct-fs"
    fewshot_selection = "bird_dev_rsl_k3"


class BirdDirectValueEvidence(BirdDirect):
    name = "bird-pro-t-direct-ve"
    value_evidence_selection = "bird_dev_chess_ir"
    value_evidence_mode = "relevant"


class BirdDirectValueEvidenceRandom(BirdDirectValueEvidence):
    name = "bird-pro-t-direct-ve-r"
    value_evidence_mode = "random"


class BirdProTDsl(ProTDsl):
    """Archer 主线的声明层档位搬到 BIRD——测 pipeline 的跨数据集泛化。

    与 en_dev 上那个 52.88 的 `pro-t-dsl` **逐位相同**：no-plan、声明层 +
    C1-C4 恒开检查 + 2 轮修复环，knowledge / learned_rules / sqlens_checks /
    conventions / extra_checks 全关。唯一差异是 `evidence=True`。

    `evidence` 为什么开：BIRD 官方协议逐题发 evidence（榜单 Oracle Knowledge
    列全 ✔️），`BirdDirect` 也是 `use_evidence=True`。关掉这个数就既不能跟
    57.37 比、也不能跟榜单比。Archer 侧相反（官方设定 w/o knowledge），所以
    这个开关只在 BIRD 档位上打开，主线 `ProTDsl` 保持 False。

    对照点 = `bird-pro-t-direct` 官方 EX **57.37**（880/1534）。两臂的差值含
    两个变量：声明层，以及 schema 表示（官方 baseline 是纯 DDL，这里是 DDL +
    每表 3 行样本）——样本行是本项目 pipeline 的固有组成，报数时说明即可。

    跑法（`--eval` 不能加，那是 archer_eval 的 VA/EX/SIM，与榜单不可比）：

        python -m model --model bird-pro-t-dsl --data bird_dev
        python -m bird eval --pred predictions/bird-pro-t-dsl_bird_dev.json --official
    """

    name = "bird-pro-t-dsl"
    evidence = True
    # knowledge / learned_rules 都关着，所以这个值现在是空转的；设成 bird_dev
    # 是为了将来真开知识层时不会静默去读 data/knowledge/en.json（Archer 的）。
    dataset = "bird_dev"


class BirdProTDslFewShot(BirdProTDsl):
    """BIRD no-plan DSL + 固定三条训练集 SQL 语义参考。"""

    name = "bird-pro-t-dsl-fs"
    fewshot_selection = "bird_dev_rsl_k3"


class BirdProTDslValueEvidence(BirdProTDsl):
    name = "bird-pro-t-dsl-ve"
    value_evidence_selection = "bird_dev_chess_ir"
    value_evidence_mode = "relevant"


class BirdProTDslValueEvidenceRandom(BirdProTDslValueEvidence):
    name = "bird-pro-t-dsl-ve-r"
    value_evidence_mode = "random"


class BirdProTDslFewShot20240627(BirdProTDslFewShot):
    """BIRD 2024-06-27 dev + 对应版本的固定 top-3。"""

    name = "bird-pro-t-dsl-fs-20240627"
    fewshot_selection = "bird_dev_20240627_rsl_k3"
    dataset = "bird_dev_20240627"
