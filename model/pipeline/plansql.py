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
from model.pipeline.stages.generate import GenerateStage
from model.pipeline.stages.plan import PlanStage
from model.pipeline.stages.vote import VoteStage
from model.prompts import schema_with_rows


class PlanSQL(SQLGenerator):
    endpoint_spec: dict          # ChatEndpoint 的构造参数，planner/sqlgen 共用一个骨干
    n_plans = 1                  # >1 时 planner 升温出多样 plan + 执行结果投票
    plan_temperature = 0.7
    concurrency = API_CONCURRENCY

    def __init__(self) -> None:
        self.endpoint = ChatEndpoint(**self.endpoint_spec)
        self.trace_records: list[dict] = []   # predict_all 后与预测同序的调试记录

    def _stages(self) -> list:
        # 每次调用现取参数，实例上改 n_plans 立即生效；M2 的新阶段插在这里
        return [
            PlanStage(self.endpoint, self.n_plans, self.plan_temperature),
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
