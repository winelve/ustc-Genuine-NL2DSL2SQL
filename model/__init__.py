"""阶段一·生成侧：模型接口与实现。

新增一个模型（本地的、API 的都一样）：
  1. 在 model/ 下写一个继承 SQLGenerator 的类（见 base.py；
     OpenAI 兼容的 API 模型继承 api.py 的 APIModel，只填几个类属性）
  2. 在下面的 MODELS 里加一行
  3. python -m model --model <name> --data en_dev --eval

命名约定 `<骨干>[-t]-<配置>`（token 词表见 docs/ABLATION.md）：
  骨干 flash/pro；`-t` = 开 thinking；配置 = pipeline 组件栈
  direct → plan → plandsl → dsl（去 plan），可再追加 prof/force/conv/chk/cchk。
"""

from model.api import (DeepSeekFlash, DeepSeekFlashThinking, DeepSeekPro,
                       DeepSeekProThinking, DeepSeekProThinkingConv)
from model.base import SQLGenerator
from model.bird import BirdDirect
from model.example import FirstTableBaseline
from model.pipeline.archive import (ProTPlanDslConv, ProTPlanDslConvCchk,
                                    ProTPlanDslProf, ProTPlanDslProfForce,
                                    ProTPlanDslProfForceChk)
from model.pipeline.models import (ProTDsl, ProTDslChk, ProTDslConv,
                                   ProTDslConvChk, ProTDslConvChkR0,
                                   ProTPlan, ProTPlanDsl)

# 注册表：--model 参数用的名字 -> 模型类。含义见 docs/ABLATION.md。
MODELS: dict[str, type[SQLGenerator]] = {
    # 框架自检哑基线（无 LLM，每题取第一张表）
    FirstTableBaseline.name: FirstTableBaseline,

    # 直出基线：LLM 直接出 SQL、无 pipeline（骨干 × thinking 四格对照）
    DeepSeekFlash.name: DeepSeekFlash,                  # flash-direct
    DeepSeekFlashThinking.name: DeepSeekFlashThinking,  # flash-t-direct
    DeepSeekPro.name: DeepSeekPro,                      # pro-direct
    DeepSeekProThinking.name: DeepSeekProThinking,      # pro-t-direct

    # 主线加法阶梯：plan → plandsl → dsl(去plan) → +conv → +chk
    ProTPlan.name: ProTPlan,                # pro-t-plan
    ProTPlanDsl.name: ProTPlanDsl,          # pro-t-plandsl
    ProTDsl.name: ProTDsl,                  # pro-t-dsl
    ProTDslConv.name: ProTDslConv,          # pro-t-dsl-conv
    ProTDslConvChk.name: ProTDslConvChk,    # pro-t-dsl-conv-chk  ★满配·最终

    # 满配 leave-one-out 消融（对照 = pro-t-dsl-conv-chk，每臂只动一个变量）
    ProTDslChk.name: ProTDslChk,                        # pro-t-dsl-chk（−conv）
    ProTDslConvChkR0.name: ProTDslConvChkR0,            # pro-t-dsl-conv-chk-r0（−重试）
    DeepSeekProThinkingConv.name: DeepSeekProThinkingConv,  # pro-t-direct-conv（−声明层）

    # BIRD 跑分档位：官方 baseline 口径的单次调用直出（见 model/bird.py）
    BirdDirect.name: BirdDirect,            # bird-pro-t-direct

    # 存档：带 plan 注知识的探索支（已被 no-plan 线取代，多数判负，保留以可复现）
    ProTPlanDslProf.name: ProTPlanDslProf,                  # pro-t-plandsl-prof
    ProTPlanDslProfForce.name: ProTPlanDslProfForce,        # pro-t-plandsl-prof-force
    ProTPlanDslProfForceChk.name: ProTPlanDslProfForceChk,  # pro-t-plandsl-prof-force-chk
    ProTPlanDslConv.name: ProTPlanDslConv,                  # pro-t-plandsl-conv
    ProTPlanDslConvCchk.name: ProTPlanDslConvCchk,          # pro-t-plandsl-conv-cchk
}

__all__ = ["SQLGenerator", "MODELS"]
