"""DeclareStage：plan → {sql, declarations} JSON → 纯规则校验 → 定向修复循环。

半程 IR 的编排（设计 docs/design/2026-07-22-M2-dslsql.md）：SQL 由模型直出，
校验只看声明与 SQL 是否自洽、是否接地；不过就把具体失败项发回模型重出，
最多 max_repairs 轮。轮数用尽取最后一版 SQL 照常下传（绝不因校验失败丢答案；
唯一空串的情形是三轮都解析不出 JSON）。
"""

from __future__ import annotations

from model.llm import ChatEndpoint
from model.pipeline.context import Candidate, PipelineContext
from model.pipeline.dsl import load_schema_info, parse_output, validate
from model.pipeline.templates import load_template, render


class DeclareStage:
    def __init__(self, endpoint: ChatEndpoint, max_repairs: int = 2) -> None:
        self.endpoint = endpoint
        self.max_repairs = max_repairs

    def run(self, ctx: PipelineContext) -> None:
        schema_info = load_schema_info(ctx.db_path)
        system = load_template("dslgen.system")
        for plan in ctx.plans:
            user = render("dslgen.user", schema=ctx.schema,
                          question=ctx.question, plan=plan)
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
                    issues = validate(out, schema_info, ctx.db_path)
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
