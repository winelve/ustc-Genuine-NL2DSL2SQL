# 项目进度

> 新会话入口文档。读完本文件 → `docs/DEVELOPMENT.md`（铁律）→ `README.md`（命令）即可开工。
> **每次会话结束时更新本文件**：完成了什么 / 决策了什么（附原因）/ 下一步。
>
> 最后更新：2026-07-22

## 目标

在 Archer benchmark 上构建 NL2SQL pipeline：先复现 OraPlan-SQL 作为对照组（M1），
再引入 DSL 中间层作为核心命题（M2），逐步消融对比证明 DSL 的价值（M3）。

- 论文：`docs/material/2510.23870v1.pdf`（OraPlan-SQL，Archer 2025 挑战赛第一名，EN 55.0 / ZH 56.7 EX）
- 架构图：`docs/material/image.png`
- 数据规模：en/zh 各 train 414 题（8 库）、dev 104 题（2 库）

## 里程碑状态

| 里程碑 | 内容 | 状态 |
|---|---|---|
| 基础框架 | `archer_eval` 评测器（VA/EX/SIM，Algorithm 1）+ `model` 生成框架 + runner + pytest | ✅ 完成 |
| M0 裸基线 | CT-3 prompt + LLM 直接出 SQL（deepseek-v4-flash/pro 已接入，含 thinking 对照） | ✅ 完成（en_dev 约 VA 98 / EX 20+） |
| M1 plan 式 pipeline（对照组） | planner → SQL 生成 → 执行淘汰 + 多数投票（默认 n_plans=1） | ✅ 代码完成+测试全绿；待真实 API 冒烟与 dev 跑分 |
| M2 DSL 中间层 | planner 后加 DSL 结构化输出 → 规则校验循环 → sqlglot 编译 + LLM 降级通道 | 🔨 代码完成+测试全绿；待真实 API 冒烟与 dev 跑分 |
| M3 增量迭代 | ASSUME 反事实算子 / 公式库 / 值链接强化 / 经验缓存 / 投票加宽 | ⬜ 未开始 |

## 当前工作：M1 plan 式 pipeline

**已实现**（2026-07-22，设计文档 `docs/design/2026-07-22-M1-plansql.md`）：

- `model/llm.py` — 公共 `ChatEndpoint`（从 api.py 抽取，APIModel 已改用，行为不变）
- `model/pipeline/` — `plansql.py`（PlanSQL 编排 + PlanSQLFlash 注册 `plansql-flash`）、
  `context.py`、`stages/{plan,generate,vote}.py`、`templates.py`（占位符校验）、
  `prompts/*.md`（提示词模板，直接编辑）、`__main__.py`（`--preview N` 预览消息）
- runner 新增 trace 钩子：`predictions/<模型名>_<数据集>.trace.json`
- 测试 70 项全绿（模板/投票纯函数 + 假 LLM 端到端，CI 不打真 API）

**全量结果与复盘（2026-07-22，deepseek-v4-pro-thinking 骨干，n_plans=1）**：

| 指标 | M0 直出 | M1 plansql | 差 |
|---|---|---|---|
| en_dev EX | 40.4% | 30.8% | **-9.6** |
| 其中 A | 66.7% | 62.5% | -4.2 |
| 其中 A+C | 25.0% | 21.4% | -3.6 |
| 其中 A+H | 36.4% | 22.7% | **-13.6** |
| 其中 A+C+H | 36.7% | 20.0% | **-16.7** |

回归 12 题 / 反超 2 题，回归 9/12 带 H。逐题看 trace 的根因链：
1. **planner 把反事实假设"正规化"成普通过滤或直接丢弃**（如"假如 UK 人口是 103000"
   被改写成 `WHERE Name='United Kingdom'`；"假如举办地在 Glebe Park"被当成待确认的
   既成事实然后忽略），或自造公式无视库里现成的列（GNPOld）。
