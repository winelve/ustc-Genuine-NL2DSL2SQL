"""阶段一·生成侧：模型接口与实现。

新增一个模型（本地的、API 的都一样）：
  1. 在 model/ 下写一个继承 SQLGenerator 的类（见 base.py；
     OpenAI 兼容的 API 模型继承 api.py 的 APIModel，只填几个类属性）
  2. 在下面的 MODELS 里加一行
  3. python -m model --model <name> --data en_dev --eval
"""

from model.api import DeepSeekFlash, DeepSeekFlashThinking, DeepSeekPro, DeepSeekProThinking
from model.base import SQLGenerator
from model.example import FirstTableBaseline
from model.pipeline.plansql import DSLSQLPro, M3A, M3B, M3C, PlanSQLPro
from model.pipeline.plansql import (M3DC, M3DP, M3DPNoPlan, M3DXNoPlan,
                                    NoPlanDSLSQL)

# 注册表：--model 参数用的名字 -> 模型类
MODELS: dict[str, type[SQLGenerator]] = {
    FirstTableBaseline.name: FirstTableBaseline,
    DeepSeekFlash.name: DeepSeekFlash,
    DeepSeekFlashThinking.name: DeepSeekFlashThinking,
    DeepSeekPro.name: DeepSeekPro,
    DeepSeekProThinking.name: DeepSeekProThinking,
    PlanSQLPro.name: PlanSQLPro,
    DSLSQLPro.name: DSLSQLPro,
    M3A.name: M3A,
    M3B.name: M3B,
    M3C.name: M3C,
    M3DP.name: M3DP,
    M3DC.name: M3DC,
    NoPlanDSLSQL.name: NoPlanDSLSQL,
    M3DPNoPlan.name: M3DPNoPlan,
    M3DXNoPlan.name: M3DXNoPlan,
}

__all__ = ["SQLGenerator", "MODELS"]
