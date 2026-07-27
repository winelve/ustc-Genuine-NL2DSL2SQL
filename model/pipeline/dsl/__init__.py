"""DSL 声明层：模型输出的 {sql, declarations} 结构与分层校验。

半程 IR（设计见 docs/design/2026-07-22-M2-dslsql.md）：SQL 仍由模型直出，
声明表逼它把关键决定摊在桌面上；本包只做机器校验，零 LLM 调用。

分层（设计见 docs/superpowers/specs/2026-07-27-learned-checks-design.md）：
  schema.py         —— 声明表结构与解析
  checks.py         —— L1 通用检查（跨数据集）
  rules.py          —— L2 学习规则（数据集专属，离线蒸馏）
  archived_checks.py —— 判负/被替代的检查（C5a/C5b/C6/C7）

边界：archived_checks 的内容**不从包级转出**——只被 archive.py 与
scripts/measure_checks.py 直接 `from model.pipeline.dsl.archived_checks import
...`。主线代码不该、也不能通过 `model.pipeline.dsl` 碰到它们；不要把这段
import 加回来。
"""

from model.pipeline.dsl.checks import *          # noqa: F401,F403
from model.pipeline.dsl.checks import (  # noqa: F401
    _c1_alignment, _c2_consistency, _c3_grounding, _c3_literal_neighbors,
    _c4_anchors,
    profile_ids_for, render_profile, render_profile_block, validate,
)
from model.pipeline.dsl.schema import *          # noqa: F401,F403
from model.pipeline.dsl.schema import (  # noqa: F401
    _eq_column_literal_pairs, _expr_columns, _is_star,
    Anchor, AnchorMap, Assumption, BlankableDict, BlankableText, Considered,
    Declarations, DslOutput, OutputDecl, SchemaInfo, TimeContext,
    load_schema_info, parse_output,
)
