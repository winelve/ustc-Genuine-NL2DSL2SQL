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
                 extra_checks: bool = False) -> None:
        self.endpoint = endpoint
        self.max_repairs = max_repairs
        # 三个开关默认关 = M3 系的对照基线；M3 各档在 plansql.py 里显式打开。
        # 注意基线与跑出 44.2 的 M2 并非同一套 dslgen 提示词（见 plansql.DSLSQL）。
        self.use_profile = use_profile
        self.force_considered = force_considered
        self.extra_checks = extra_checks

    def run(self, ctx: PipelineContext) -> None:
        schema_info = load_schema_info(ctx.db_path)
        items = build_profile(ctx.db_path) if self.use_profile else []
        profile_ids = profile_ids_for(items) if self.force_considered else set()
        system = load_template("dslgen.system")
        for plan in ctx.plans:
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
                                      question=ctx.question,
                                      profile_ids=profile_ids,
                                      extra_checks=self.extra_checks)
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
                plan=plan, sql=sql,
                checks={"passed": passed, "rounds": rounds,
                        "declarations": declarations},
            ))
