"""判负存档的探索支：带 plan 前站注入知识的消融档位（画像轴 + 约定轴）。

这些档位在 en_dev 上判负或落在噪声区（结果与判读见 docs/ABLATION.md §4），
已被 no-plan 主线取代。保留注册是为了历史结果可一键复跑（归档≠删除），
不再投入新工作；新变体一律加在 models.py。
"""

from __future__ import annotations

from model.pipeline.models import ProTPlanDsl


class ProTPlanDslProf(ProTPlanDsl):
    """库画像进 prompt（planner 与 dslgen 两处都注入），不强制表态——只"给知识"。

    注入 planner 是必须的：plan 阶段先把锚定错，dslgen 只能补救；
    只注 dslgen 等于错已经犯完了才递材料。
    """

    name = "pro-t-plandsl-prof"
    use_profile = True


class ProTPlanDslProfForce(ProTPlanDslProf):
    """+ considered 强制表态（C5a）：把"没想到"变成"想过并否决了"，
    后者才可校验、可统计。
    """

    name = "pro-t-plandsl-prof-force"
    force_considered = True


class ProTPlanDslProfForceChk(ProTPlanDslProfForce):
    """+ C5b 锚一致性 + C6 比率线索（建议级检查，精度见各自 docstring/ABLATION.md）。"""

    name = "pro-t-plandsl-prof-force-chk"
    extra_checks = True


class ProTPlanDslConv(ProTPlanDsl):
    """prose 臂：train 蒸馏的约定表以 guidelines 文本注入 dslgen。

    与画像轴互斥不叠加——约定对齐的分数单独归因。
    """

    name = "pro-t-plandsl-conv"
    conventions = True


class ProTPlanDslConvCchk(ProTPlanDslConv):
    """强制臂：同一份约定 + C7 检查器在修复环里按违规触发——
    机器强制执行约定的净值与 prose 臂对照。
    """

    name = "pro-t-plandsl-conv-cchk"
    convention_checks = True
