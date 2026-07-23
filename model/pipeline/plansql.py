"""PlanSQL：先规划后写 SQL 的 SQLGenerator 实现。

pipeline = [PlanStage, GenerateStage, VoteStage]，每条样本流经一遍；
M2 的 DSL 结构化 / 校验阶段将插在 Plan 与 Generate 之间（改 _stages 即可）。

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
    use_profile = False          # M3 库画像；关闭时 planner 消息与 M1 逐字节相同

    def __init__(self) -> None:
        self.endpoint = ChatEndpoint(**self.endpoint_spec)
        self.trace_records: list[dict] = []   # predict_all 后与预测同序的调试记录

    def _stages(self) -> list:
        # 每次调用现取参数，实例上改 n_plans 立即生效；M2 的新阶段插在这里
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


class PlanSQLPro(PlanSQL):
    name = "plansql-pro"
    endpoint_spec = dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        key_env="DEEPSEEK_API_KEY",
        # 开思考换推理质量；代价是 DeepSeek 思考模式静默忽略采样参数——
        # 各 stage 传的 temperature 不生效，n_plans>1 的多样性会失效（见 PROGRESS 决策记录）
        request_params={"extra_body": {"thinking": {"type": "enabled"}}},
    )


class DSLSQL(PlanSQL):
    """M2 半程 IR：sqlgen 换成 DeclareStage（SQL + 声明表 + 校验修复循环）。

    planner 与投票与 M1 完全一致——M2 − M1 的唯一变量就是声明层。
    """

    max_repairs = 2
    # M3 消融开关。基线全 False = M3 系的对照点。
    # ⚠️ dslgen 提示词在 M3 开发中改过版（anchors 枚举化、considered 段、
    # user 模板多出 Facts 标题行），与跑出 en_dev 44.2 的 M2 版本**不同**——
    # 做 M3 消融前必须用当前提示词重跑本基线，不能拿 44.2 直接比。
    # use_profile 继承自 PlanSQL，打开时 planner 与 dslgen **两处都注入**。
    force_considered = False
    extra_checks = False
    conventions = False          # M3-d：约定附录进 dslgen system（prose 臂）
    convention_checks = False    # M3-d：C7 约定检查器（强制执行臂）

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


class DSLSQLPro(DSLSQL):
    name = "dslsql-pro-thinking"
    endpoint_spec = dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        key_env="DEEPSEEK_API_KEY",
        # M2 主线骨干 = pro + thinking（M1 收官矩阵结论），与 M1 对照同底；
        # 注意 DeepSeek 思考模式静默忽略 temperature（见 PROGRESS 决策记录）
        request_params={"extra_body": {"thinking": {"type": "enabled"}}},
    )


class M3A(DSLSQLPro):
    """M3-a：库画像进 prompt（**planner 与 dslgen 两处都注入**），不强制表态。

    只"给知识"。与 M3-b 的分差就是本项目最有论文价值的那个数：
    给知识 vs 强制用知识。

    注 planner 是必须的：dev 62% 的错断在 plan 阶段，planner 先把锚猜错，
    dslgen 只能补救。只注 dslgen 等于错已经犯完了才递材料。
    """

    name = "m3a-pro-thinking"
    use_profile = True


class M3B(M3A):
    """M3-b：+ considered 强制表态（C5a）。

    触发机制：把"没想到"变成"想过并否决了"，而后者可校验、可统计。
    依据 dev #24/#26 那组天然对照——模型知道 attendance rate = 出勤/容量，
    只是没把 Capacity 拉进视野。
    """

    name = "m3b-pro-thinking"
    force_considered = True


class M3C(M3B):
    """M3-c：+ C5b 锚一致性 + C6 比率线索。

    这两个是建议级检查，实测精度 55%–67%（见各自 docstring）。
    它们到底是净收益还是净损失，由 M3-c − M3-b 的分差回答，不预设。
    """

    name = "m3c-pro-thinking"
    extra_checks = True


class M3DP(DSLSQLPro):
    """M3-d prose 臂：train 蒸馏的约定表以 guidelines 文本注入 dslgen。

    对照系即 OraPlan 的做法（其消融：guidelines 值 +27.9）。
    与画像轴（m3a/b/c）互斥不叠加——约定对齐的分数单独归因。
    """

    name = "m3dp-pro-thinking"
    conventions = True


class M3DC(M3DP):
    """M3-d 强制臂：同一份约定 + C7 检查器在修复环里按违规触发。

    m3dc − m3dp = "机器强制执行约定"的净值——路线 A 的中心论据
    （dev #40 的 C6 轨迹已证明决策点挑战能顶动模型，此处推广到约定族）。
    """

    name = "m3dc-pro-thinking"
    convention_checks = True


class NoPlanDSLSQL(DSLSQLPro):
    """no-plan 消融基线：去掉 PlanStage，question+schema 直达 dslgen。

    一次运行回答两个悬案：① planner 对 thinking 骨干是否死重（M1 实测 ±0
    的延伸——那时下游是 sqlgen，这次是声明层）；② 与 M3DPNoPlan 对比时，
    排除"plan 在无知识状态下先定死决定"的混杂（m3a、m3d 两次撞到的同一堵墙，
    m3dp 实测 ±0.00 且 #98 的分摊策略正是 plan 阶段定下的）。
    对照点：本臂 − 基线 45.19 = 纯去 planner 的效应。
    """

    name = "noplan-pro-thinking"

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


class M3DPNoPlan(NoPlanDSLSQL):
    """no-plan + 约定 prose：知识与问题同一条消息抵达唯一的决策点。

    本臂 − noplan 基线 = 排除 plan 前站后 prose 约定的净值；
    若仍 ≈0，"约定 prose 无效"才真正定案（m3dp 的 ±0.00 有 plan 混杂）。
    实测（2026-07-23）：45.19 → 52.88（去 plan）→ 57.69（+约定），
    合计 McNemar p≈0.019，靶子指纹见 PROGRESS。
    """

    name = "m3dp-noplan-pro-thinking"
    conventions = True


class M3DXNoPlan(M3DPNoPlan):
    """m3dp-noplan + C5b/C6 建议级检查（extra_checks）。

    动机：C6 的 dev 离线实测 4 触发 4 有用 0 有害，靶子 #24/#25/#40/#41
    在 57.69 的错题单里全数仍错；C5b 加 %闸门后 dev 2/2/0。
    C7 刻意不开：C7-abs dev 实测 0 有用 / 2 有害（#84/#86 现在是对的），
    开了是负期望。相对 m3dp-noplan 单变量 = extra_checks。
    """

    name = "m3dx-noplan-pro-thinking"
    extra_checks = True
