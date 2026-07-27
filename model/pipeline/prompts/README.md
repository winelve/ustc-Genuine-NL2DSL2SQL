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

dslgen.system.md ──┐  M2 dslsql 用 dslgen 替换 sqlgen：
dslgen.user.md ────┤  同样吃 {schema} {question} {plan}，产出 SQL+声明表 JSON；
dslgen.repair.md ──┘  校验不过时把 {issues} 发回模型定向修复（≤2 轮）
```

## 占位符字典

| 模板 | 占位符 | 值从哪来 |
|---|---|---|
| planner.system.md | （无） | planner 的角色设定，纯文本 |
| planner.user.md | `{schema}` `{question}` `{profile}` | `schema_with_rows(db)` / 数据集题面 / 库画像（画像轴开时非空） |
| sqlgen.system.md | （无） | SQL 生成的角色设定，纯文本 |
| sqlgen.user.md | `{schema}` `{question}` `{plan}` | 同上 + planner 的输出 |
| dslgen.system.md | （无） | 声明层生成的角色设定 + JSON 格式说明 |
| dslgen.user.md | `{schema}` `{question}` `{plan}` `{profile}` | 同 sqlgen.user + 库画像 |
| dslgen.user.noplan.md | `{schema}` `{question}` `{profile}` | 去 plan 主线（dsl 系）用，无 `{plan}` |
| dslgen.repair.md | `{issues}` | 校验器产出的失败项列表（每行 `- ...`） |
| dslgen.conventions.md | `{conventions}` | K1–K11 约定块（conv 开时追加进 dslgen system） |
| dslgen.knowledge.md | `{knowledge}` | data/knowledge/<数据集>.json 蒸馏条目块（knowledge 开时追加进 dslgen system，约定附录之后） |
| direct.conventions.md | `{conventions}` | 同一份约定块（pro-t-direct-conv 臂追加进直出 system） |

规则：占位符是 `{小写标识符}`；写错名字加载时直接报错并列出可用项；
模板里其他花括号（JSON 示例、集合写法）原样保留，不受影响。
中文题也走同一套英文提示词（direct generation，plan 用英文，见设计文档）。
