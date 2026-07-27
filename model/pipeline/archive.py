"""判负存档的探索支：带 plan 前站注入知识的消融档位（画像轴 + 约定轴）。

这些档位在 en_dev 上判负或落在噪声区（结果与判读见 docs/ABLATION.md §4），
已被 no-plan 主线取代。保留注册是为了历史结果可一键复跑（归档≠删除），
不再投入新工作；新变体一律加在 models.py。

`_ArchivedDeclareStage` 是旧开关（use_profile/force_considered/extra_checks/
conventions/convention_checks）的适配层：`DeclareStage` 换代后只剩四个新
开关，这些旧开关靠这个子类继续跑 C5a/C5b/C6/C7 与 conventions 附录——
只覆写 `DeclareStage` 的三个窄小钩子（`_system_extra`/`_profile_items`/
`_extra_issues`），`run()` 全程复用基类那一份，不整段复制。

`models.py` 里的 `ProTDslConv`/`ProTDslConvChk`/`ProTDslConvChkR0`（主线
leave-one-out 臂，不是判负存档）也用 `conventions` 开关，同样靠这个适配层——
它们在各自的 `_stages()` 里用局部 import 拿 `_ArchivedDeclareStage`，避免
`models.py`/`archive.py` 之间的模块级循环 import。
"""

from __future__ import annotations

import sqlglot

from model.pipeline.context import PipelineContext
from model.pipeline.dsl import profile_ids_for
from model.pipeline.dsl.archived_checks import validate_archived
from model.pipeline.models import ProTPlanDsl
from model.pipeline.profile import build_profile
from model.pipeline.stages.declare import DeclareStage
from model.pipeline.stages.plan import PlanStage
from model.pipeline.stages.vote import VoteStage
from model.pipeline.templates import render


class _ArchivedDeclareStage(DeclareStage):
    """旧开关的适配层：归档档位靠它继续跑 C5a/C5b/C6/C7 与 conventions 附录。"""

    def __init__(self, endpoint, max_repairs: int = 2, *,
                 use_profile: bool = False, force_considered: bool = False,
                 extra_checks: bool = False, conventions: bool = False,
                 convention_checks: bool = False, knowledge: bool = False,
                 evidence: bool = False, dataset: str = "en_train",
                 use_plan: bool = True) -> None:
        super().__init__(endpoint, max_repairs, dataset=dataset,
                         knowledge=knowledge, evidence=evidence,
                         use_plan=use_plan)
        self.use_profile = use_profile
        self.force_considered = force_considered
        self.extra_checks = extra_checks
        self.conventions = conventions
        self.convention_checks = convention_checks
        self._profile_ids: set[str] = set()   # _profile_items() 按 force_considered 填

    def _system_extra(self) -> str:
        """约定 prose 附录，插在基线与知识附录之间——与本任务改造前的顺序一致。"""
        if not self.conventions:
            return ""
        from model.pipeline.conventions import conventions_block
        return render("dslgen.conventions", conventions=conventions_block())

    def _profile_items(self, ctx: PipelineContext) -> list[str]:
        items = build_profile(ctx.db_path) if self.use_profile else []
        self._profile_ids = profile_ids_for(items) if self.force_considered else set()
        return items

    def _extra_issues(self, out, ctx: PipelineContext, schema_info) -> list[str]:
        """C5a（恒跑，profile_ids 为空时自己短路）+ 按开关加的 C5b/C6/C7。"""
        tree = sqlglot.parse_one(out.sql, dialect="sqlite")
        return validate_archived(out, tree, ctx.db_path, question=ctx.question,
                                 profile_ids=self._profile_ids,
                                 extra_checks=self.extra_checks,
                                 convention_checks=self.convention_checks)


class _ArchivedDsl(ProTPlanDsl):
    """归档档位共用的阶段编排：与 `ProTPlanDsl`/`DSLSQL` 唯一差异是
    `DeclareStage` 换成 `_ArchivedDeclareStage`，把旧开关接回去。不注册，
    只当基类用——注册的类见下面几个。"""

    def _stages(self) -> list:
        # 全部七个旧/新开关都转发（同 ProTDsl._stages() 的归档分支）——类属性
        # 是唯一事实源，这里只管转发不管筛选，避免某个开关在这条分支上静默
        # 失效。这一族档位当前都不设 knowledge/evidence/dataset，但转发全部
        # 参数比"只转发用得上的那几个"更不容易在将来出现新组合臂时踩坑。
        return [
            PlanStage(self.endpoint, self.n_plans, self.plan_temperature,
                      use_profile=self.use_profile),
            _ArchivedDeclareStage(self.endpoint, self.max_repairs,
                                 dataset=self.dataset,
                                 knowledge=self.knowledge,
                                 evidence=self.evidence,
                                 use_profile=self.use_profile,
                                 force_considered=self.force_considered,
                                 extra_checks=self.extra_checks,
                                 conventions=self.conventions,
                                 convention_checks=self.convention_checks,
                                 use_plan=self.use_plan),
            VoteStage(),
        ]


class ProTPlanDslProf(_ArchivedDsl):
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


class ProTPlanDslConv(_ArchivedDsl):
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