2. **sqlgen 忠实执行错误的 plan**——thinking 骨干直出时自己的推理反而能处理对，
   经过"自由文本 plan"这一信息瓶颈后，错误被固化且无法恢复。
3. 这正是论文消融的复现：planner 无 guidelines（44.2）**差于**无 planner（64.4）。
   裸 plan 层是负资产，plan 的价值全部来自提示词质量——M2 的 DSL 命题恰好瞄准
   这个失败模式（自由文本表达不了假设语义 → 用 ASSUME 算子显式表达）。

**消融①结果（2026-07-22 重跑，唯一变量 = planner 反事实原则）**：

| | M0 直出 | 裸 plan | +反事实原则 |
|---|---|---|---|
| 总 EX | 40.4% | 30.8% | **40.4%** |
| A+C | 25.0% | 21.4% | 17.9% |
| A+H | 36.4% | 22.7% | **50.0%** |
| A+C+H | 36.7% | 20.0% | 36.7% |

- 总分与 M0 打平是**巧合而非趋同**：104 条预测仅 7 条与 M0 相同，8 回归 8 反超对冲。
- 原则修复 H 类干净利落（A+H 反超 M0 +13.6），8 条回归中 7 条是裸 plan 时代的老错。
- **净瓶颈移到 C 类**：plan 把错误的常识口径（如"出生年=当前年−Age"的 Archer 取值惯例）
  文字化固化，SQL 忠实执行。通用原则修不了口径问题，题型 guidelines 已被否决——
  这正是 M2 DSL/公式库的靶子。
- 结论：**M1 定格为对照组**（plan 层 ±0：H 增益 / C 损耗对冲）。104 题下 1 题≈1%，
  不再为个位数题目调提示词，避免滑向刷分 guidelines 路线。
- 归档：裸 plan 记录在 `results/plan-sql-logs/*.bare-plan.*`（用户已把历史结果收进
  `results/plan-sql-logs/`、`results/raw-deepsesk-model-logs/`）。

**M1 收官矩阵（2026-07-22，en_dev EX；非 thinking 组由用户补测）**：

| 骨干 | M0 直出 | M1 plansql (n=1) | M1 n=3 投票 |
|---|---|---|---|
| pro thinking | 40.4（VA 100） | 40.4 | — |
| pro 非 thinking | 22.1（VA 81.7） | **29.8**（VA 99） | 27.9 |

- **plan 框架的收益 = 骨干推理能力的补集**：非 thinking +7.7 EX 且 19 条无效 SQL
  全部修复；thinking ±0。与论文 planner 消融（64.42→72.12，+7.70）数值吻合——
  M1 复现完成，且给出新观察："自由文本 plan 层对强推理骨干是死重"。
- **n=3 投票 -1.9 是机制性的**：n=1 用 temp 0 贪心，n=3 三个候选全是 temp 0.7、
  失去贪心锚点；难题上三方结果各异时投票退化为"取第一个采样 plan"。若将来再开
  投票：候选 0 固定贪心 + 平票偏向贪心（论文投票也仅 +0.97，优先级低）。
- 结果文件：`results/en_dev_plansql-pro.json`（非 thinking n=1）、
  `en_dev_plansql-pro-3.json`（n=3）、`raw-deepsesk-model-logs/en_dev_deepseek-v4-pro.json`
  （非 thinking 直出）；thinking 组的历史记录见 plan-sql-logs/ 与 raw-deepsesk-model-logs/。

M1 定格为对照组，不再动。M2 的靶子是 thinking 自己补不出来的三样：机器可校验性
（DSL+校验循环，抓 A+C 口径错）、确定性编译（sqlglot 零幻觉）、外部知识注入
（公式库/值口径，M3）。ASSUME 算子对准 H。M2−M1 分差即中心论据。

## 当前工作：M2 DSL 中间层（声明层 + 校验循环）

