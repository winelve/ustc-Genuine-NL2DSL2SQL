"""DeclareStage：plan → {sql, declarations} JSON → 纯规则校验 → 定向修复循环。

半程 IR 的编排（设计 docs/design/2026-07-22-M2-dslsql.md）：SQL 由模型直出，
校验只看声明与 SQL 是否自洽、是否接地；不过就把具体失败项发回模型重出，
最多 max_repairs 轮。轮数用尽取最后一版 SQL 照常下传（绝不因校验失败丢答案；
唯一空串的情形是三轮都解析不出 JSON）。
"""

from __future__ import annotations

from model.llm import ChatEndpoint
from model.pipeline.context import Candidate, PipelineContext
from model.pipeline.dsl import (load_schema_info, parse_output,
                                profile_ids_for, render_profile, validate)
from model.pipeline.profile import build_profile
from model.pipeline.templates import load_template, render


class DeclareStage:
    def __init__(self, endpoint: ChatEndpoint, max_repairs: int = 2, *,
                 use_profile: bool = False, force_considered: bool = False,
                 extra_checks: bool = False, conventions: bool = False,
                 convention_checks: bool = False, use_plan: bool = True) -> None:
        # 中间状态（本计划 Task 2）：C5a/C5b/C6/C7 已归档到 dsl/archived_checks.py，
        # validate() 不再接受 profile_ids/extra_checks/convention_checks。下面
        # use_profile/force_considered/extra_checks/convention_checks 四个开关
        # 仍在（换代要等 Task 13），但已经不再传给 validate——归档档位
        # （archive.py 里那些 pro-t-plandsl-prof*/-conv*）的行为会暂时退化，
        # 这是预期的，Task 13 会把它们接回 validate_archived。
        self.endpoint = endpoint
        self.max_repairs = max_repairs
        # 五个开关默认关 = 对照基线；各消融档位在 models.py/archive.py 里显式打开。
        self.use_profile = use_profile
        self.force_considered = force_considered
        self.extra_checks = extra_checks
        self.conventions = conventions
        self.convention_checks = convention_checks
        # no-plan 消融：False 时不读 ctx.plans，question+schema(+约定)直达 dslgen，
        # 消除"planner 在无知识状态下先把决定定死"这个前站因素
        self.use_plan = use_plan

    def _system(self) -> str:
        """基线模板 + 可选约定附录。附录是追加式的——基线消息逐字节不变。"""
        system = load_template("dslgen.system")
        if self.conventions:
            from model.pipeline.conventions import conventions_block
            system += "\n" + render("dslgen.conventions",
                                    conventions=conventions_block())
        return system

    def run(self, ctx: PipelineContext) -> None:
        schema_info = load_schema_info(ctx.db_path)
        items = build_profile(ctx.db_path) if self.use_profile else []
        profile_ids = profile_ids_for(items) if self.force_considered else set()
        system = self._system()
        for plan in (ctx.plans if self.use_plan else [None]):
            if plan is None:
                user = render("dslgen.user.noplan", schema=ctx.schema,
                              question=ctx.question,
                              profile=render_profile(items))
            else:
                user = render("dslgen.user", schema=ctx.schema,
                              question=ctx.question, plan=plan,
                              profile=render_profile(items))
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            sql, declarations, rounds, passed = "", None, [], False
            for _ in range(1 + self.max_repairs):
                reply = self.endpoint.chat_messages(messages, temperature=0.0)
                out, parse_error = parse_output(reply)
                if out is None:
                    issues = [parse_error]
                else:
                    issues = validate(out, schema_info, ctx.db_path,
                                      question=ctx.question)
                    sql, declarations = out.sql, out.declarations.model_dump()
                rounds.append({
                    "sql": out.sql if out else None,
                    # 逐轮留声明：修复前后的声明差异就是声明层起没起作用的证据
                    "declarations": out.declarations.model_dump() if out else None,
                    "issues": issues,
                })
                if not issues:
                    passed = True
                    break
                messages += [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": render(
                        "dslgen.repair",
                        issues="\n".join(f"- {issue}" for issue in issues))},
                ]
            ctx.candidates.append(Candidate(
                plan=plan or "", sql=sql,
                checks={"passed": passed, "rounds": rounds,
                        "declarations": declarations},
            ))
