"""GenerateStage：每个 plan → 一条候选 SQL（贪心解码）。"""

from __future__ import annotations

from model.api import extract_sql
from model.llm import ChatEndpoint
from model.pipeline.context import Candidate, PipelineContext
from model.pipeline.templates import load_template, render


class GenerateStage:
    def __init__(self, endpoint: ChatEndpoint) -> None:
        self.endpoint = endpoint

    def run(self, ctx: PipelineContext) -> None:
        system = load_template("sqlgen.system")
        for plan in ctx.plans:
            user = render("sqlgen.user", schema=ctx.schema, question=ctx.question, plan=plan)
            sql = extract_sql(self.endpoint.chat(system, user, temperature=0.0))
            ctx.candidates.append(Candidate(plan=plan, sql=sql))