**定位决策（2026-07-22，设计文档 `docs/design/2026-07-22-M2-dslsql.md`，三方案对比）**：
① 全程 IR（模型只出受限 DSL，sqlglot 编译）弃——M1 已证明"强推理骨干经过更窄的
中间层"会掉分，受限代数只会更窄；③ 片段 IR（算式走 DSL、骨架 SQL 直出、程序拼接）
弃——拼接边界工程上切不干净；选定 **② 半程 IR**：SQL 仍由模型全力直出，但必须随附
结构化声明表，纯规则校验声明的完整性/与 SQL 的一致性/接地，不过则定向修复——保住
thinking 骨干 40.4 的底盘、零表达力天花板，DSL 的作用是强制显式化 + 给 M3 知识注入
留插座。错误分布依据：+反事实原则后剩余 62 道错题全部是"SQL 合法但语义错"，C 类
主导模式是时间回算（没意识到要算 / 算了但口径猜错），纯结构校验一条都抓不到——
M2 的价值主张不是"约束/校验器"，而是逼模型把口径假设显式写进 anchor 槽位，
判对错留给 M3 公式库。

**实现清单**（分支 `dsl`，计划 8 个任务全部完成，93 项测试全绿）：

- `model/pipeline/dsl.py` —— 声明表 Pydantic schema（`time_context` / `outputs` /
  `assumptions`，零 Archer 专属词汇）+ `parse_output` + 四组校验器：
  C1 完整性（必填字段齐全 + sqlglot 解析 SQL 输出列与 `outputs` 一一对应）、
  C2 一致性（`displaced=true` ⇒ 至少一个输出列 derived；assumptions 必须参与计算）、
  C3 接地（表/列存在于 schema；字面值 difflib 近邻核对库内值）、
  C4 锚完整（`derived` 表达式每个时间语义列须有 anchor）+ `validate()` 总入口。
- `model/pipeline/stages/declare.py` —— `DeclareStage`：dslgen 调用 + 修复循环编排，
  校验失败项定向拼进对话重生成，默认 ≤2 轮，`Candidate.checks` 记每轮 trace，
  轮数用尽兜底取最后一版 SQL（绝不空串）。
- `model/pipeline/prompts/dslgen.{system,user}.md` + `dslgen.repair.md` 三件套、
  `templates.py` 占位符登记同步。
- `DSLSQL` / `DSLSQLPro` 注册为 `dslsql-pro`（骨干同 plansql-pro：deepseek-v4-pro +
  thinking），预测文件 `predictions/dslsql-pro_<数据集>.json`；planner 相关文件与
  M1 注册项零改动。

**最终审查修掉的两处（2026-07-22，commit 8b69185，均先补失败测试再改）**：

- **C3 存在性判定被候选池截断**：`_c3_literal_neighbors` 原先拿 `LIMIT 2000` 的
  截断值集判断"字面值在不在列里"。dev 两库碰不到（world_1 里 `Name`/`Population`
  列名跨表重名，被"不猜表"规则跳过），但 train 的 soccer_1 `Player.player_name`
  有 10848 个不同值、列名唯一——排在 cap 之后的**真实**球员名会被判成打错并附近邻
  建议，白白耗一轮修复去改正确的 SQL。改为带条件查询精确判存在，cap 只截断喂给
  difflib 的候选池（原本的用途）。
- **trace 每轮只留 SQL 不留声明**：设计 §5 要求"每轮的 SQL 与声明"，原实现只在
  `checks` 顶层留最终声明。修复前后的声明差异正是"声明层起没起作用"的过程证据，
  少了它修复率之外的定性分析做不了。现每轮 `rounds[i]` 都带 `declarations`。

**两项事实核查（2026-07-22，用户提出，见设计文档 §1）**：

