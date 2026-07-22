"""PlanStage：question + schema → n 个自然语言 plan。"""

from __future__ import annotations

from model.llm import ChatEndpoint
from model.pipeline.context import PipelineContext
from model.pipeline.templates import load_template, render


class PlanStage:
    def __init__(self, endpoint: ChatEndpoint, n_plans: int, plan_temperature: float) -> None:
        self.endpoint = endpoint
        self.n_plans = n_plans
        self.plan_temperature = plan_temperature

    def run(self, ctx: PipelineContext) -> None:
        # 单 plan 求可复现用贪心；多 plan 靠温度出多样性（每个 plan 独立一次调用）
        temperature = 0.0 if self.n_plans == 1 else self.plan_temperature
        system = load_template("planner.system")
        user = render("planner.user", schema=ctx.schema, question=ctx.question)
        for _ in range(self.n_plans):
            ctx.plans.append(self.endpoint.chat(system, user, temperature=temperature).strip())
