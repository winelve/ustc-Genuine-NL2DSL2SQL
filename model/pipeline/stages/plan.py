"""PlanStage：question + schema → n 个自然语言 plan。"""

from __future__ import annotations

from model.llm import ChatEndpoint
from model.pipeline.context import PipelineContext
from model.pipeline.dsl import render_profile_block
from model.pipeline.profile import build_profile
from model.pipeline.templates import load_template, render


class PlanStage:
    def __init__(self, endpoint: ChatEndpoint, n_plans: int, plan_temperature: float,
                 *, use_profile: bool = False) -> None:
        self.endpoint = endpoint
        self.n_plans = n_plans
        self.plan_temperature = plan_temperature
        # 知识必须在犯错之前到达：dev 62% 的错断在 plan 阶段。
        # 默认关 —— 关闭时渲染出的消息与 M1 逐字节相同（见 render_profile_block）。
        self.use_profile = use_profile

    def run(self, ctx: PipelineContext) -> None:
        # 单 plan 求可复现用贪心；多 plan 靠温度出多样性（每个 plan 独立一次调用）
        temperature = 0.0 if self.n_plans == 1 else self.plan_temperature
        system = load_template("planner.system")
        items = build_profile(ctx.db_path) if self.use_profile else []
        user = render("planner.user", schema=ctx.schema, question=ctx.question,
                      profile=render_profile_block(items))
        for _ in range(self.n_plans):
            ctx.plans.append(self.endpoint.chat(system, user, temperature=temperature).strip())
