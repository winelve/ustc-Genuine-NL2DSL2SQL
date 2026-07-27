"""DeclareStage：plan → {sql, declarations} JSON → 纯规则校验 → 定向修复循环。

半程 IR 的编排（设计 docs/design/2026-07-22-M2-dslsql.md）：SQL 由模型直出，
校验只看声明与 SQL 是否自洽、是否接地；不过就把具体失败项发回模型重出，
最多 max_repairs 轮。轮数用尽取最后一版 SQL 照常下传（绝不因校验失败丢答案；
唯一空串的情形是三轮都解析不出 JSON）。

开关换代（本轮 learned-checks）：C5a-C7/画像/约定那一组旧开关（use_profile/
force_considered/extra_checks/conventions/convention_checks）已经不在这里——
归档档位（archive.py 的探索支、models.py 的 ProTDslConv 系 LOO 臂）靠
archive.py 的 `_ArchivedDeclareStage` 子类继续用它们，本类只留四个新开关
（knowledge/evidence/learned_rules/sqlens_checks）+ use_plan。`_ArchivedDeclareStage`
只覆写下面三个窄小钩子（`_system_extra` / `_profile_items` / `_extra_issues`），
`run()` 全程只有这一份。
"""

from __future__ import annotations

import sqlglot

from model.llm import ChatEndpoint
from model.pipeline.context import Candidate, PipelineContext
from model.pipeline.dsl import (load_schema_info, parse_output, render_profile,
                                validate)
from model.pipeline.dsl.checks import sqlens_issues
from model.pipeline.dsl.rules import eval_rules, load_rules, rules_path_for
from model.pipeline.knowledge import (knowledge_block, knowledge_path_for,
                                      load_knowledge)
from model.pipeline.templates import load_template, render


class DeclareStage:
    def __init__(self, endpoint: ChatEndpoint, max_repairs: int = 2, *,
                 dataset: str = "en_train", knowledge: bool = False,
                 evidence: bool = False, learned_rules: bool = False,
                 sqlens_checks: bool = False, use_plan: bool = True) -> None:
        self.endpoint = endpoint
        self.max_repairs = max_repairs
        self.dataset = dataset
        # 四个开关默认关 = 对照基线；各档位在 models.py 里显式打开。
        self.knowledge = knowledge            # 蒸馏知识进 system
        self.evidence = evidence              # 题目自带 evidence 进 user
        self.learned_rules = learned_rules    # L2 学习规则
        self.sqlens_checks = sqlens_checks    # SQLens 静态信号
        # no-plan：question+schema(+知识) 直达 dslgen，消除"plan 在无知识状态下
        # 先把决定定死"这个前站因素（实测：同一份知识 plan 后 ±0，plan 前 +4.81）
        self.use_plan = use_plan
        self._rules = load_rules(rules_path_for(dataset)) if learned_rules else []

    def _system(self) -> str:
        """基线模板 + 可选附加块（钩子）+ 可选知识附录。都是追加式的——
        基线消息逐字节不变；附加块排在知识之前，knowledge=False 时不影响
        只开附加块那一支的输出。主线的附加块永远为空，归档档位覆写
        `_system_extra` 插入约定附录。"""
        system = load_template("dslgen.system")
        extra = self._system_extra()
        if extra:
            system += "\n" + extra
        if self.knowledge:
            items = load_knowledge(knowledge_path_for(self.dataset))
            if items:
                system += "\n" + render("dslgen.knowledge",
                                        knowledge=knowledge_block(items))
        return system

    def _system_extra(self) -> str:
        """插在基线与知识附录之间的附加文本；主线永远为空，归档档位覆写为
        约定 prose 附录。"""
        return ""

    def _profile_items(self, ctx: PipelineContext) -> list[str]:
        """库画像条目；主线永远为空——归档档位覆写为 build_profile(ctx.db_path)。"""
        return []

    def _evidence_block(self, ctx: PipelineContext) -> str:
        """题目自带外部知识；开关关或题目没有时返回空串（模板里那一行变空行）。"""
        if not self.evidence or not ctx.evidence.strip():
            return ""
        return f"Evidence: {ctx.evidence.strip()}"

    def _extra_issues(self, out, ctx: PipelineContext, schema_info) -> list[str]:
        """L2 学习规则 + SQLens 静态信号。SQL 解析失败时上游已经返回，这里必成功。
        没开学习规则/SQLens 时提前返回，省一次 sqlglot 重解析。归档档位覆写这个
        钩子换成 C5a-C7（`validate_archived`），两者互斥、不会同时触发。"""
        if not self._rules and not self.sqlens_checks:
            return []
        tree = sqlglot.parse_one(out.sql, dialect="sqlite")
        issues: list[str] = []
        if self._rules:
            issues += eval_rules(self._rules, tree=tree, question=ctx.question,
                                 decl=out.declarations.model_dump(),
                                 db_path=ctx.db_path)
        if self.sqlens_checks:
            found = sqlens_issues(tree, out.sql, ctx.question, schema_info,
                                  ctx.db_path)
            for name in sorted(found):
                issues += found[name]
        return issues

    def run(self, ctx: PipelineContext) -> None:
        schema_info = load_schema_info(ctx.db_path)
        items = self._profile_items(ctx)
        system = self._system()
        for plan in (ctx.plans if self.use_plan else [None]):
            if plan is None:
                if ctx.fewshot_block:
                    user = render(
                        "dslgen.user.noplan.fewshot",
                        schema=ctx.schema,
                        question=ctx.question,
                        evidence=self._evidence_block(ctx),
                        examples=ctx.fewshot_block,
                    )
                else:
                    user = render(
                        "dslgen.user.noplan",
                        schema=ctx.schema,
                        question=ctx.question,
                        evidence=self._evidence_block(ctx),
                    )
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
                    issues += self._extra_issues(out, ctx, schema_info)
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