- **`commonsense_knowledge` 字段测试时不提供**：Archer 论文（2024.eacl-long.6）
  主实验（§6.1）只输入问题本身，"w/ knowledge"仅为 §6.2 分析实验，OraPlan 全篇未用
  该字段——官方设定 = w/o knowledge。约束：M3 公式库不得直接使用 dev 集该字段，
  合法路线是从 train 集该字段离线蒸馏通用公式库，靠 train→dev 泛化。
- **数据库无字段注释**：10 库中仅 bike_1 的 DDL 带注释，dev 两库
  （concert_singer、world_1）零注释——模型对列语义的全部依据 = 列名 + 3 行样本，
  "`Age` 为当前年龄"这类口径在输入中根本不存在，只能靠模型猜或外部注入，佐证
  M2 anchor 声明 + M3 知识注入的组合设计。

**下一步**：用户跑 `dslsql-pro` 的 en_dev 真实评测（`.venv\Scripts\python.exe -m model
--model dslsql-pro --data en_dev --eval`），对照 M1 40.4；trace 里各检查触发率/
修复率是论文过程证据，值得单独统计。

## 决策记录

- 2026-07-22 · **M1 不做 schema embedding 检索**：论文对大库做 top-k schema 检索，
  但 Archer 单库表数很少，全量 schema + 每表 3 行样本直接给不损失效果且更简单（与总路线图一致）。
- 2026-07-22 · **meta-prompting 离线环节不复现过程、直接采用其产物**：论文的
  feedback-guided meta-prompting 是赛前离线迭代，其输出（附录 5.1 的 guidelines）
  直接写进 planner 系统提示词，即为对其结果的复现。
- 2026-07-22 · **中文走 direct generation**：论文附录 5.2 实测中文问题直接生成英文 plan
  远好于先翻译（79.8 vs 55.8），复现遵循此路线。
- 2026-07-22 · **不采用论文的 meta-prompting guidelines**（用户拍板）：附录 5.1 那套
  guidelines 是冲着刷分蒸馏的，针对性太强、泛化性存疑。M1 的 planner 用干净的通用
  规划提示词；entity-linking 一类的指引也不进默认提示词（提示词是可编辑文件，需要时手动加）。
- 2026-07-22 · **M1 不做 few-shot ICL 检索**（用户拍板删除）：论文消融显示 ICL 仅 +1.93 分，
  M1 求纯净对照组；后续若加，作为独立消融变量。
- 2026-07-22 · **执行失败的候选直接淘汰，不做回喂修复**（用户拍板）：与论文一致；
  修复闭环留给 M2 的 DSL 校验循环。
- 2026-07-22 · **默认 n_plans=1**（temp 0 可复现）；n_plans>1 时 planner 用 temp 0.7
  出多样 plan + 执行结果多数投票。投票机制照常实现，只是默认不开。
- 2026-07-22 · **pipeline 不叫 oraplan**（并非照抄复现）：包名 `model/pipeline/`，
  注册名 `plansql-<骨干>`（如 `plansql-flash`）。
- 2026-07-22 · **提示词与代码分离**：所有提示词放 `model/pipeline/prompts/*.md`
  纯文本模板（`{question}` `{schema}` `{plan}` 占位符），改提示词不碰代码；
  prompts/README.md 列每个模板的可用占位符。
- 2026-07-22 · **抽取公共 ChatEndpoint**：把 OpenAI 客户端封装从 `api.py` 抽成可复用的
  轻量类，APIModel 与 pipeline 共用，不重复造客户端。
- 2026-07-22 · **M1 全量结果为负增益（-9.6 EX），失败集中在 H 类**（复盘见"当前工作"）。
  待用户定夺：① 往 planner.system.md 加一条通用反事实处理原则（"假设=修改数据，
  不是过滤条件"，作为独立消融变量单独跑）；② 不修 M1，把它定格为"裸 plan 对照组"，
  直接推进 M2 用 DSL 的 ASSUME 算子解决同一问题。两者不冲突，可先①后②。
  → 2026-07-22 已实施①（单变量消融，待重跑）；变体类随用户改动定名 `PlanSQLPro`
  （plansql-pro = deepseek-v4-pro + thinking，flash 变体暂不保留）。
