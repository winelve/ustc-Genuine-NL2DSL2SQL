# 提示词模板

改提示词 = 改本目录的 .md 文件，不用碰任何代码。改完先预览再跑：

```powershell
.venv\Scripts\python.exe -m model.pipeline --data en_dev --preview 0
```

## 内容流动

```
planner.system.md ──┐
planner.user.md ────┤  {schema} = 全量建表语句+每表3行样本   {question} = 题面
                    ▼
               planner LLM ──→ plan 文本 × n_plans ──┐
sqlgen.system.md ──┐                                │
sqlgen.user.md ────┤  {schema} {question} + {plan} ◀┘
                    ▼
               sqlgen LLM ──→ SQL 候选 × n ──→ 只读执行淘汰 + 多数投票 ──→ 最终 SQL
```

## 占位符字典

| 模板 | 占位符 | 值从哪来 |
|---|---|---|
| planner.system.md | （无） | planner 的角色设定，纯文本 |
| planner.user.md | `{schema}` `{question}` | `schema_with_rows(db)` / 数据集题面 |
| sqlgen.system.md | （无） | SQL 生成的角色设定，纯文本 |
| sqlgen.user.md | `{schema}` `{question}` `{plan}` | 同上 + planner 的输出 |

规则：占位符是 `{小写标识符}`；写错名字加载时直接报错并列出可用项；
模板里其他花括号（JSON 示例、集合写法）原样保留，不受影响。
中文题也走同一套英文提示词（direct generation，plan 用英文，见设计文档）。
