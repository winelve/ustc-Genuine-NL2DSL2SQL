"""阶段一·生成侧：模型接口与实现。

新增一个模型的三步：
  1. 在 model/ 下新建文件，写一个继承 SQLGenerator 的类（见 base.py 的契约）
  2. 在下面的 MODELS 注册表里加一行
  3. 运行 python -m model --model <name> --data en_dev --eval
"""

from model.base import SQLGenerator
from model.example import FirstTableBaseline
from model.prompts import build_ct3_prompt, schema_with_rows

# 注册表：--model 参数用的名字 -> 模型类
MODELS: dict[str, type[SQLGenerator]] = {
    FirstTableBaseline.name: FirstTableBaseline,
}

__all__ = ["SQLGenerator", "MODELS", "build_ct3_prompt", "schema_with_rows"]
