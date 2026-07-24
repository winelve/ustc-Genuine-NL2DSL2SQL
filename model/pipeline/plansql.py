"""PlanSQL：先规划后写 SQL 的 SQLGenerator 实现。

pipeline = [PlanStage, GenerateStage, VoteStage]，每条样本流经一遍；
DSL 结构化/校验阶段可插在 Plan 与 Generate 之间（改 _stages 即可）。

参数随模型走（铁律 #2）：骨干 endpoint、n_plans、plan_temperature 都是类属性，
新变体 = 子类 + MODELS 注册一行。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from archer_eval.data import Sample
from archer_eval.progress import Progress
from config import API_CONCURRENCY
from model.base import SQLGenerator
from model.llm import ChatEndpoint
from model.pipeline.context import PipelineContext
from model.pipeline.stages.declare import DeclareStage
from model.pipeline.stages.generate import GenerateStage
from model.pipeline.stages.plan import PlanStage
from model.pipeline.stages.vote import VoteStage
from model.prompts import schema_with_rows


class PlanSQL(SQLGenerator):
    endpoint_spec: dict          # ChatEndpoint 的构造参数，planner/sqlgen 共用一个骨干
    n_plans = 1                  # >1 时 planner 升温出多样 plan + 执行结果投票
    plan_temperature = 0.7
    concurrency = API_CONCURRENCY
    use_profile = False          # 库画像开关；关闭时 planner 消息与不带画像时逐字节相同

    def __init__(self) -> None:
        self.endpoint = ChatEndpoint(**self.endpoint_spec)
        self.trace_records: list[dict] = []   # predict_all 后与预测同序的调试记录

    def _stages(self) -> list:
        # 每次调用现取参数，实例上改 n_plans 立即生效
        return [
            PlanStage(self.endpoint, self.n_plans, self.plan_temperature,
                      use_profile=self.use_profile),
            GenerateStage(self.endpoint),
            VoteStage(),
        ]

    def _run(self, sample: Sample, db_path: Path) -> PipelineContext:
        ctx = PipelineContext(question=sample.question, db_path=Path(db_path))
        ctx.schema = schema_with_rows(db_path)   # [0] 上下文准备：全量 schema+样本行
        for stage in self._stages():
            stage.run(ctx)
        return ctx

    def predict(self, sample: Sample, db_path: Path) -> str:
        return self._run(sample, db_path).final_sql

    def predict_all(
        self, samples: list[Sample], db_paths: list[Path], progress: bool = True
    ) -> list[str]:
        """并发跑全 pipeline；同时收集与预测同序的 trace_records。"""

        def one(indexed: tuple[int, tuple[Sample, Path]]) -> tuple[str, dict, str | None]:
            i, (sample, db_path) = indexed
            try:
                ctx = self._run(sample, db_path)
                return ctx.final_sql, ctx.to_trace(), None
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                return "", {"question": sample.question, "error": error}, \
                    f"  sample {i} failed: {error}"

        bar = Progress(len(samples), "generate", enabled=progress)
        preds, traces = [], []
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            for sql, trace, error in pool.map(one, enumerate(zip(samples, db_paths))):
                if error:
                    bar.write(error)
                preds.append(sql)
                traces.append(trace)
                bar.step()
        self.trace_records = traces
        return preds


class ProTPlan(PlanSQL):
    name = "pro-t-plan"
    endpoint_spec = dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        key_env="DEEPSEEK_API_KEY",
        # 开思考换推理质量；代价是 DeepSeek 思考模式静默忽略采样参数——
        # 各 stage 传的 temperature 不生效，n_plans>1 的多样性会失效（见 PROGRESS 决策记录）
        request_params={"extra_body": {"thinking": {"type": "enabled"}}},
    )


class DSLSQL(PlanSQL):
    """半程 IR：sqlgen 换成 DeclareStage（SQL + 声明表 + 校验修复循环）。

    planner 与投票逻辑与不带 DSL 的 plan pipeline 完全一致，声明层是唯一变量。
    """

    max_repairs = 2
    # 消融开关，默认全部关闭 = 对照点。
    # use_profile 继承自 PlanSQL，打开时 planner 与 dslgen 两处都注入。
    force_considered = False
    extra_checks = False
    conventions = False          # 约定附录进 dslgen system（prose 臂）
    convention_checks = False    # C7 约定检查器（强制执行臂）

    def _stages(self) -> list:
        return [
            PlanStage(self.endpoint, self.n_plans, self.plan_temperature,
                      use_profile=self.use_profile),
            DeclareStage(self.endpoint, self.max_repairs,
                         use_profile=self.use_profile,
                         force_considered=self.force_considered,
                         extra_checks=self.extra_checks,
                         conventions=self.conventions,
                         convention_checks=self.convention_checks),
            VoteStage(),
        ]


class ProTPlanDsl(DSLSQL):
    name = "pro-t-plandsl"
    endpoint_spec = dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        key_env="DEEPSEEK_API_KEY",
        # 主线骨干 = pro + thinking，与对照组同底；
        # 注意 DeepSeek 思考模式静默忽略 temperature
        request_params={"extra_body": {"thinking": {"type": "enabled"}}},
    )


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


class ProTDsl(ProTPlanDsl):
    """去掉 PlanStage，question+schema 直达 dslgen。

    验证 planner 对 thinking 骨干是否是死重效应，并排除"plan 在无知识状态下
    先定死决定"这个混杂因素——对比时只留声明层，不留自由文本 plan 层。
    """

    name = "pro-t-dsl"

    def _stages(self) -> list:
        return [
            DeclareStage(self.endpoint, self.max_repairs,
                         use_profile=self.use_profile,
                         force_considered=self.force_considered,
                         extra_checks=self.extra_checks,
                         conventions=self.conventions,
                         convention_checks=self.convention_checks,
                         use_plan=False),
            VoteStage(),
        ]


class ProTDslConv(ProTDsl):
    """no-plan + 约定 prose：知识与问题同一条消息抵达唯一的决策点。

    与 no-plan 基线的分差 = 排除 plan 前站后，prose 约定单独的净值。
    """

    name = "pro-t-dsl-conv"
    conventions = True


class ProTDslConvChk(ProTDslConv):
    """pro-t-dsl-conv + C5b/C6 建议级检查（extra_checks）；C7 刻意不开
    （精度见 docs/ABLATION.md）。相对 pro-t-dsl-conv 单变量 = extra_checks。
    """

    name = "pro-t-dsl-conv-chk"
    extra_checks = True