- 注意（潜伏问题）：pro 变体现开 thinking，DeepSeek 思考模式**静默忽略 temperature**；
  n_plans=1 无影响，但将来 n_plans>1 的多样性会失效，届时需关思考或换多样性来源。
- 2026-07-22 · **M2 选定半程 IR**（三方案对比见"当前工作"）：全程 IR 弃因 M1 已证明
  更窄的中间层会拉低强推理骨干（自由文本 plan −9.6 EX），受限代数只会更窄；片段 IR
  弃因算式/骨架拼接边界工程上切不干净；半程 IR 保住 thinking 骨干 40.4 底盘、
  零表达力天花板，且 M1 消融显示剩余错误全是"SQL 合法但语义错"、纯结构校验抓不到，
  DSL 的价值在于强制显式化口径假设 + 给 M3 知识注入留插座，不在于约束/校验本身。
- 2026-07-22 · **修复轮数默认 2**（`DeclareStage` 类属性，可调）：与 M1 的执行淘汰
  重试节奏一致，避免修复循环无限拖长单题延迟；轮数用尽兜底取最后一版 SQL。
- 2026-07-22 · **值近邻用 difflib，不引 rapidfuzz**：C3 接地检查现阶段只需"当前
  VA 100% 的保险"级别的近邻核对，标准库够用；M3 值链接强化需要更强的模糊匹配时再引
  rapidfuzz 依赖，避免过早引入未用满的第三方库。

## 完整路线图（总架构，M0→M3 是同一张图逐步点亮）

```
  自然语言问题 (en/zh)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ [0] 上下文准备层（纯程序，无 LLM）                       │
│   全量 schema + 每表 3 行样本行        ←不检索,直接全给   │
│   值链接: "Balmoor"→库内候选          (rapidfuzz)      │
│   few-shot: 相似题+gold SQL     [已删除, 需要时再消融]   │
│   公式库检索: 耗油=距离/油耗            [M3+]           │
└─────────────────────────────────────────────────────┘
        │  (问题 + 备好的料)
        ▼
┌─────────────────────────────────────────────────────┐
│ [1] 生成层（LLM 唯一的重活）                            │
│   Step A: plan   自由文本草稿           (给自己看)      │
│   Step B: DSL    Pydantic 结构 [M2+]   (给机器看)      │
└─────────────────────────────────────────────────────┘
        │  DSL (JSON/AST)   ※ plan 不下传, 只留作调试证据
        ▼
┌─────────────────────────────────────────────────────┐
│ [2] 校验层（纯规则，无 LLM）[M2+]                       │
│   结构/类型/引用完整性/值存在性 → 修复循环 ≤3 次           │
└─────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────┐
│ [3] SQL 层                                          │
│   主通道: sqlglot 确定性编译 DSL→SQL [M2+]             │
│   降级通道: LLM 直接生成 SQL (M1 即此通道; 记覆盖率)      │
└─────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────┐
│ [4] 执行层                                           │
│   SQLite 只读执行 → 报错自修重试；多候选按执行结果多数投票  │
└─────────────────────────────────────────────────────┘
        ▼
│ [5] 评测  archer_eval: VA / EX, 按 A/C/H 分桶（已完成） │

  M0 裸基线      schema+样本行 → LLM 直接 SQL            （地板分）
  M1 OraPlan复现 [0]few-shot → [1]仅plan → SQL → [4]投票 （对照组）
  M2 核心命题    +DSL → 校验 → 编译+降级                  （M2-M1 分差 = 中心论据）
  M3 增量迭代    +ASSUME/公式库/值链接/经验缓存             （每步只动一个变量，同一张消融表）
```
