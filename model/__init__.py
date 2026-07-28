"""阶段一·生成侧：模型接口与实现。

新增一个模型（本地的、API 的都一样）：
  1. 在 model/ 下写一个继承 SQLGenerator 的类（见 base.py；
     OpenAI 兼容的 API 模型继承 api.py 的 APIModel，只填几个类属性）
  2. 在下面的 MODELS 里加一行
  3. python -m model --model <name> --data en_dev --eval

项目收尾后，论文主线冻结为 Direct / Direct+FS / DSL / DSL+FS 四格。
其他注册项保留用于历史复现，但统一归入 EXPERIMENT_MODELS，不再与主线混排。
"""

from model.api import (DeepSeekFlash, DeepSeekFlashThinking, DeepSeekPro,
                       DeepSeekProThinking, DeepSeekProThinkingConv,
                       DeepSeekProThinkingFewShot, DeepSeekProThinkingSFS,
                       DeepSeekProThinkingValueEvidence,
                       DeepSeekProThinkingValueEvidenceRandom,
                       DeepSeekProThinkingValueEvidenceV2,
                       DeepSeekProThinkingValueEvidenceV2Random)
from model.base import SQLGenerator
from model.bird import (
    BirdDirect, BirdDirectFewShot, BirdDirectValueEvidence,
    BirdDirectValueEvidenceRandom, BirdProTDsl, BirdProTDslFewShot,
    BirdProTDslFewShot20240627, BirdProTDslValueEvidence,
    BirdProTDslValueEvidenceRandom,
)
from model.example import FirstTableBaseline
from model.pipeline.archive import (ProTPlanDslConv, ProTPlanDslConvCchk,
                                    ProTPlanDslProf, ProTPlanDslProfForce,
                                    ProTPlanDslProfForceChk)
from model.pipeline.models import (ProTDsl, ProTDslChk, ProTDslConv,
                                   ProTDslConvChk, ProTDslConvChkR0,
                                   ProTDslFewShot, ProTDslSFS,
                                   ProTDslValueEvidence,
                                   ProTDslValueEvidenceRandom,
                                   ProTDslKnowledge, ProTDslKnowledgeRules,
                                   ProTDslKnowledgeRulesSqlens,
                                   ProTPlan, ProTPlanDsl)

# 主线注册表：唯一保留的两个 idea 是 DSL 与 fixed semantic few-shot。
MAIN_MODELS: dict[str, type[SQLGenerator]] = {
    # 框架自检哑基线（无 LLM）。
    FirstTableBaseline.name: FirstTableBaseline,

    # Archer en_dev 四格。
    DeepSeekProThinking.name: DeepSeekProThinking,                  # Direct
    DeepSeekProThinkingFewShot.name: DeepSeekProThinkingFewShot,    # Direct + FS
    ProTDsl.name: ProTDsl,                                          # DSL
    ProTDslFewShot.name: ProTDslFewShot,                            # DSL + FS

    # BIRD dev_20251106 四格。
    BirdDirect.name: BirdDirect,
    BirdDirectFewShot.name: BirdDirectFewShot,
    BirdProTDsl.name: BirdProTDsl,
    BirdProTDslFewShot.name: BirdProTDslFewShot,
}


# 探索/负结果/旧版复现档位。保留旧名字和运行能力，但不属于最终方法。
EXPERIMENT_MODELS: dict[str, type[SQLGenerator]] = {
    # 骨干与早期 Direct 对照。
    DeepSeekFlash.name: DeepSeekFlash,
    DeepSeekFlashThinking.name: DeepSeekFlashThinking,
    DeepSeekPro.name: DeepSeekPro,

    # 结构感知检索与 Value Evidence。
    DeepSeekProThinkingSFS.name: DeepSeekProThinkingSFS,
    DeepSeekProThinkingValueEvidence.name: DeepSeekProThinkingValueEvidence,
    DeepSeekProThinkingValueEvidenceRandom.name: DeepSeekProThinkingValueEvidenceRandom,
    DeepSeekProThinkingValueEvidenceV2.name: DeepSeekProThinkingValueEvidenceV2,
    DeepSeekProThinkingValueEvidenceV2Random.name: DeepSeekProThinkingValueEvidenceV2Random,

    # Plan、旧约定/检查器与学习式知识消融。
    ProTPlan.name: ProTPlan,
    ProTPlanDsl.name: ProTPlanDsl,
    ProTDslSFS.name: ProTDslSFS,
    ProTDslValueEvidence.name: ProTDslValueEvidence,
    ProTDslValueEvidenceRandom.name: ProTDslValueEvidenceRandom,
    ProTDslConv.name: ProTDslConv,
    ProTDslConvChk.name: ProTDslConvChk,
    ProTDslChk.name: ProTDslChk,
    ProTDslConvChkR0.name: ProTDslConvChkR0,
    DeepSeekProThinkingConv.name: DeepSeekProThinkingConv,

    # BIRD 探索臂与旧版数据。
    BirdDirectValueEvidence.name: BirdDirectValueEvidence,
    BirdDirectValueEvidenceRandom.name: BirdDirectValueEvidenceRandom,
    BirdProTDslValueEvidence.name: BirdProTDslValueEvidence,
    BirdProTDslValueEvidenceRandom.name: BirdProTDslValueEvidenceRandom,
    BirdProTDslFewShot20240627.name: BirdProTDslFewShot20240627,

    # 带 plan 注知识的历史探索支。
    ProTPlanDslProf.name: ProTPlanDslProf,
    ProTPlanDslProfForce.name: ProTPlanDslProfForce,
    ProTPlanDslProfForceChk.name: ProTPlanDslProfForceChk,
    ProTPlanDslConv.name: ProTPlanDslConv,
    ProTPlanDslConvCchk.name: ProTPlanDslConvCchk,

    # 学习式知识/规则阶梯。
    ProTDslKnowledge.name: ProTDslKnowledge,
    ProTDslKnowledgeRules.name: ProTDslKnowledgeRules,
    ProTDslKnowledgeRulesSqlens.name: ProTDslKnowledgeRulesSqlens,
}


# 向后兼容：原有命令仍通过 MODELS 找到全部档位。
MODELS: dict[str, type[SQLGenerator]] = {
    **MAIN_MODELS,
    **EXPERIMENT_MODELS,
}

__all__ = [
    "SQLGenerator",
    "MAIN_MODELS",
    "EXPERIMENT_MODELS",
    "MODELS",
]
