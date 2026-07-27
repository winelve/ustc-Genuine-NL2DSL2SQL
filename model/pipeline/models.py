"""pipeline 主线模型：编排基类 + 主线消融阶梯的注册类。

pipeline = 若干 stage 顺序流过（PlanStage / GenerateStage / DeclareStage /
VoteStage 的组合），每条样本流经一遍；组合由各类的 _stages() 决定。

参数随模型走（铁律 #2）：骨干 endpoint、消融开关都是类属性，
新变体 = 子类 + MODELS 注册一行。命名 `<骨干>[-t]-<配置>` 见 docs/ABLATION.md。
判负存档的探索支（画像轴、带 plan 注知识）在 archive.py，不在这里。
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
    # 唯一事实源：no-plan 档位（ProTDsl 系）覆写为 False。--list 与 _stages()
    # 都读这个类属性，不靠实例化判断（实例化会撞真实 ChatEndpoint 构造）。
    use_plan = True

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
        ctx.evidence = sample.commonsense_knowledge or ""
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
    # 决定读哪份知识/规则文件（data/knowledge、data/rules 下按前缀取）。
    # 只由类属性决定——model/__main__.py 的 runner 不按 --data 覆盖它：
    # 知识/规则文件用哪份是档位自己的声明，不该被命令行悄悄改掉；换数据集
    # 要跑哪份知识/规则，靠注册一个把 dataset 设成对应值的档位类。
    dataset = "en_train"
    # 四个学习式消融开关（DeclareStage 认得的新开关），默认全关 = 对照点。
    knowledge = False
    evidence = False              # Archer 官方设定 w/o knowledge，只为 BIRD 预留
    learned_rules = False
    sqlens_checks = False
    # 旧开关（C5a-C7/画像/约定）：DeclareStage 已经不接受它们了，_stages() 也不再
    # 传给它；类属性留着只是为了给归档档位（archive.py 的探索支、下面的
    # ProTDslConv 系 LOO 臂）当继承默认值——它们的 _stages() 走
    # archive._ArchivedDeclareStage，相邻档位"只加一个 True"的单变量写法要靠
    # 这份默认值成立。
    use_profile = False           # 继承自 PlanSQL，这里重复声明只为醒目
    force_considered = False
    extra_checks = False
    conventions = False           # 约定附录进 dslgen system（prose 臂）
    convention_checks = False     # C7 约定检查器（强制执行臂）

    def _stages(self) -> list:
        return [
            PlanStage(self.endpoint, self.n_plans, self.plan_temperature,
                      use_profile=self.use_profile),
            DeclareStage(self.endpoint, self.max_repairs,
                         dataset=self.dataset,
                         knowledge=self.knowledge,
                         evidence=self.evidence,
                         learned_rules=self.learned_rules,
                         sqlens_checks=self.sqlens_checks,
                         use_plan=self.use_plan),
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


class ProTDsl(ProTPlanDsl):
    """去掉 PlanStage，question+schema 直达 dslgen。

    验证 planner 对 thinking 骨干是否是死重效应，并排除"plan 在无知识状态下
    先定死决定"这个混杂因素——对比时只留声明层，不留自由文本 plan 层。
    """

    name = "pro-t-dsl"
    use_plan = False   # 唯一事实源：--list 与 _stages() 都读它，见 PlanSQL.use_plan

    def _stages(self) -> list:
        # 老三样（conventions/extra_checks/convention_checks）任一打开，就说明
        # 这一档还在用旧开关（pro-t-dsl-conv 系 LOO 臂）——走 archive.py 的
        # _ArchivedDeclareStage 适配层；否则走新四开关的主线 DeclareStage。
        # 局部 import 避免 models.py/archive.py 模块级循环 import
        # （archive.py 反过来要 import ProTPlanDsl）。单一 _stages()，
        # ProTDslConv/ProTDslConvChk/ProTDslConvChkR0/ProTDslChk 都靠它分流，
        # 不必各自重复覆写。
        if self.conventions or self.extra_checks or self.convention_checks:
            from model.pipeline.archive import _ArchivedDeclareStage
            # 全部七个旧/新开关都转发——类属性是唯一事实源，_stages() 只管
            # "转发"不管"筛选"；漏转发等于让某个开关在这条分支上静默失效
            # （例如将来出现 conventions=True + knowledge=True 的组合臂）。
            declare = _ArchivedDeclareStage(
                self.endpoint, self.max_repairs,
                dataset=self.dataset,
                knowledge=self.knowledge,
                evidence=self.evidence,
                use_profile=self.use_profile,
                force_considered=self.force_considered,
                extra_checks=self.extra_checks,
                conventions=self.conventions,
                convention_checks=self.convention_checks,
                use_plan=self.use_plan)
        else:
            declare = DeclareStage(
                self.endpoint, self.max_repairs,
                dataset=self.dataset,
                knowledge=self.knowledge,
                evidence=self.evidence,
                learned_rules=self.learned_rules,
                sqlens_checks=self.sqlens_checks,
                use_plan=self.use_plan)
        return [declare, VoteStage()]


class ProTDslConv(ProTDsl):
    """no-plan + 约定 prose：知识与问题同一条消息抵达唯一的决策点。

    与 no-plan 基线的分差 = 排除 plan 前站后，prose 约定单独的净值。
    仍用旧开关 conventions，`_stages()` 继承自 `ProTDsl`（见上）。
    """

    name = "pro-t-dsl-conv"
    conventions = True


class ProTDslConvChk(ProTDslConv):
    """pro-t-dsl-conv + C5b/C6 建议级检查（extra_checks）；C7 刻意不开
    （精度见 docs/ABLATION.md）。相对 pro-t-dsl-conv 单变量 = extra_checks。
    """

    name = "pro-t-dsl-conv-chk"
    extra_checks = True


# ---- 满配 leave-one-out 消融（对照 = pro-t-dsl-conv-chk，方案见 ABLATION.md）


class ProTDslChk(ProTDsl):
    """满配 − conv：声明层 + C5b/C6 检查，不注约定文本。

    与满配的唯一差异 = conventions 关；顺带回答交互问题——
    chk 的收益（+5.77）是否依赖约定文本在场。
    """

    name = "pro-t-dsl-chk"
    extra_checks = True


class ProTDslConvChkR0(ProTDslConvChk):
    """满配 − 重试：修复循环 0 轮，其余逐位同满配。

    检查照跑、照记 trace，但没有重生成通道——检查只通过修复循环起作用，
    所以关重试 ≡ 关掉全部 C 的效果，一臂度量整个"校验→修复"回路的总值。
    注意 VA 可能回落：满配 VA 100% 有一部分是修复环救回的非法 SQL。
    """

    name = "pro-t-dsl-conv-chk-r0"
    max_repairs = 0


# ---- 学习式知识/规则阶梯（本轮 learned-checks 的主线，方案见 ABLATION.md）
#
# 全部 no-plan（知识的阻断器是 plan 前站，实测同一份知识 plan 后 ±0.00、
# plan 前 +4.81、裸直出 +8.65）、max_repairs=2（检查器只通过修复循环起作用，
# 关掉重试后检查照跑但改变不了输出，实测 −10.58）。四档只用新开关，
# 不碰 conventions/extra_checks/convention_checks，走 ProTDsl._stages() 里
# 的 DeclareStage 分支（不经 _ArchivedDeclareStage）。


class ProTDslKnowledge(ProTDsl):
    """+ 蒸馏知识（进 system）。相对 pro-t-dsl 单变量 = knowledge。"""

    name = "pro-t-dsl-knowledge"
    knowledge = True


class ProTDslKnowledgeRules(ProTDslKnowledge):
    """+ L2 学习规则（进修复环）。单变量 = learned_rules。"""

    name = "pro-t-dsl-knowledge-rules"
    learned_rules = True


class ProTDslKnowledgeRulesSqlens(ProTDslKnowledgeRules):
    """+ SQLens 静态信号。单变量 = sqlens_checks。★满配"""

    name = "pro-t-dsl-knowledge-rules-sqlens"
    sqlens_checks = True
