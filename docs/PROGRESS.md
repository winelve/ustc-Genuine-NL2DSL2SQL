# 项目进度

> 新会话入口文档。读完本文件 → `docs/DEVELOPMENT.md`（铁律）→ `README.md`（命令）即可开工。
> **每次会话结束时更新本文件**：完成了什么 / 决策了什么（附原因）/ 下一步。
>
> 最后更新：2026-07-29

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
| M3 增量迭代 | ASSUME 反事实算子 / 公式库 / 值链接强化 / 经验缓存 / 投票加宽 | 🔨 画像前置注入（m3a/b）判负收档；m3c 检查器族并入 M3-d 强制臂验证；M3-d 约定轴进行中 |

## 2026-07-29 · 收尾整理审计与执行

- 用户确认最终保留的两个实验 idea 为 **DSL** 与 **fixed semantic few-shot**；
  Direct 只作为对照，其余 plan、conventions/knowledge、SFS、Value Evidence、
  selector、DPC 等路线统一视为探索性实验，不再与主线混排。
- 本轮只读盘点确认：当前 `.gitignore` 整块忽略 `docs/`、`predictions/`、
  `results/`、`data/fewshot/`，导致可复现资产与缓存一起被隐藏；同时
  `docs/DEVELOPMENT.md` 已不存在，但 `AGENTS.md` / `CLAUDE.md` 仍把它列为必读，
  文档入口失效。
- 已找回并审计 fixed semantic top-k：Archer `en_dev` k=3 共 104 records，
  BIRD 新/旧 dev 各 1533 个唯一题面 records；三份均为每题恰好 3 例、零重复
  source、零 self-selection。最终四格 prediction 也完整：Archer 各 104 条，
  BIRD 各 1534 条。
- 用户明确取消“修复文档入口”：不恢复 `docs/DEVELOPMENT.md`，不改现有
  `README.md` 的定位，也不重构本进度文档；改为新增 `README.new.md` 展示最终主线。
- `.gitignore` 已改为精确规则：运行期 predictions/results、模型权重、原始 corpus、
  SFS/VE/DPC 大体积产物继续忽略；三份 RSL k=3 selection 在原运行路径放行。
  `.superpowers/`、嵌套 `.superpowers/` 和任意 `superpowers/` 目录全部忽略；
  原先被跟踪的 10 个 `docs/superpowers/` 文件已从 Git 索引移除，本地文件保留。
- `model` 注册表拆为 `MAIN_MODELS` 与 `EXPERIMENT_MODELS`，兼容的 `MODELS`
  仍包含全部旧档位。主线只列 Direct / Direct+FS / DSL / DSL+FS 的
  Archer/BIRD 四格；`python -m model --list` 分组展示，生成算法与旧命令均未改变。
- 新增 `artifacts/`：冻结 Archer/BIRD 最终四格 prediction、可用 trace、详细/官方
  result，以及旧版 BIRD DSL+FS 历史快照；`manifest.json` 记录题数、分数、路径和
  SHA-256。新增 `experiments/README.md` 汇总探索代码与判定状态。
- 验证：manifest 中三份 selection、8 个最终臂和 1 个旧版臂的文件、题数、分数、
  trace 与 SHA-256 全部匹配；三份 selection audit 均为每题 3 例、零重复 source、
  零 self-selection；Archer/BIRD DSL+FS 无 API prompt preview 成功；
  `.venv\Scripts\python.exe -m pytest -q` 为 **500 passed**。

## 2026-07-29 · BIRD Direct+FS / DSL+FS 候选选择实验

- 用户批准直接复用已有 `bird-pro-t-direct-fs` 与 `bird-pro-t-dsl-fs`
  全量预测，不重跑候选生成；固定成功线为至少 **976/1534（63.62%）**，
  即相对当前 DSL+FS 960/1534（62.58%）净增至少 16 题。低于成功线立即收档，
  达标才复跑 selector 一次并考虑集成。
- 设计与实施计划分别提交为
  `docs/superpowers/specs/2026-07-29-bird-fs-selector-design.md` 和
  `docs/superpowers/plans/2026-07-29-bird-fs-selector.md`。
- 新增独立 `python -m model.selection`：读取两份对齐预测，通过 SQL 规范化、
  SQLite 只读执行结果等价和单路可执行性做零 API 路由；只有两路均可执行且
  结果不同才调用一次 DeepSeek output-contract pairwise judge。judge 只见
  question、evidence、DDL、匿名 A/B SQL 和执行摘要，不见 gold、评测标签或
  完整结果行；只准选 A/B，低置信度、格式/API 失败均回退 DSL。
- 实际全量 dry-run 路由为：`same_sql=197`、`same_result=919`、
  `direct_only_valid=12`、`dsl_only_valid=12`、`both_invalid=4`、
  `pairwise=390`。因此主实验无需重跑 1534×2 次生成，只需约 **390 次**
  selector API。
- 新增 10 个聚焦测试，最终全量回归为 **479 passed**；实现提交为
  `c2fc855`。
- 主实验实际路由因执行时序轻微变化为 `same_sql=197`、
  `same_result=919`、`direct_only_valid=11`、`dsl_only_valid=13`、
  `both_invalid=3`、`pairwise=391`；共调用 391 次 selector，消耗
  542,410 prompt / 41,914 completion / 584,324 total tokens，其中
  cache hit 284,672、miss 257,738。
- 最终 `bird-pro-t-fs-sel` 为 **941/1534（61.34%）**，相对 DSL+FS
  960/1534（62.58%）净少 19 题、−1.24 EX，未达到预设 976/1534
  成功线。配对翻转为 selector 独对 39、DSL 独对 58，McNemar exact
  `p=0.0671`。
- 退化定位到 LLM pairwise，而非候选互补性或执行路由：不用 judge、分歧题
  全回退 DSL 的规则路由反事实为 963/1534（62.78%，+3 题）；391 道
  pairwise 中 judge 改选 Direct 196 次，只救回 36 道 Direct-only 正确题，
  却破坏 58 道 DSL-only 正确题，净 −22。两路仅一方正确的 203 题里 judge
  只选对 98（48.3%），低于始终选 DSL 的 120（59.1%）。
- selector 的自报置信度不可用：390 个有效回复全部是 `high`，另 1 个解析/
  API 错误，没有任何 medium/low 分层；原始 A/B 选择为 A 274、B 116，
  显示明显首位偏差。损失分布在 moderate −12、challenging −7，且跨多个
  数据库，不是单库偶然异常。定性案例显示 judge 会把“是否额外返回指标列”、
  “是否按状态分别计数”、NULL 是否算作 other 等 BIRD 标注口径歧义，
  自信地解释成候选错误。

**决策：**按预注册 stopping rule 判负，不复跑 selector、不集成双路生成。
保留 standalone 代码与 trace 作为负结果证据。零 API 的单路可执行路由只有
+3 题（+0.20 EX），不足本轮 +1–2 分目标，也不单独并入主线。若未来重开，
必须使用有监督/校准过的 selector 或独立 verifier；不能继续修改零样本
pairwise prompt 反复烧 token。

## 2026-07-29 · BIRD DPC-1x1 低成本 Pilot

- 调研官方 DPC（ACL 2026）论文与
  `HKUSTDial/DPC@f75c759e58cc5b2b2a0d9b5227e38536e9a248ad`：官方
  Tester 构造 Minimal Distinguishing Database，Solver 独立生成 Pandas
  程序，再用 BS-F1 比较两个 SQL 结果；不需要 train 或本地大模型。
- 官方仓库可以复用核心代码，但当前不是可直接 `pip install git+...` 的包：
  flat layout 同时包含 `dpc/results/baseline/evaluation`，setuptools package
  discovery 会失败。新增 `python -m model.dpc_pilot bootstrap`，将固定 commit
  检出到 gitignored 的 `data/dpc/official/`；`requirements-dpc.txt` 只安装
  `chardet/scipy/tabulate` 三个缺失依赖。
- 新增 `model.dpc_pilot` 薄适配层：
  - 读取上一轮 selector trace 的 391 道 `pairwise` 题，按 difficulty
    分层、稳定 hash 固定抽 80 道；实际配额 simple 33 / moderate 25 /
    challenging 22；
  - 输入候选固定为 `[DSL+FS, Direct+FS]`，让 1-vs-1 执行聚类平票时更强的
    DSL 成为 champion；DPC 失败或证据不足均安全保留 DSL；
  - 官方 LLM Slicer 改为 sqlglot AST 的物理表切片并保留对应完整列，省去
    每题一次 API；官方 Tester、Solver、pipeline、execution clustering 和
    BS-F1 保持复用；
  - 默认 `DPC-1x1`：1 test data、1 solver、最多一次纠错、DeepSeek V4 Pro
    关闭 thinking，每题通常两次 API；逐题原子 checkpoint、耗时、调用次数和
    全部 token usage 均写入 trace；
  - 官方生成 Python 原本在子进程中开放完整 builtins。适配层增加 AST 限制，
    禁止 import、dunder、文件/网络/进程及 pandas I/O，再用最小 builtins 的
    spawn 子进程执行并保留超时。
- 输出把 pilot 决策合回完整 1534 条 DSL+FS baseline，现有
  `python -m bird eval` 可直接评分。预注册停止规则：相对 960/1534 净增至少
  4 题才扩大；净增 1–3 只定向复核；持平/下降立即收档。
- 已验证官方 checkout、依赖安装、80 题 manifest、无 key 安全回退 smoke、
  `git diff --check`、`compileall`；全量回归 **489 passed**。没有替用户调用
  付费 API。

**下一步：**用户按 README 先跑 `python -m model.dpc_pilot run --limit 5`；
检查 fallback、trace 与 token 后去掉 `--limit` 断点续跑 80 题，最后评测完整
输出。不要直接扩大到剩余 391 题。

### DPC 首次 5 题 smoke 暴露的问题与修复

- 首次付费 smoke 的 5 题中，官方 Solver 生成了 `import pandas` 和纯辅助函数，
  但适配层 AST 同时禁止 `Import` / `FunctionDef`，导致 4/5 题
  `Verification Error (All Data Failed)`，只有 1 题完成有效验证。该结果不能
  用于判断 DPC 效果。
- 首次 trace 的 usage 全为 null 并不代表没有 API 消耗。官方 pipeline 在内部
  ThreadPoolExecutor 中调用 Tester/Solver，项目 ContextVar 计量器没有传播到
  新线程；同时 runner 丢弃了 LLM 自己已累计的 usage。`fallbacks=0` 也只统计
  Python exception，没有识别官方 pipeline 返回的内部 fallback。
- 修复后：
  - Solver system prompt 明确 `pd`/DataFrame 已预载、禁止外部访问；执行器只
    允许冗余的 `import pandas as pd`，允许经过完整 AST 检查的无 decorator
    纯辅助函数，其他 import、文件/网络/进程、dunder 和 pandas I/O 仍禁止；
  - DeepSeek wrapper 独立、线程安全地记录每次调用的 elapsed/usage/error，
    runner 从 wrapper 合并逐题 API calls、cache/reasoning token，不再依赖
    ContextVar 跨线程传播；
  - `Verification Error` / `Slicer Error` 现在正确标为 `fallback`，
    `No Challenger` 标为 `no_duel`；
  - checkpoint 升级为 `bird-dpc-run-v2`，首次 5 条旧记录会自动重跑，其他
    固定题不受影响。
- 新增 `python -m model.dpc_pilot self-test`：移除 API key 后，用脚本化
  Tester/Solver 回复实际跑官方 pipeline、SQLite MDD、受限 Python executor
  和 BS-F1。实测输出为 `winner=direct`、
  `Challenger Won Duel (Votes: 1/1)`、`scripted_calls=2`，全程无网络/API。

**下一步：**重新执行相同的 `python -m model.dpc_pilot run --limit 5`；
runner 会自动重跑旧 5 条。确认本次 `fallbacks` 与非 null usage 后才继续 80 题。

### DPC 修复后 5 题付费 smoke

- 无 key `self-test` 按预期通过；修复后的 5 题均完成有效验证，
  `fallbacks=0`，旧 checkpoint 已正确重跑。
- 共 14 次 API：102,592 prompt / 24,831 completion / 127,423 total tokens，
  cache hit 68,992、miss 33,600。平均每题 25,485 token、2.8 次 API；按当前
  样本线性外推，80 题约 204 万 total token，明显高于最初依据论文均值的估计。
- 消耗归因：Tester 9 次调用占 96,179 token（75.5%），Solver 5 次占
  31,244（24.5%）；4/5 题首次 MDD 无效而触发 Tester correction，四次重试
  单独占 53,333 token（41.9%）。DPC 理论下限是 Tester+Solver 两次调用，
  本次实际均值为 2.8 次。
- 当前零 API table-level slicer 是主要放大器：California Schools 前 5 题每题
  保留 40–89 列、schema text 6.7k–23.3k chars，而两条 SQL 实际显式引用只有
  10–26 个不同列。官方 Tester 又要求每个合成 row 补齐 slice 中的所有列，
  因而同时放大 Tester 输入、MDD JSON 输出、retry 历史和 Solver 的 test-data
  输入。省掉一次官方 LLM Slicer 调用的简化在宽表上反而可能提高总 token。
- DPC 在 #2/#5/#18/#37 切到 Direct，#11 保留 DSL。复用已经完成的两臂官方
  评测逐题标签核对：
  - #37：DSL 错、Direct 对，净增 1；
  - #2/#5/#18：两臂都错，切换不改变 EX；
  - #11：两臂都错，保留不改变 EX。
  因此这 5 题相对 DSL+FS 是 **+1 / −0**，完整预测的反事实总分为
  961/1534（62.65%），但样本太小且前四题都是同一库的 challenging，不能作为
  80 题效果结论。
- #18 的 challenger BS-F1 仅 0.0588、champion 为 0，刚越过 epsilon=0.05；
  说明当前 1x1 选择仍会在两路都与 proxy 很差时切换。为避免看过 smoke 后改
  阈值造成实验口径漂移，暂不调整 epsilon。

**下一步：**考虑成本，不直接从 5 跳到 80；先运行
`python -m model.dpc_pilot run --limit 20`（只新增 15 题，预计约 38 万
token）。在运行前固定中间停止规则：累计 20 题净增至少 2 且无明显 DSL→错
破坏才继续 80；净增不超过 0 或 verifier fallback 明显则停止。

### DPC 累计 20 题 Pilot：触发停止规则

- 20/20 均完成有效验证，`fallbacks=0`；累计 399,895 total token
  （317,071 prompt / 82,824 completion，cache hit 168,960、miss 148,111）。
  DPC 切到 Direct 13 题，保留 DSL 7 题。
- #96/#97 的首次 Solver Pandas 程序在 merge 时错误使用缺失的
  `district_id`，触发 `KeyError`。这是 LLM 生成程序的运行错误，不是 SQLite
  或安全执行器故障；官方 self-correction 捕获 traceback 后各追加一次 Solver
  调用并成功完成。两次纠错分别增加 6,960 / 6,750 token，共 13,710。
- 复用固定 Direct/DSL 两臂既有官方逐题评测核对最终选择：
  - DPC gain：#37、#42，共 2；
  - DPC loss：#65、#73、#107，共 3；
  - 其余 15 题不改变 EX。
  因此相对 DSL+FS 为 **2 gain / 3 loss，净 −1**，反事实全量分数
  959/1534（62.52%），低于 DSL+FS 的 960/1534。

**决策：**累计 20 题净增不超过 0，且已经出现 3 个 DSL→错破坏，明确触发
预注册中间停止规则。停止 DPC pilot，不继续跑 80。运行时 `KeyError` 已由
预期的自纠错机制恢复，不需要为该错误重跑；即使进一步压缩 token，也不会改变
当前选择质量判负的事实。

## 2026-07-29 · BIRD Direct+FS / DSL+FS 分歧题导出

- 新增 `scripts/export_bird_disagreements.py`，将 selector trace 中全部
  `pairwise` 路由导出为 `analysis/bird_direct_dsl_fs_disagreements.json`。
- artifact 共 391 条；每条包含 1-based `question_no`、官方 `question_id`、
  dataset index、db/difficulty、question/evidence、`direct-fs`、
  `direct-dsl-fs`、gold `answer` 和两臂 correctness/label。
- 与既有逐题评测对齐验证：Direct+FS 独对 83、DSL+FS 独对 120、两者都错
  188，总计 391；没有同为正确的分歧题。JSON 结构、题号对齐和必需字段均已
  机械校验通过。

## 2026-07-28 · CHESS-IR Value Evidence 实现

- 开发前已把原工作区提交为 `d320430`，并在新分支 `codex/chess-ir`
  完成设计、实现和验证；设计/计划分别位于
  `docs/superpowers/specs/2026-07-28-chess-ir-value-evidence-design.md` 与
  `docs/superpowers/plans/2026-07-28-chess-ir-value-evidence.md`。
- 新增独立离线链路 `model.value_evidence.offline`：
  - SQLite 只读扫描 distinct TEXT values，按 CHESS 规则过滤 PK、ID/URL/email/
    date/address 等列和过长/过多取值；
  - character 3-gram、100-permutation MinHashLSH，阈值 0.01；
  - DeepSeek V4 Flash 关闭 thinking、temperature 0、max_tokens 256，沿用 CHESS
    原版 question + hint 关键词提示词；逐题记录 usage，支持成功项 checkpoint/resume；
  - LSH top-10 → edit threshold 0.3 → 本地 `all-mpnet-base-v2` cosine threshold
    0.6；exact/substring hit 不被 embedding 阈值误杀；
  - BIRD 列描述单独编码/检索；每列最多 3 个值、每题最多 12 个值和 8 列描述。
- 相关值与随机对照写入同一个严格 artifact。`ve-r` 不随机换列或增加值：
  在同一 table/column 内选择长度最接近的确定性 hash 候选；描述、值数量和所有
  其他 prompt 内容保持一致。artifact 与 index 位于 `data/value_evidence/`，
  默认 gitignored；线上生成不 import datasketch、NumPy、Torch 或
  SentenceTransformers。
- 注册 8 个实验档位：
  - Archer：`pro-t-direct-ve` / `pro-t-direct-ve-r` /
    `pro-t-dsl-ve` / `pro-t-dsl-ve-r`；
  - BIRD：`bird-pro-t-direct-ve` / `bird-pro-t-direct-ve-r` /
    `bird-pro-t-dsl-ve` / `bird-pro-t-dsl-ve-r`。
- BIRD human evidence 始终开启；VE schema 插入纯 DDL 后、官方 question/evidence
  block 前。Archer/BIRD baseline 均保持原路径：未启用 VE 时不读取 artifact，
  仍使用原 schema 表示。缺少 selection 或逐题 record 会明确失败，不静默退回。
- trace 新增 `value_evidence`，记录 selection/artifact/keyword/encoder SHA-256、
  固定阈值、关键词、列描述、相关值、control value 和本次实际注入值；prediction
  JSON 仍只含 SQL。
- 关键词预算按 Archer `en_dev` + BIRD `dev` 估计 115–118 万 DeepSeek token，
  建议预留 140 万；embedding 使用已存在的本地 `all-mpnet-base-v2`，不需要
  OpenAI key。
- README 已给出 index → keywords → select → audit、10 题 smoke、分阶段全量
  命令与 stopping rule：先跑 `ve` Direct；只有正向信号才跑 `ve-r`，再决定
  是否支付 DSL 全量成本。
- 独立 Python 3.11 环境已补装 `datasketch==1.6.4`，Archer `en_dev` 的两库
  index 已实际生成验证：`concert_singer` 52 values，`world_1` 9 values。
- 代码审查发现并修复：BIRD 重复题 target 去重、多词关键词的 CHESS 前后缀
  expansion、context evidence 组合查询、LSH 大小写统一、singleton control
  同值污染、audit 缺少 dataset SHA/target 覆盖验证、DISTINCT 非确定排序和
  ID/UUID/GUID 漏滤。复核后无 Critical/Important 阻断项。
- 最终验证：`git diff --check`、`compileall` 均通过；
  `.venv\Scripts\python.exe -m pytest -q` 为 **464 passed**。

**当前缺口：**真实 index、keyword 和 selection 尚未生成（需要用户的
DeepSeek key 与离线 Python 3.11/3.12 环境）；其中 Archer index 已完成，
Archer/BIRD keyword、selection 及 BIRD index 尚未生成，因此尚无效果分数。

**下一步：**按 README 先准备 Archer/BIRD artifact，各跑 10 题 Direct smoke；
确认 trace 中检索值合理后跑 Direct `ve` 全量。若 BIRD 官方 evidence 覆盖了增益，
按用户决策直接判该方法在本项目无效，不关闭 evidence 寻找虚假增益。

## 2026-07-28 · CHESS-IR Archer 首轮结果与退化归因

- `pro-t-direct-ve` 全量：VA 97.12%、EX **31.73%（33/104）**、SIM 38.01%；
  对照 `pro-t-direct` 为 VA 99.04%、EX **36.54%（38/104）**、SIM 41.78%，
  即净少 5 题、EX −4.81。
- 退化全部来自 `concert_singer`：15/52 → 10/52（−9.62 EX）；
  `world_1` 保持 23/52 → 23/52。配对翻转为 baseline 独对 8、VE 独对 3，
  双侧精确检验 `p=0.227`，单次结果方向负但未达到显著。
- thinking 波动仍很强：两臂只有 6/104 条 SQL 文本完全相同。26 道没有检索到
  value 的题里仍有 25 道 SQL 改变，但 EX 恰好一得一失；因此不能把每个翻转都
  归因于 value。
- 与 value 的关联仍明确：有 value 的 78 题中 baseline 独对 7、VE 独对 2，
  净 −5；无 value 的 26 题净 0。`concert_singer` 平均每题注入 3.37 个值，
  `world_1` 仅 0.69 个，污染面与退化库一致。
- 首要实现问题是 substring 强保留过宽：当前 211 个 value 中只有 94 个
  exact，`stadium.Name` 占 85 个（其中 51 个 fuzzy），另有 23 个 fuzzy
  `stadium.Location`。通用片段 `stadium` / `Park` 会让 Bayview Stadium、
  Forthbank Stadium、Queen's Park 等与 Somerset/Glebe 查询无关的值绕过
  embedding 与逐列 relative filtering；17 个最终候选甚至低于名义
  embedding threshold 0.6。按 CHESS 原始逐列 relative 规则回放，可删除
  51/211 个候选。
- 其次，当前 baseline→VE 不是纯加法：VE 用 DDL + retrieved block 替换了
  CT-3 的每表三行样本。`concert_singer` schema 在首题从 1560 字符降到 854，
  并丢失 `Is_male` 实际编码为 `F/T` 等表示信息。翻转题 #29 的 baseline
  正确使用 `Is_male='F'`，VE 改成 `Is_male=0` 且 JOIN 顺序产生语法错误，
  是该混杂因素的直接实例。
- 8 道 baseline→wrong 中，#23/#29/#34/#35 都带明显的额外错误值；#10/#11
  只有正确的 `Wide Awake`，#92 只有正确的 `Asia`，#97 没有 value，后三类更像
  thinking 波动或样本行表示变化。VE 还新增 3 条无效 SQL（baseline 仅 1 条）。

**决策：**当前 artifact/实验设计不能用于否定 Value Evidence；先不跑
VE-R、DSL 或 BIRD。若继续，应先单独修复为 CHESS 忠实的 threshold +
逐列 relative filtering（不允许普通 substring 无条件绕过），再把
“保留 CT-3 rows 并追加值”与“替换 rows”分开，避免同时改变两项变量。

## 2026-07-28 · CHESS-IR VE2 修复完成

- 保留 `chess-ir-mpnet-v1`、`pro-t-direct-ve` 及其负结果，不覆盖历史实验；
  新增 `chess-ir-mpnet-v2`、`pro-t-direct-ve2` 和
  `pro-t-direct-ve2-r`。
- VE2 对所有候选统一执行 embedding >= 0.6，不再允许 exact/substring
  绕过；随后按列执行 edit >= 0.9 × 列内最高 edit，再执行 embedding >=
  0.9 × 剩余候选最高 embedding。v1 reader/renderer 行为保持兼容。
- VE2 prompt 改为纯追加：先逐字保留 baseline 的 CT-3 DDL + 每表三行样本，
  再追加 retrieved context；VE2-R 只替换同列 control value。trace 新增
  `schema_mode=ct3-additive`，可以直接审计实验差异。
- 模型加载时 fail closed 校验 artifact strategy；audit 同时校验期望 strategy、
  v2 固定 embedding threshold=0.6 及每个保留值的实际分数，避免把误命名的
  v1 artifact 静默用于 VE2。
- 复用现有 DeepSeek keywords、数据库索引和本地 `all-mpnet-base-v2`，
  已离线生成 `archer_en_dev_chess_ir_v2.json`，本次 **0 DeepSeek token**。
  严格审计通过：104/104 records、155 values、26 题无 value、最低 embedding
  0.626847、阈值以下候选为 0；相比 v1 的 211 values 删除 56 个候选。
- README 已改为最小实验：只跑 `pro-t-direct-ve2` 和
  `pro-t-direct-ve2-r`，都与 `pro-t-direct` baseline 配对比较；Direct
  没有正信号时不继续跑 DSL/BIRD。
- 最终验证：实际 prompt 的 CT-3 baseline 前缀逐字保留；`compileall` 通过，
  `.venv\Scripts\python.exe -m pytest -q` 为 **469 passed**；独立代码复核
  无剩余 Critical/Important。

**下一步：**先跑 `pro-t-direct-ve2` 全量；若它恢复/超过 baseline，再跑
`pro-t-direct-ve2-r` 判断提升是否来自相关值，而不是单纯增加 prompt 内容。

## 2026-07-28 · CHESS-IR VE2 首轮结果与噪声分析

- `pro-t-direct-ve2`：VA 99.04%、EX **38.46%（40/104）**、SIM 43.49%；
  baseline `pro-t-direct` 为 EX 36.54%（38/104），表面提升 +2 题 /
  +1.92 EX。
- 配对翻转为 baseline 独对 6、VE2 独对 8、共同正确 32、共同错误 58；
  McNemar exact `p=0.791`。question-level bootstrap 95% CI 为
  **[−4.81, +8.65] EX**，不能排除退化，也不能证明正增益。
- 104 题实际是 52 个 gold SQL、每个两个 paraphrase；按 gold SQL cluster
  bootstrap 后区间仍为 [−4.81, +8.65]。SIM 的 +0.0171 配对变化区间
  [−0.0524, +0.0876]，同样不稳定。
- 最关键的内部噪声对照：
  - 有 value 的 78 题：baseline 独对 4、VE2 独对 5，净 **+1**；
  - 无 value 的 26 题：baseline 独对 2、VE2 独对 3，净 **+1**；
  - 无 value 时 VE2 renderer 退回逐字相同的 CT-3 schema，但 26/26 的生成
    SQL 都与 baseline 不同，说明 thinking 运行间波动足以制造当前量级的差值。
  扣除无 value 组的变化后，粗略 difference-in-differences 为 −2.56 EX，
  没有 value-specific 正信号。
- 定性检查 9 道“有 value 且正确性翻转”的题：5 道 VE2 gain 的主值都已直接
  出现在问题中；#50/#51 甚至同时注入了与假设 2010 冲突的 2013/2014，
  #18 仍带无关的 `Queen's Park`。这些 gain 更像 prompt 扰动导致模型换了一条
  推理路径，不能归因于新数据库证据。对应地，#10/#11 在只追加完全正确的
  `Wide Awake` 后反而成对退化。
- VE2 相对有缺陷的 v1 从 33→40（+7），配对 10 gain / 3 loss，
  exact `p=0.092`：这支持“严格过滤 + 恢复 CT-3 rows 修复了 v1 的明显伤害”，
  但仍不足以证明 Value Evidence 优于原 baseline。

**当前判断：**VE2 已把工程缺陷修好并恢复到 baseline 附近，但首轮 +2 更应标为
“方向为正、证据不足”，不能写成有效提升。等待正在运行的 `ve2-r`；完成后重点
比较相关值与随机值在 78 道有 value 题上的 paired flips，并用 26 道无 value
题估计同批运行噪声。若两臂差距也只有 1–2 题，则停止该 idea；只有相关值出现
明显且语义一致的独占收益，才考虑重复运行确认。

## 2026-07-28 · CHESS-IR VE2-R 相关性对照

- `pro-t-direct-ve2-r`：VA 100%、EX **35.58%（37/104）**、SIM 41.00%。
  三臂形成相关值 40 > baseline 38 > 随机值 37，但差距都很小。
- artifact/control 完整性核验通过：VE2/VE2-R 使用相同 artifact、相同 155 个
  slot 和列，VE2-R 的每个实际注入值均等于对应 `control_value`。
- 相关值 vs 随机值：
  - 全部 104 题为 relevant 独对 6、random 独对 3，净 +3，
    McNemar exact `p=0.508`，bootstrap 95% CI [−2.88, +8.65] EX；
  - 有 value 的 78 题为 relevant 独对 5、random 独对 2，净 +3 /
    +3.85 EX，`p=0.453`，95% CI [−2.56, +10.26]；
  - 无 value 的 26 题一边各独对 1，净 0。故相关/随机的全部分差确实发生在
    treatment 组，方向上支持“值的相关性有作用”，但尚不显著。
- 相对 baseline 分解后，78 道 treatment 题中：
  - relevant 为 5 gain / 4 loss，净 **+1**；
  - random 为 1 gain / 3 loss，净 **−2**。
  因此 relevant-random 的 +3 并非三个净新增正确，约三分之二来自随机值伤害，
  relevant 对 baseline 的独立净收益仍只有 1 题。
- 三臂逐题模式中，真正满足 baseline 错、random 错、relevant 对的只有
  #18/#43/#50/#51；其中 #50/#51 是同一 gold SQL 的两个 paraphrase，所以
  只有 3 个独立意图。相反 relevant 使 baseline 正确题退化的有
  #10/#11/#34/#92。按 52 个 gold SQL cluster bootstrap，relevant-random
  区间仍为 [−1.92, +8.65] EX。

**当前判断：**随机对照给出了一个弱的正向相关性信号，但证据强度不足以进入
DSL/BIRD：有效样本只有 52 个独立意图、paired `p=0.508`，且 relevant 相对
baseline 只净增 1/78。若要区分稳定收益与 thinking 波动，最低成本方案是再做
一组独立的 VE2/VE2-R paired repeat，并检查 #18/#43/#50/#51 是否重复出现；
重复性不成立则停止 Value Evidence，成立后才考虑扩大数据集。

## 2026-07-28 · CHESS-IR VE2 重复实验：判负收档

- 第二次 `pro-t-direct-ve2`：VA 97.12%、EX **35.58%（37/104）**、
  SIM 40.02%；第一次为 40/104、SIM 43.49%。同一 relevant arm 自身波动
  **3 题 / 2.88 EX**，恰好等于第一次 relevant-random 的全部分差。
- 第二次 relevant 与固定 random 都为 37/104：
  - 全部题 relevant 独对 9、random 独对 9，净 0、exact `p=1.0`；
  - 有 value 的 78 题也是 8 vs 8，净 0，95% CI [−10.26, +10.26] EX；
  - 无 value 的 26 题为 1 vs 1，净 0。
- 第二次 relevant 相对 baseline 为 11 gain / 12 loss，净 −1；在 78 道
  value 题为 8 gain / 10 loss，净 −2，而无 value 题仍净 +1。它没有重复
  第一次的 value-specific 正方向。
- 第一次相对 baseline 的 value gains 是 #18/#43/#50/#51/#58；第二次只有
  #18/#43 重复，#50/#51/#58 全部消失，另外出现 6 个全新 gain。相反第一次
  的四个 value losses #10/#11/#34/#92 在第二次全部重复，稳定部分偏负。
- 因用相同 model name 重跑，第一次 prediction/result/trace 已被第二次覆盖；
  首次汇总和逐题翻转仍保存在本进度记录中。后续若需要正式多次重复，应先增加
  run-id/versioned output，不能继续覆盖。

**最终决策：**当前 CHESS-lite Value Evidence 在 Archer `en_dev` 上判为
**无稳定增益**。工程修复能消除 v1 的明显退化，但 relevant 两次为 40/37，
random 为 37，相关性优势未复现；不再支付 DSL/BIRD 测试成本。本 idea 作为
负结果保留，下一步转向新的、与值检索无关的改进方向。

## 2026-07-28 · BIRD C3 名称误报修复

- C3 接地检查现在能正确解析 SQLite 引号列、物理表别名、CTE/子查询输出、
  匿名子查询、递归 CTE 列名，以及多层 `SELECT *` 传播的派生列。
- 用现有 BIRD DSL+FS trace 回放：schema 类告警从 **296 条 / 82 题**
  降到 **7 条 / 2 题**。
- 剩余告警经核验是真实不一致：`connected.atom_id1` 不存在；
  `SME_avg/LAM_avg/KAM_avg` 只写进 DSL 声明、没有出现在对应 SQL 中。
- 该修复只作用于后续生成时的检查与修复循环，不会改变已经生成的预测文件。
  若要衡量 EX 影响，需要重新生成一个实验臂。

## 2026-07-28 · BIRD 旧版 dev 与输出归档

- 旧版 `dev_20240627` 单独转换并注册为 `bird_dev_20240627`，与新版
  `bird_dev` 共用同一批 11 个数据库。
- 旧版题面与新版有 182 题不同，fixed few-shot 按题目哈希查找，因此不能复用
  `bird_dev_rsl_k3.json`；已重建独立的 `bird_dev_20240627_rsl_k3.json`。
- 新增旧版专用档位 `bird-pro-t-dsl-fs-20240627`，保留 BIRD evidence 协议并读取
  旧版 selection。`pro-t-dsl-fs` 仍只用于 Archer `en_dev`。
- `predictions/` 和 `results/` 根目录中的现有产物已按 bird/direct/dsl/gold 分类；
  同名但内容不同的早期产物保存在各分类的 `_archive/`，没有覆盖或删除。

**下一步：**运行旧版全量生成，再用 `python -m bird eval --official --cross-check`
按 `bird_dev_20240627` 评测；该分数只与旧版 BIRD 主榜比较。

## 2026-07-28 · BIRD 两版难度分布与旧版结果复盘

- 旧版 `bird_dev_20240627` 正确评测为 **61.60%（945/1534）**：
  simple 68.43%（925 题）、moderate 52.16%（464 题）、challenging
  48.28%（145 题）。
- 曾得到的 60.10% 使用旧版预测却漏传 `--data bird_dev_20240627`，实际按新版
  `bird_dev` gold 评测；其 860/443/231 分布也证明了错配，该报告不可用于结论。
- 两版难度迁移不是简单减少 hard：新版 challenging = 旧版 challenging 145 题
  + 旧版 moderate 21 题 + 旧版 simple 65 题。后两组被大幅改写后，在两次新版
  运行中仅命中 2/21 和 0–1/65，直接把新版 challenging 拉到 29.87–33.77%；
  原有 145 道 challenging 上三次为 48.28% / 51.72% / 46.21%。
- 旧版 moderate 的 308 道题面与 gold 均未变化题，三次分别为
  57.79% / 58.77% / 57.79%，没有模型级退化。111 道题面相同但 gold 后来修改的题，
  同一份旧预测按旧 gold 为 39.64%，按新 gold 为 53.15%，说明旧标注本身是主要拖累。
- 旧版 moderate 的 222 道错题只有 5 道执行/gold 错误；128 道最终 SELECT 输出列数
  与 gold 不同。correct/wrong 的 few-shot 最近邻距离与修复率近似，暂无证据表明
  top-3 检索或 DSL 修复协议是这次分桶差异的主因。

**决策：**两版只各自对齐各自榜单，不横比难度桶；旧版 61.60% 作为
`dev_20240627` 正式结果，60.10% 错配报告标记无效。

## 2026-07-28 · BIRD 定向错题归因

- 2025-11 challenging：153 道错题中，88 道输出列集合/数量不符，38 道聚合或
  结果粒度不符，15 道过滤值/时间条件不符，9 道执行错误/超时，其余 3 道。
  新版从旧 simple/moderate 升入 challenging 的 86 道重写题只对 3 道；其中
  83 道错题有 67 道属于输出列覆盖失败。原有 145 道 challenging 仍有
  51.72% EX，故低分主因是新版多字段综合报告题，而非普通 hard SQL 全面失效。
- 2024-06 moderate：222 道错题中，106 道聚合/去重/分母/结果粒度不符，
  54 道过滤值或时间条件不符，43 道输出列不符，5 道执行错误/超时，其余
  14 道为表示、连接或排序问题。另有旧 gold 与题面/evidence 矛盾的标注噪声，
  调方法时不能反向拟合这些错误答案。
- 现有检查器的盲点已量化：2025 challenging 错题仍有 149/153（97.39%）最终
  checks passed；旧 moderate 错题为 221/222（99.55%）。C1–C4 主要验证
  “声明与 SQL 自洽/引用存在”，不能验证问题要求的输出覆盖、实体粒度、分子分母、
  去重口径和过滤语义。
- 2025 challenging 典型 trace：#0 模型只声明并输出 4 个“characteristics”，
  但 gold 输出 10 列；模型已在 CTE 中算出 free rate 与 county average，却没有
  暴露到最终 SELECT，单轮无 issue 通过。#1189 把阈值写成全表
  `AVG(aCL IgM)`，而 gold 要求在 `Thrombosis=2 AND ANA Pattern='S'` 子群内求平均；
  声明只写最终 COUNT、未声明阈值总体，单轮无 issue 通过，实际结果 0 vs 3。

**后续方法调整优先级：**先增加 question→输出清单覆盖校验；再把
`result_grain / numerator / denominator / deduplicate_by / filters` 纳入声明与校验。
继续加普通 few-shot 或只修 SQL 语法不是这两组错题的首要方向。

## 2026-07-28 · 模型级提示词精确预览

- `model.pipeline` 新增必填 `--model`，只输出所选 no-plan DSL 模型实际发送的
  首轮 system/user 消息，不再混排未启用的 planner、sqlgen、画像或约定组件。
- 正式生成与预览共用上下文准备和消息构造：schema、fixed few-shot、BIRD
  evidence 均来自同一代码路径；预览不初始化或调用 API。
- 命令：
  `python -m model.pipeline --model pro-t-dsl-fs --data en_dev --preview 0`
  或将模型和数据换成 `bird-pro-t-dsl-fs` / `bird_dev`。

## 2026-07-28 · 结构感知 few-shot 检索调研

- 已核查 [DAIL-SQL](https://arxiv.org/abs/2308.15363)、
  [RB-SQL](https://arxiv.org/abs/2407.08273) 和
  [DCG-SQL](https://aclanthology.org/2025.acl-long.748/)：
  - DAIL 先生成草案 SQL，用去实体后的 SQL skeleton Jaccard 过滤问题语义近邻；
    是三者中最容易接入现有 fixed-selection 契约的方案，但会增加一遍草案生成。
  - RB-SQL 训练 question→SQL-skeleton 的双塔/MaxSim 检索器；能保持最终生成单次
    LLM 调用，但论文每个检索器约 2.2 亿参数，BIRD skeleton 训练对约 94 万，
    单 V100 训练 3–6 小时。其 BIRD 消融中 skeleton retriever 的独立增益仅
    +0.71 EX，完整复现的性价比不高。
  - DCG-SQL 还需 schema pruner、schema-link graph、对比学习 graph encoder 和
    Llama-3.1-8B 似然标注的 hard negatives；论文用 A100 80GB，两个检索模块约
    3+8 小时训练。论文给出的 GitHub 仓库目前只有 README，无法直接复现。
- 对 Archer `en_dev` 做了不改代码的离线诊断：沿用现有 all-mpnet 语义 top-30，
  用 sqlglot 算子多重集衡量 gold SQL 与候选 SQL 的结构相似度。
  - 当前语义 top-3 的平均结构相似度为 0.300；
  - 用 gold 结构做 oracle top-30 重排后，最佳三例均值为 0.470，104 题中
    79 题存在更好的结构候选，最佳结构候选的中位语义名次是第 12；
  - 用现有 Direct/DSL 草案 SQL 代替 gold 重排，均值仍可到 0.384/0.391，
    但分别有 23/22 题被错误草案带偏。
  这些数只证明检索池中存在结构 headroom；自定义相似度不是论文指标，也不能用
  gold 结构作为真实方法。
- **建议（待确认）：**第一步做 DAIL-lite 的离线两阶段混合重排，而不是纯结构替换：
  现有语义检索召回 top-30 → 共享的 zero-shot Direct 草案 SQL →
  sqlglot 规范化结构特征 → 语义/结构 rank fusion → 固定 top-3 selection JSON。
  Direct 与 DSL 必须共用同一份草案和 selection，避免把 DSL 能力偷渡进 DSL+FS；
  selection trace 增加草案来源、语义名次、结构分和最终名次。结构特征优先覆盖
  当前错题主因：输出列数、聚合/分组粒度、子查询/CTE 深度、集合运算、排序限制、
  算术与谓词形态。连续融合优于 DAIL 的硬阈值，避免错误草案把正确语义近邻全部滤掉。
- **备选路线：**若两阶段方法有效但不接受额外草案成本，再做 RB-lite：
  在 BIRD 9428 条 train 上训练轻量 question↔skeleton 对比检索器，用语义近邻中的
  错结构样本作 hard negatives；Archer 仅 414 条，不足以单独训练。完整 DCG-SQL
  当前不进入实现路线。

**下一步：**路线已确认并实现，见下面的 SFS 进度；本阶段明确不加入 RB-lite。

## 2026-07-28 · SFS（Structure-aware Few-Shot）实现

- 命名冻结为 `pro-t-direct-sfs` / `pro-t-dsl-sfs`，不使用
  `pro-t-direct-struct-fs`；两者只覆盖 `name` 和 `fewshot_selection`，
  共用 `archer_en_dev_sfs_k3`。
- 新增 SQLite/sqlglot AST 结构签名、多重集 Jaccard 与等权 normalized-rank
  fusion。特征忽略标识符/字面量，覆盖投影、聚合/分组、join、谓词、子查询/CTE、
  set-op、排序/limit、算术与 window；草案解析失败时严格保持语义顺序。
- 新增离线 `rerank-sfs`：
  semantic top-30 + frozen zero-shot Direct predictions → fixed SFS top-3。
  artifact 记录 target/semantic/draft 三个输入 SHA-256、固定权重、fallback 数，
  以及逐例语义/结构名次、
  结构相似度和融合分；Direct/DSL trace 共用同一序列化函数，旧 RSL trace 不变。
- 补齐 `python -m model.fewshot.offline` 入口；`requirements-fewshot.txt`
  增加 `sqlglot==30.13.0`。真实 draft 暴露默认 sqlglot 不接受 SQLite 反引号，
  已通过失败测试把解析方言固定为 `sqlite`，最终 104 题 0 fallback。
- Archer 真实 artifact：
  - semantic top-30 SHA-256
    `BCE07E58CBE0DB4397A691807BE69846FE1233E4494145E62CD36BD046516F79`；
  - frozen `pro-t-direct` draft SHA-256
    `D6EA9904C7D6B39BB36C2BB65075379A9509D8F85035BA71F173CEDB01F1C434`；
  - Archer `en_dev` target SHA-256
    `865DF28A35EA86D04C572C17C2C949860394B1A28B18818175BB1C554E7EDFD1`；
  - SFS top-3 SHA-256
    `4045B19B77A88468B64C39C459D2C4C4E43E1617809FA7C3C8491C3380261322`，
    重建前后逐字节一致。
- Audit：104 records、每题恰好 3 例、0 duplicate、0 self-selection；
  proxy draft-structure 均值 0.3372→0.4613。诊断-only 的 gold-structure
  均值 0.3399→0.3962（73 提升/9 持平/22 下降），未用于调参。
- exact prompt preview 已确认 Direct/DSL 第 0 题使用相同 source IDs
  `en_train:357 / 302 / 300`，DSL 仍要求 SQL+declarations JSON，Direct 仍为 CT-3。
- 效果实验现已运行：Direct 104 题与 DSL 10 题 smoke 均未显示增益；
  具体结果与归因见后面的“SFS 首轮真实结果与负结果归因”。
- 设计与执行计划：
  `docs/superpowers/specs/2026-07-28-sfs-structural-fewshot-design.md`、
  `docs/superpowers/plans/2026-07-28-sfs-structural-fewshot.md`。

**结论：**Archer 首轮未成立，不扩到 BIRD，也不先做 RB-lite。

## 2026-07-28 · 逐题耗时与 Token 统计

- 新增并发安全的逐题 metrics collector；每个 worker 用独立 `ContextVar`，
  不会在 Direct/DSL 并发生成时串题。
- `ChatEndpoint` 直接读取 DeepSeek 非流式响应的 `usage`，记录并汇总：
  `prompt_tokens`、`completion_tokens`、`total_tokens`、缓存命中/未命中 token
  以及 `reasoning_tokens`；不做本地估算。
- 每题 trace 新增 `metrics`：端到端 `elapsed_seconds`、调用次数、
  API 累计耗时、逐题 usage 总量和每次调用明细。DSL 的初次生成及修复轮次全部计入
  同一题；API 失败仍记录耗时和异常类型，未返回的 token 字段为 `null`。
- 端到端计时覆盖上下文与 prompt 准备、全部 API 调用、DSL 校验/修复和最终选择。
  预测 JSON 格式不变，统计只进入 `.trace.json` 与断点 trace。
- checkpoint stamp 升级为 `question-metrics-v1`，不会静默复用缺少 metrics 的旧断点。
- README 已补 SFS 10 题 smoke、104 题全量命令和 trace 字段说明。
- 验证：新增测试经过 RED→GREEN；最终
  `.venv\Scripts\python.exe -m pytest -q` 为 **428 passed**。

**结果：**metrics 已随 Direct 104 题全量验证；SFS 效果结论见下一节。

## 2026-07-28 · SFS 首轮真实结果与负结果归因

- `pro-t-direct-sfs` 104 题全量：VA 99.04%、EX **42.31%（44/104）**、
  SIM 47.30%；语义 top-3 为 EX 44.23%（46/104）、SIM 48.86%，因此 SFS
  点估计少 2 题、EX −1.92。
- 配对结果：语义 FS 独对 8 题、SFS 独对 6 题（双侧精确检验 `p=0.791`）。
  这不是显著退化，但明确没有取得正向证据。
- thinking 随机性不可忽略：示例及顺序完全不变的 4 题，生成 SQL 文本仍 4/4
  改变。因此单次运行的 −2 题不能全部归因于检索；后续方法比较需重复运行，
  或换非 thinking 的确定性骨干。
- 根因证据：
  - frozen zero-shot draft 只正确 38/104；draft 正确子集 SFS 净 +1，
    draft 错误子集净 −3；
  - SFS 将 312 个示例位置中的 161 个替换为原语义 top-3 外候选，42 个来自
    rank ≥10；算子多重集把语义完全不同但 SELECT/JOIN/算术外形相近的题拉入；
  - proxy 结构均值 0.3372→0.4613 是对优化目标本身的提升，并不预测 EX。
- DSL SFS 的前 10 题 smoke 为 4/10；旧语义 FS 同一前 10 题为 6/10。
  当前没有理由继续支付剩余 94 题成本。
- 新 metrics 在真实全量中工作正常：104 个 API calls；总计
  117,225 prompt / 140,609 completion / 257,834 total /
  130,217 reasoning tokens；逐题平均 22.71 秒，中位 17.91 秒。

**决策：**`sfs-v1` 作为负结果收档，不调 dev 权重、不跑 DSL 全量。若重开，
先设计能区分“逻辑变换”而非 AST 外形的表示，并处理错误草案传播；RB-lite
仍不因本次失败自动进入实现。

## 2026-07-28 · Value Evidence 调研（已转入 CHESS-IR 实现）

- 对齐 CHESS、SEED、SQL-R1 的消融口径：
  - CHESS 在 subsampled BIRD dev 上，相关 entity/context retrieval 相对
    “随机示例 + 全列描述”为 64.62 vs 59.86，净 **+4.76 EX**；但同时包含
    value 与 description retrieval，不是纯 value-only。
  - SEED 没有随机值对照；自动 evidence 相对无 evidence 的 BIRD dev 收益随
    下游模型从 **−0.58 到 +17.73 EX**，说明 evidence 格式和兼容性同样关键。
  - SQL-R1 的任意 representative values 在 RL 训练消融中为 63.1 vs 61.9，
    仅 **+1.2 EX** 且论文称不显著、会增加序列长度与训练成本。
- 代码核查：
  - CHESS 完整版需要 LSH、edit/embedding 重排、关键词 LLM 和列描述向量库；
  - SEED 还需 schema 摘要、BIRD train evidence few-shot、探索 SQL 和 evidence
    生成，每题约多 3–4 次 LLM 调用，Archer 无人工 evidence 可直接复用；
  - SQL-R1 只是每列无排序 `SELECT DISTINCT ... LIMIT N`，实际主路径没有启用
    question-relevant hits。
- 本仓库 `schema_with_rows()` 已经给每表无排序 `LIMIT 3`，等价于更重的任意值
  baseline。较可行的是 CHESS-lite：对小型 Archer 库只读扫描 distinct text values，
  用 exact/substring/edit similarity 选问题相关值，并让 Direct/DSL 共用固定 artifact。
  正式实验必须让相关值与任意值保持相同数量或近似 token 预算，只改变 value selection。
- 完整调研记录：
  `docs/analysis/2026-07-28-value-evidence-research.md`。

**后续：**用户确认采用完整离线 CHESS-IR 骨架、本地 all-mpnet、
相关值/同列随机值对照和 BIRD evidence 常开；实现状态见本文顶部
“CHESS-IR Value Evidence 实现”。

## 当前工作：RSL-SQL 风格 fixed few-shot 消融（2026-07-27）

目标只比较两个仍活跃的生成方式：`direct` 与 no-plan `DSL`，各自加/不加同一组
检索示例，形成四格消融。其他历史组件不再投入工作。

**已完成并验证：**

- 参考 RSL-SQL（Apache-2.0）重新实现离线检索，而非 vendor 整仓：
  `model/fewshot/` + `scripts/build_fewshot.py`。固定
  `sentence-transformers/all-mpnet-base-v2`、未归一化欧氏距离、`k=3`、稳定排序；
  在线生成只读取固定 selection JSON，不 import Torch/SentenceTransformers/PyArrow。
- 离线环境与主 `.venv` 分离。Windows 使用 Python 3.11/3.12、
  `torch==2.5.1+cpu`、`sentence-transformers==3.3.0`、
  `transformers==4.46.3`；后一个 pin 是因为新版 Transformers 会拒绝由
  Torch 2.5.1 加载本地 `.bin`。本地模型已实测成功编码 `(1, 768)` 向量。
- 修复了原计划广播欧氏距离的规模问题：三维临时量在 BIRD 上约 41.4 GiB；
  现按 256 个 target 分块，用二维精确欧氏公式，主要内存约几十 MiB。
- 资源已放入 `data/fewshot/`（全部 gitignored）：
  - Archer corpus：414 条；dev selection：104 条。
  - BIRD train parquet：9,428 条，字段 `db_id/question/evidence/SQL/schema`；
    SHA-256 `C47CCEBF3C9168D2A1957882489CFAEDAEA63A8A2AB7DDB1C57DE26C11C0A762`。
  - BIRD dev 有一条完全重复题（rows 863/875），故 1,534 行对应 1,533 个唯一
    selection record；重复题共享同一 top-3。
  - 两份 audit 均为：每条恰好 3 例、0 重复 source ID、0 self-selection。
- 新实验档位：
  - `pro-t-direct-fs`
  - `pro-t-dsl-fs`
  - `bird-pro-t-direct-fs`
  - `bird-pro-t-dsl-fs`
- 单变量边界已锁死：
  - baseline 关闭 FS 时不读 selection 文件，direct/BIRD official/DSL prompt
    保持逐字节不变；
  - BIRD direct FS 仍为一次 API、单 user message，完整 official prompt 是 suffix；
  - DSL 示例只展示 question + gold SQL，模板明确要求目标仍输出完整
    SQL + declarations JSON；
  - 缺 selection record 时 fail-closed，不静默退回 baseline；
  - prediction 仍是纯 SQL 数组，selection ID/距离/corpus checksum/encoder/k 只进 trace。
- 10 题 API smoke 已完成：
  - Archer：`direct+FS` EX 2/10，`DSL+FS` EX 6/10；同一前 10 题的既有
    `DSL` 为 4/10，因此 DSL+FS 暂时净增 2 题。
  - BIRD 官方 EX：`direct+FS` 2/10，`DSL+FS` 2/10；对应既有 baseline
    前 10 题分别为 2/10、1/10。
  - Archer DSL+FS：0 空 SQL、0 JSON parse failure、平均 0.5 次修复；
    baseline 为 0 parse failure、平均 0.6 次修复。
  - BIRD DSL+FS：0 空 SQL、0 JSON parse failure、平均 0.7 次修复；
    baseline 有 1 次首轮 parse failure、平均 0.7 次修复。
  - FS 提示词平均增加约 1,590 字符（Archer）/1,402 字符（BIRD）。
  协议健康门槛通过，可进入 Archer 全量；10 题正确率只作 smoke，不作效果结论。
- smoke 后发现 direct checkpoint 的 trace 为 `null`：SQL 生成与分数不受影响，
  但不满足逐题记录检索例的复现约定。已给 `APIModel` 增加对齐的 few-shot trace，
  runner 会为旧断点纯本地补齐 trace，不会重打已经付费的 API；两份 10 题 direct
  trace sidecar 已重建，每题均含 3 个 source ID。
- 当前 focused tests 为 **229 passed**；提交修复前仍需再跑全量测试。

**下一步：**

Archer `en_dev` 已通过效果门槛。下一步先去掉 `--limit 10`，断点续跑
BIRD 的 `bird-pro-t-direct-fs` 与 `bird-pro-t-dsl-fs` 两个全量臂；之后再实现
Archer selection 按数据集配置，并补 `zh_dev / en_train / zh_train` 的检索文件与跑分。

**2026-07-27 结果补记：**

- Archer `en_dev` 四格已跑齐：同期 `pro-t-direct` 36.54、`pro-t-dsl` 52.88、
  `pro-t-direct-fs` 44.23、`pro-t-dsl-fs` 58.65。few-shot 在 Direct/DSL 上
  分别 +7.69/+5.77；DSL 在无/有 few-shot 时分别 +16.34/+14.42。
- 历史 Direct 40.38（42/104）继续冻结保留；当前评测器复算仍为 40.38，
  本轮 36.54 是 thinking 重跑波动，不能用历史 Direct 与同期 FS 臂作严格归因。
- BIRD Direct 全量 57.37（880/1534），Direct+FS 全量 60.23（924/1534），
  fixed few-shot 提升 +2.86 EX；DSL+FS 仍待补全量。
- `--official --cross-check` 的官方串行阶段在 1534 题上约需 10 分钟，过去会静默等待。
  适配器现会在开始时提示，并每 30 秒打印累计耗时；官方脚本和评分逻辑未改。
- `docs/FEWSHOT_ABLATION.md` 集中记录四格 × 五数据集的历史结果、基本分析与缺失格子。
  当前 fixed selection 只覆盖 `en_dev` 和 `bird_dev`；
  `zh_dev / en_train / zh_train` 需先构建并接入各自 selection。

**2026-07-28 · BIRD C3 名称误报修复：**

- `model/pipeline/dsl/checks.py` 的 C3 现在按 SQLite 规则规范化双引号、反引号和
  方括号标识符，并从 sqlglot AST 解析物理表别名、CTE/子查询输出、匿名子查询、
  递归 CTE 显式列名，以及多层 `SELECT *` 的列传递。
- BIRD DSL+FS 既有 trace 的 103 个相关轮次回放：schema 类提示由
  **296 条 / 82 题降为 7 条 / 2 题**。剩余 7 条均为真实不一致：
  `connected.atom_id1` 不在物理 schema；`SME_avg/LAM_avg/KAM_avg` 只写在 DSL
  声明里、没有在 SQL 中定义。
- 该修复只影响今后的 DSL 生成与修复反馈，不会改变已经生成的预测文件或既有
  61.86 官方 EX。若要测实际分数影响，需要新建独立实验臂重新生成，不能覆盖旧结果。

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

**M2 实测（2026-07-23）**：en_dev EX 44.2（VA 98.1）、en_train EX 52.2（VA 99.0）。
对照 M1 的 40.4，dev +3.8。

## 当前工作：M3 知识层（库画像 + 强制表态 + 校验扩充）

**错因分析（2026-07-23，人工通读全部错题）**：
`docs/analysis/2026-07-23-cot-failure-analysis.md`（dev 58 错题）+
`2026-07-23-train-cot-failure-analysis.md`（train 198 错题，含对前者的复审与三处修正）。

关键结论——**dev 与 train 的失效画像相反，不可互相外推**：

| | dev | train |
|---|---|---|
| 真正的推理错误 | 62%（plan 阶段） | **9%** |
| pred 与 gold 形状完全相同（纯数值差） | 45% | **61%** |
| 主瓶颈 | 时间锚点臆断（推理层） | 口径/常数/输出形态（约定层） |

三条被数据推翻的假设（都写在分析文档里，附实测）：
1. **"通用公式库"大部分是空的**：133 道有 CK 的错题里约 97 道，CK 的内容 pred
   早就有了（"age = 给定日期 − dob"、"总价 = 单价 × 数量"模型本来就会）。真正
   补缺口的只有"Archer 规定值 ≠ 常识值"那 4–5 条（BMI 用 0.45 而非 0.453592、
   1 inch = 25mm 而非 25.4）——性质属约定对齐，划归 M3-d，不进主线。
2. **"列义注释生成器"完全没必要**：dev 的 9 条去重知识需求，全部落在
   "库画像 + 跨库通用公式"上，需要列义生成器的为 **0** 条。
3. **train 库 ≠ dev 库 ≠ test 库不构成障碍**：知识分两层即可绕开——通用层跨库、
   库画像层每库现算，两层都不依赖具体是哪个库。

**已实现**（分支 `dsl`，设计文档 `docs/design/2026-07-23-M3-knowledge.md`，154 项测试全绿）：

- `model/pipeline/profile.py` —— 库画像生成器，只出**程序可确定**的四类：
  存量时点列 / 时间成对列 / 多版本快照表 / 空表。10 库合计 **7 条**。
  dev 两个靶子命中（`singer.Age`、`GNP/GNPOld`），train 侧命中
  soccer_1 快照表与 formula_1 两张空表。
  **两条红线（2026-07-23 复盘后定）**：条目只摆事实、不教公式不给做法
  （锚定到哪个时点是模型在声明层自己表态的事，画像替它决定=往答案上暗示）；
  条目一律英文（注入英文 prompt）。
  刻意**不出数值列对**：Player_Attributes 单表就有 1264 组，进 prompt 只稀释注意力。
  快照表 vs 事件表的判别式 = 外键只指向一张表 **且没有任何表引用它**
  （后一条堵住 races 假阳性：races 被 7 张表引用，每行是独立赛事不是 circuit 快照；
  初版漏了这条，races 的误导条目会注进每道 formula_1 题）。
- `dsl.Considered` + C5a —— 强制对画像每条表态（used/why）。把"没想到"变成
  "想过并否决了"，后者可校验、可统计。
- `dsl._c6_ratio_hint` —— 题面要比率但 SQL 没有除法时，摆出同表数值列。
- `dsl.Anchor` 枚举化（now/column/literal）+ C5b —— 抓"声明对了、SQL 没跟上"。
- `plansql.M3A/M3B/M3C` —— 三档消融，开关是类属性；`DSLSQL` 基线三开关全 False
  并有测试锁死开关默认值。**⚠️ 但"基线与已跑出的 M2 逐位一致"是假的**（2026-07-23
  复盘发现）：dslgen 的 system/user 模板在 M3 开发中改过版（anchors 枚举化、
  considered 段、Facts 标题行），对基线同样生效——**M3 消融前必须用当前提示词
  重跑基线**，44.2 那个数不能直接当对照点。

**消融轴**：M3-a 只给知识 / M3-b + 强制用知识 / M3-c + 建议级校验。
**a→b 的分差 = "给知识"与"强制用知识"之差，是本项目最有论文价值的一个数。**

**两个检查器的实测精度（对着已跑出的 M2 预测算，"有用" = 该题原本判错）**：

| 检查 | dev | train | 备注 |
|---|---|---|---|
| C6 比率线索 | 触发 4，4 有用 / 0 有害 | 触发 11，6 有用 / 5 有害 | dev 是在 dev 上调的，train 的 55% 才是无偏估计 |
| C5b 锚一致 | 触发 2，2 / 0 | 触发 3，2 / 1 | 2026-07-23 加了 %字面量闸门后的数（原 dev 6，3/3） |

两者默认关闭、只在 M3-c 启用；净收益交给消融量，不预设。调参过程被测量纠正三次
（`\brate\b` 漏了复数导致四个靶子全没打中；收窄 `\bper\b` 反而让 train 从 6 有用
掉到 1 有用；C5b 初版没有 `displaced` 闸门，train 触发 119 条其中 80 条打在本来
判对的题上）——都记在各自 docstring 里。

**2026-07-23 复盘会话（用户质疑 3bc1ebd..44c649d 后全面核查 + 修正）**：

核查结论：可检验的数字（画像条数、C5b/C6 触发量与有用/有害、错题数、分析文档
引文、库内事实、gold 断言）全部复现，**没有发现编造数据**；但发现四类真实问题，
已全部修掉：

1. **races 假阳性**（见上，判别式加"零被引用"条件，8 条→7 条）。
2. **提示词特化暗示**：dslgen.system.md 把 "Age column in a table that has no
   birth-date column" 当例子写进 kind=now 的定义——等于把 Archer 的锚约定
   喂给 dev 锚点题。已改中性措辞。**泛化性红线：知识只通过画像层进 prompt，
   提示词模板里不得出现指向具体库/列/题式的例子。**
3. **画像条目教公式/教做法**（"先回推 出生年=录入年−Age"、"基准列是 GNPOld"、
   "必须明示取最新还是聚合"）：全部改成纯事实英文陈述，有测试锁死
   （test_profile_states_facts_not_recipes）。
4. **基线一致性声称失实**（见上 ⚠️）+ C5b 补 %闸门（dev 3 有害→0）+
   preview 分段标注 sqlgen 仅属 M1（消除"SQL 残余"误读）。

**m3a/m3b 判负收档（2026-07-23，dev 实测）**：四档实测（en_dev EX）：基线重跑 45.19 / m3a 42.31 / m3b 43.27 / m3c 49.04。
重跑基线后按协议跑 `m3a/m3b`——前置注入库画像 + 强制表态（C5a）在 dev 上是 **−2.9 / −1.9**（相对新基线 45.19），
且都落在 McNemar p ≥ 0.65 的噪声区间内，非机制性提升。逐题回查找到因果实锤：
#4/#5 两题的 trace 里模型在 `considered` 字段写下等同于"投降"的表态原话，
但把 `displaced` 判成 `false`——C5a 只强制"对画像表态"，不强制"表了态就必须
采纳"，`displaced=false` 成了合法的逃生门：画像给了知识，模型可以承认看到、
照旧不用，还能通过校验。m3c +3.85（≈4 题，McNemar p≈0.45）在噪声区间不下正结论，但其 C5b/C6 与 M3-d 的 C7 同属"决策点挑战"机制族，由 m3dc 以更高功效复验。
**结论：画像前置注入（m3a/m3b）判负收档**——
注册项保留作对照，不再投入。这与
下方 M3-d 的路线判断一致：知识若不带强制，价值就漏在"表态"和"执行"之间的缝隙里，
详见新开的 M3-d 一节。

**下一步（已执行，结果见 M3-d 一节）**：① 用当前提示词重跑基线
`dslsql-pro-thinking` en_dev（新对照点 45.19，替代旧的 44.2）；② 跑
`m3a/m3b`（结论见上，判负）与 `m3c`（+3.85 噪声区，见上文复验说明）；③ no-plan 消融待讨论，未启动。
M3-d（Archer 规定值表 + 输出形态规约 + entity-linking 指引）已升格为路线 A 主线，
独立消融轴、不与画像轴叠加计分——原因见下方决策记录与 M3-d 一节。

## 当前工作：M3-d 约定知识层（路线 A）

**路线判断（2026-07-23，用户拍板，详见决策记录）**：约定＝知识，M3-d 从"另开的
小计划"升格为主线。依据三条：① OraPlan 消融里 guidelines 值 +27.9 EX
（44.23→72.12，附录 5.1 那套本项目 M1 已否决，但分差本身说明"约定类知识"体量
可观）——对照本项目当前基线 45.19，量级相当；② 真知 NL2KE 架构的核心主张是
"知识＝带定义的词表＋强制绑定"，与画像轴"给了不强制＝漏"的判负教训一致；
③ 本项目自己的 CK 审计（train `commonsense_knowledge` 133 条错题相关知识里
97 条模型本来就会）证明知识注入的增量几乎全部集中在"规定值/口径约定"这一类，
不在"通用常识公式"。

**双臂协议**：`m3dp`（prose，约定表以自然语言追加进 dslgen 提示词，不改校验）
vs `m3dc`（prose + C7 建议级检查器强制表态）。m3dp − 基线 = 约定知识本身的价值；
m3dc − m3dp = 机器强制的净值。协议细节（对照点、读数方式、预期量级、
train/dev 分离）见下方"m3d 实验协议"。

**约定表实现**（`model/pipeline/conventions.py`，commit b99ed09 / 8f3142f）：
从 train 错题蒸馏 **K1–K11 共 11 条**，三条红线：只收 train 证据 ≥2 题的条目、
措辞泛化不点 dev 库列名、条目数 ≤12（有测试锁死）。**K6 证据修正**：初版证据
引了 world_1（dev 库）的例子，复核后剔除，"只用 train 证据"这条红线本身也补了
测试防再犯。约定表通过**附录追加式注入**进 dslgen 提示词（commit a9d6c7c）——
开关关闭时基线消息逐字节不变，有测试锁死，保证 m3dp/m3dc 与既有 M2/M3 基线
消息级可比。

**C7 约定检查器**（`model/pipeline/dsl.py` `_c7_*`，commit 372e1e5，建议级默认关，
只在 m3dc 启用）：三支，精度均为 Task 4 对 M2 归档 trace 的离线测量
（`scripts/measure_checks.py`，可复现，测量发生在协议写定**之后**，避免针对
数字调参）：

| 检查 | train 触发 | train 有用/有害 | dev 触发 | dev 有用/有害 |
|---|---|---|---|---|
| C7-const（规定常数/儒略式，K2/K3） | 27 | 26 / 1 | 0 | — |
| C7-abs（difference→ABS，K4） | 75 | 39 / 36 | 2 | 0 / 2 |
| C7-dodge（反投降） | 0（调整后） | — | 6 | 4 / 2 |

- **C7-const**：train 上几乎纯净（26/27 有用），dev 未触发——样本量太小无法单独
  验证，随 m3dc 整体一起读数。
- **C7-abs**：train 上薄利（39 有用 vs 36 有害，接近对半），是否留在 m3dc 里
  交给消融本身裁决，不预先关停；dev 上 2 次触发全部有害，权且记录、不调参
  （train-only 红线不允许拿 dev 结果反推规则）。
- **C7-dodge（反投降）**：初版含 `\bwould (?:have|be)\b` 分支，在 train 上
  0 有用 / 2 有害——#235/#243 两题查证是**价格反事实**（"if the price were X"）
  被误抓成时间位移语义，不是本检查器要抓的模式。按 train 证据把该分支去掉后
  train 触发降到 0（不再误伤）；调整后的版本在 dev 上触发 6 次、4 有用（#0/#5/
  #7/#48——**与 m3a 弃疗簇重叠（含 #5）**，即上面判负分析里模型"表态但不采纳"的那几题）、
  2 有害。**红线**：dev 这组数字只记录、不据此再调参——调参的证据来源必须是
  train，dev 只用来读最终协议的效果。

**实现落地情况**：`conventions.py`（11 条 K1–K11）+ `_c7_*`（3 支检查器）+
附录追加式注入（基线字节不变，测试锁死）+ `m3dp-pro-thinking` / `m3dc-pro-thinking`
两档已注册（`model/__init__.py`，commit 3d18dce）；全套 **170 项测试全绿**。

**m3d 实验协议（用户执行，2026-07-23 写死）**：

```
.venv\Scripts\python.exe -m model --model m3dp-pro-thinking --data en_dev --eval
.venv\Scripts\python.exe -m model --model m3dc-pro-thinking --data en_dev --eval
```

读数方式（写死，防临场脑补）：
- 对照点 = 本周基线 45.19（`results/en_dev_dslsql-pro-thinking.json`，模板未动
  所以继续有效）。
- m3dp − 45.19 = prose 约定的价值；m3dc − m3dp = 机器强制的净值。
- 每步逐题翻转表 + McNemar（脚本沿用本周做法）；|净差| ≤ 3 题按噪声报告。
- **预期量级**：dev 错题里约定族目标 ≥ 20 题（时间锚 18、形态 8、反事实模板、
  per-capita……有重叠），若 m3dc 仍在噪声区，路线 A 的 dev 上限即到，转
  zh_dev / 报告机制发现。
- train 上**不评测主数**（约定蒸馏自 train，评了算污染）；只可跑 sanity
  （预期大涨，涨幅只写"上界"不写结论）。

**m3d 实测（2026-07-23，按上方协议判读）**：

| | EX | vs 对照 | 翻转 | McNemar |
|---|---|---|---|---|
| m3dp（prose） | 45.19（VA 97.1） | **±0.00** vs 基线 | +8/−8 | p≈1.00 |
| m3dc（+C7 强制） | 47.12（VA 99.0） | **+1.92** vs m3dp | +8/−6 | p≈0.79 |

**两臂都在噪声区，按协议判：路线 A 在 en_dev 上没有兑现 OraPlan 量级的收益。**
逐题取证（不是纯噪声，机制清晰）：

- **prose 臂"用了但压不住"**：K5 靶子 #100 修对且在 m3dc 稳住（唯一干净的约定收益）；
  K10 的 #102/#103 各修对一半；但 **#98 在 K6 明文在场的情况下照样把 103000
  按份额分摊**（K6 禁的就是这个），#5 又把锚挂回发行年（K1 在场）——
  8 对 8 错正负相抵。**约定写进 system prompt ≠ 被执行**，与 m3a 的教训同构。
- **C7 实弹与离线预测吻合**：dodge 打了 #0/#10/#11/#48/#50 五题，模型五题全部
  顶住不改（多轮重复触发直到轮尽），修复转化率 0/5；abs 打了 #84/#86，离线预测
  的 2 条 harmful 里 #84 真的被改坏。**建议级挑战对 thinking 骨干顶不动**——
  dev #40 那次 C6 成功是少数派而非规律。
- **结构性混杂未排除**：约定只注了 dslgen，planner 仍在无约定状态下定 plan，
  dslgen 拿着约定去执行一个已经定错的 plan——与 m3a"只注 dslgen"是同一个错误，
  这次是为保 planner 冻结而主动选的。#98 的分摊策略正是 plan 阶段定下的。

**no-plan 消融（2026-07-23 用户拍板"试一下"，已实现，174 项测试全绿）**：
`NoPlanDSLSQL`（`noplan-pro-thinking`，去 PlanStage 的基线）与
`M3DPNoPlan`（`m3dp-noplan-pro-thinking`，+约定 prose），
新模板 `dslgen.user.noplan.md`、`DeclareStage(use_plan=False)`；
单变量红线有测试锁死（唯一差异 = conventions）。

```
.venv\Scripts\python.exe -m model --model noplan-pro-thinking --data en_dev --eval
.venv\Scripts\python.exe -m model --model m3dp-noplan-pro-thinking --data en_dev --eval
```

读数（写死）：noplan − 45.19 = 纯去 planner 的效应；
m3dp-noplan − noplan = 排除 plan 前站后 prose 约定的净值。
|净差| ≤ 3 题按噪声报告。

**no-plan 实测（2026-07-23）——本项目第一个显著结果**：

| | EX | 翻转 vs 上一档 | McNemar |
|---|---|---|---|
| 基线（有 plan） | 45.19 | — | — |
| noplan | **52.88**（VA 99.0） | +17/−9 | p≈0.17 |
| noplan+约定 | **57.69**（VA 99.0） | +13/−8 | p≈0.38 |
| **合计 基线→noplan+约定** | **+12.50** | **+20/−7** | **p≈0.019 ✅** |

逐题机制（不是噪声，两步各有清晰指纹）：

- **去 planner 的 +17 里 12 题是时间锚簇**（#12–15/#20–23/#48–51）——dev 最大
  单一错因（锚点臆断）大部分**自愈**：不是知识修好的，是移走了"在无知识状态下
  先把锚定死"的前站。plan 层对 thinking 骨干不是死重（M1 结论），是**负资产**，
  下游越结构化（声明层）越明显。OraPlan 自家消融早就写着同一形状：
  无 guidelines 的 planner（44.23）**差于**无 planner（64.42）；我们 45.19 < 52.88。
- **约定的 +13 里 9 题是点名靶子**：#100/#101（K5 CAST）、#102/#103（K10
  per-capita，两题首次同时对）、#26/#27（K11 宽表，首次对）、#98（K6 反事实，
  夺回）、#5（锚）。**同一份 prose，在 plan 后面 ±0.00，在决策点前 +4.81**——
  知识注入的成败不在内容在时机：必须抵达"尚未被约束的决策点"。
- 仍未破：#0–#3（Gentleman 无 WHERE 读法）、#24/#25（Average 字面吸引）、
  #92–95（线性外推，约定表按 train-only 红线没收这条）。

**诚实警示**：no-plan 这一刀是看完 dev 取证后下的——en_dev 对这个决定而言
已不是干净考卷；zh_dev / test 复验通过前不庆祝。m3dp-noplan−noplan 单步
p≈0.38，靠靶子指纹撑机制解释，复验时重点看约定靶子是否再现。
**train 复验已做（见"验证债① 实测"节）：train 上净 +3 题 p≈0.78 纯噪声——
"负资产"仅在 plan 型错误占主导的 dev 画像上成立，勿写成全局结论。**

## 刷分冲刺（2026-07-23 用户定调：继续在 en_dev 冲分，目标 60+）

**最终成绩：`m3dx-noplan-pro-thinking` en_dev EX 63.46（66/104，VA 100）——
2026-07-23 用户确认满足，冲分收档。实测与归因见下方"牌 1 实测"。**
（下文为冲刺时的牌面记录，保留供论文取材。）
到 60% 需再 +3 题；65% 需 +8。剩余 44 错题的簇分布与三张牌：

**牌 1（已实现，下一跑）**：`m3dx-noplan-pro-thinking` = m3dp-noplan + C5b/C6
建议级检查（extra_checks）。依据：C6 dev 离线实测 4 触发 4 有用 0 有害，
靶子 #24/#25/#40/#41 在 57.69 的错题单里全数仍错；C5b 带 %闸门后 2/2/0。
**C7 刻意不开**（C7-abs dev 0 有用/2 有害，#84/#86 现在是对的，开了负期望）。
预期 +2~4 题 → 59.6~61.5。

```
.venv\Scripts\python.exe -m model --model m3dx-noplan-pro-thinking --data en_dev --eval
```

读数：对照 57.69，逐题翻转 + McNemar；重点看 #24/#25/#40/#41 是否被 C6 顶动
（老 m3c 时代 C6 曾在 #40 顶两轮成功，但那时有 plan；#24/#25 当年三轮顶不动）。

**牌 1 实测（2026-07-23）：EX 63.46（VA 100.00，66/104）——超预期上限，用户满足，冲分收档。**

单步 57.69→63.46：+11/−5 净 +6，McNemar p≈0.21（单步不显著）。
累计 基线 45.19→63.46：**+22/−3 净 +19，p≈0.00016**——整条 no-plan+约定+检查
链路对基线是压倒性显著。

+6 的归因分解（trace 逐题核对，消息→检查器映射已对照 `dsl.py` 源码确认）：

- **C6 净 +3，与离线预测完全吻合**：#24/#25/#40/#41 四靶全部触发、模型四题
  全部在被顶后改写 SQL 且终版含除法（trace rounds 可查），#24/#25/#41 三题
  转对，#40 改了仍错，0 有害。离线预测 4 触发 4 有用，实弹 4 触发 3 转化——
  **无 plan 时建议级检查顶得动 thinking**（对照 m3c 时代有 plan 时 #24/#25
  三轮顶不动），plan 的"锁死效应"连修复回路也压制。
- **C5b 净 0**：只触发 #93（未修出），无害。
- **其余 +8/−5 净 +3 是重跑抖动**：#64/#65/#72 修对时两档都无任何检查触发，
  纯采样方差；#48/#51（锚簇）这次翻错，触发的只有两档共有的恒开 C2。
  注意"displaced=true 但无 derived"这条消息属 **C2（恒开）不是 C5b**，
  归因时勿凭消息文本猜编号，以 `dsl.py` validate() 的门控为准。

**诚实口径**：63.46 里约 3 分是运气（抖动净 +3），本臂真实力约 60–61，
重跑可能回落；但 C6 的 +3 是有 trace 因果链的真收益。VA 100% 系修复回路
把最后一个非法 SQL 也救回。牌 2（dev 蒸馏，未跨线）、牌 3（C8，未实现）
均不再需要。

**牌 2（16 题的大矿，但需用户拍板跨线）**：剩余四大簇
①#0–#3 时间状语读法（"at the time of X's release"作用于全表非过滤）
②#6/#7/#46/#47 成员反事实（"若 X 参加了所有演唱会"=补行，非过滤）
③#60–#63 majority=plurality + 比较分母取全库
④#92–#95 线性外推（增长率不变=等差 GNP+(GNP−GNPOld)，非等比）
——**已 grep 验证 train 零证据**（四个正则均 0 命中），train-only 红线立不了项。
要吃这 16 题只能走 **dev 蒸馏 guidelines**（= OraPlan 附录 5.1 的原始做法，
挑战赛惯例，但违反本项目 2026-07-23 定的"知识只从 train 立项"红线）。
方案若批准：另立 `KD*` 命名空间 + 单独档位（如 m3kd-noplan），文档明标
"dev-informed，不与 K-train 轴混算"，泛化性由最终 test 集裁决。**待用户拍板。**

**牌 3（合法、程序化、还没实现）**：C8 "字面值在别的列"检查——
#68–#71 的 `Kang-won` 是 `city.District` 的值，pred 拿去配 `city.Name` 返回空集。
纯 schema+数据驱动（同 C3/C6 家族，零 Archer 专属），实现后先用
`scripts/measure_checks.py` 对 train 离线测精度再定去留。靶子 4 题。

**验证债（冲分后必须还，写论文前不可跳）**：
① ~~`noplan-pro-thinking` 跑 en_train~~ **已还（2026-07-23，实测见下节）**；
② zh_dev 三档复验（基线/noplan/noplan+约定）——no-plan 决策是看完 en_dev
取证后下的，en_dev 对它已不是干净考卷；③ m3dc-noplan（C7 无 plan 转化率）。

### 验证债① 实测：noplan @ en_train（2026-07-23）

`noplan-pro-thinking` en_train：**EX 52.90**（VA 98.07，219/414）。
对照 = `results/m2-dslsql/en_train_dslsql-pro-thinking.json`（带 plan，EX 52.17，
216/414）。逐题翻转 **+27/−24，净 +3 题，McNemar p≈0.78——train 上纯噪声**。
分错因类型看也无单簇：A 降（69.3→64.9）、A+C 平、A+C+H/A+H 各微升。

**判读（对"planner 负资产"结论的修正）**：
- dev +7.7 在 train 上**不复现**——planner 的害处不是全局的，而是集中在
  dev 特有的失效画像上（62% plan 阶段推理错、时间锚簇 12 题自愈）；train 推理错
  只占 9%（口径/常数为主），plan 移走后无从获益，只剩 ±24/27 的大幅 churn 对消。
  这与"dev 与 train 失效画像相反"的错因分析完全自洽，机制解释反而更完整了：
  **去 planner 的收益 ∝ 数据集里 plan 型错误的占比**。
- 论文口径应写成："移除 planner 在 414 题干净大样本上无害（p≈0.78），
  在 plan 型错误占主导的 dev 上显著获益"——不写"planner 全局负资产"。
- **混杂提醒**：对照是 M2 时代模板（anchors 枚举化等改版前）跑的，非严格单变量；
  dev 侧同一模板漂移只值 ~+1 分（44.2→45.19），不足以翻转"train 无净效应"的读数。
  如需论文级严格对照，须用当前模板重跑 `dslsql-pro-thinking` en_train（414 次
  调用，费用大，暂记账不跑）。

**新会话交接须知**：预测/结果文件在 `predictions/`、`results/`（历史归档在
`results/m3-knowledge/`、`predictions/m2-dslsql/`）；逐题对比脚本模式见本文件
各"实测"节（load results samples 的 index/match 做翻转表 + McNemar）；
检查器精度一律用 `scripts/measure_checks.py` 复算，不许凭记忆引数字；
错题分析文档在 `docs/analysis/`（gitignored，勿删）；约定表红线测试在
`tests/test_conventions.py`，改 K 条目前先读它。

## 当前工作：满配 leave-one-out 消融（2026-07-24 立项）

**目标**：对主线满配 `pro-t-dsl-conv-chk`（en_dev 63.46）做减法消融，每臂从满配
只减一个组件。方案、臂表、命令与读数协议的**唯一出口是 `docs/ABLATION.md` §3b**，
此处只记决策与交接。

**三条设计决策（2026-07-24，用户拍板）**：
1. **"关掉全部 C" ≡ "去重试"是同一个实验**：检查器只通过修复循环起作用
   （`declare.py` 的重生成回路），关重试后检查照跑但改变不了输出。故用户原提的
   5 组去重后 = 3 个新臂：`pro-t-dsl-chk`（−conv）、`pro-t-dsl-conv-chk-r0`
   （−重试，`max_repairs=0`）、`pro-t-direct-conv`（−声明层 = 裸直出 + K1–K11）。
2. **C 不逐个消融**：逐检查器归因从已有 trace 免费复算（C6 净 +3 / C5b 净 0），
   不花 API 钱；LOO 只出臂级总分。7 格里 4 格复用已有数，只需 3 跑。
3. **−声明层臂的论文价值**：与 `pro-t-plandsl-conv`(±0)、`pro-t-dsl-conv`(+4.81)
   构成"同一份约定 × 三个注入位置"的完整曲线，直接检验"约定的收益是否依赖
   声明层"——若不涨，反证 DSL 核心命题。

**代码清理（同日完成，用户拍板）**：
- `model/pipeline/plansql.py` → **`models.py`**（git mv 保留历史）：编排基类 +
  主线阶梯 + 新增 LOO 两臂（`ProTDslChk`、`ProTDslConvChkR0`）。
- 判负存档支（prof/force 画像轴 3 类 + plandsl-conv/cchk 2 类）挪到
  **`archive.py`**，注册保留（归档≠删除，历史结果可一键复跑）。
- `pro-t-direct-conv` 落在 `model/api.py`（`DeepSeekProThinkingConv`）：APIModel
  加 `conventions` 开关 + 新模板 `prompts/direct.conventions.md`（措辞去掉声明层
  专属词汇）；关闭时 system 逐字节同基线，有测试锁死。
- 单变量红线测试 5 条新增（LOO 三臂各一 + 直出 system 字节一致两条），
  **181 项测试全绿**。

**LOO 实测（2026-07-24，用户跑三臂，结果表与完整判读在 ABLATION §3b）**：

| 臂 | EX | Δ vs 满配 63.46 | McNemar p |
|---|---:|---:|---:|
| −chk（已有） | 57.69 | −5.77 | 0.21 |
| −conv | 56.73 | −6.73 | 0.19 |
| −重试 | 52.88 | −10.58 | **0.027 ✅** |
| −声明层 | 49.04 | −14.42 | **0.0015 ✅** |

三个要点（细节见 §3b）：
1. **组件边际排序：声明层 > 重试环 > conv > chk**；前两名单臂显著，
   conv/chk 单臂不显著但合并显著（−conv−chk p=0.035）、方向一致。
2. **重试环的价值在语义修正不在救 SQL**：-r0 臂 VA 仅 100→99.0，
   预期的 VA 回落没发生，但净丢 11 题。
3. **叙事修正**：conv 在裸直出上 +8.65（p=0.093）——约定不依赖声明层也有效。
   三点曲线定格：plan 后 ±0 / 声明层前 +4.81 / 裸直出 +8.65。
   正确表述是"**知识的阻断器是 plan 前站**，抵达未锁死的决策点即有效"，
   不再说"知识需要声明层才能绑定"；声明层自身价值独立存在
   （direct-conv 49.04 → dsl-conv 57.69）。

预测/结果文件已按骨架归档（`predictions/{dsl,direct}/`、`results/{dsl,direct}/`）。
**下一步**：LOO 轴收档；待补实验回到 ABLATION §7（终配置 en_train 复验、
非 thinking 网格、多骨干）。

## BIRD 跑分线（2026-07-26 重整，第二次会话）

**结果与口径的唯一出口是 `docs/BIRD.md`**，此处只记决策与踩过的坑。

**路线（用户拍板）**：不再"把 BIRD 的资料都接进来备用"，改成**单一目标：跟主榜可比**。
提示词逐字复刻官方 baseline，评测直接跑官方脚本，只测一次。

**数据版本（本次会话反复了两轮，结论务必记住）**：**计分用 `dev_20251106`**
（HuggingFace `birdsql/bird_sql_dev_20251106`，sha256 `ffd8018378dd…03feb`），
因为对齐的是 `DeepSeek-R1 (Baseline)` Dev **61.67** 那一行——它在
Single Trained Model 赛道、单候选、reasoning 骨干，与本档位形态一致（用户确认 R1 用的
就是 20251106）。另一版 `dev_20240627`（sha256 `630272f2…2f06`）是**主榜 EX 表**
那些行用的（GPT-4 46.35、DeepSeek 56.13、AskData + GPT-4o 77.64），也留在
`data/bird/official/` 备查。

**两版不可互比**：题号一一对应、库相同，但 182 题问题被改写、450 条 gold SQL 被改、
gold 平均长度 161→278、challenging 145→231，dev-1106 明显更难。`bird/paths.py` 用
`DevVersion` 把两版的 sha256 都钉死，`SCORING` 指向计分那版；`fetch` 校验不过报错，
`convert` 发现本地哈希不符也拒绝转换，测试里另有一条红线断言转换产物是计分那版
（`challenging == 231`）。**踩过的坑**：换版不会报错，只会悄悄给出不可比的分数。

**`bird/` 重整**（原 762 行 7 文件 → 现在职责单一）：
`paths`（位置 + 版本哈希）/ `dataset`（fetch + convert）/ `official`（**官方 baseline
提示词，唯一知道它长什么样的地方**）/ `official_eval/`（原样 vendor 的官方
`evaluation.py` + 输入输出适配器 + SOURCE.md）/ `evaluate`（同口径的本项目实现）/
`scores`（results → markdown 表）/ `extras`（列描述、外键等**非官方**资料，
标注清楚且不进默认导出）。删掉：`prompt.py`（并入 extras）、tied 全部代码路径
（新旧官方脚本都不读 `dev_tied_append.json`）。

**评测：官方脚本当裁判**。官方 EX 就是 `set(pred)==set(gold)` 一句，没有并列处理
（用户引到过"官方对 ORDER BY…LIMIT 并列做过规则调整"的说法，核对源码后不成立）。
`--official` 跑 vendor 的官方脚本报数，不加则跑本项目实现（快、只读、出逐题明细），
`--cross-check` 要求两者一致。本项目实现的超时预算已改成**两条查询共享一个 30s**，
对齐官方那一次 `func_timeout`。

**模型档位**：`model/bird.py` 的 `bird-pro-t-direct`（`MODELS` 注册在 `model/` 是铁律，
放 `bird/` 会双向 import）。单条 user 消息、无 system、不发 temperature/stop/max_tokens
（thinking 遇 `\n\n` 会被官方那套 stop 截断）。锚点 = 主榜 `DeepSeek (Baseline)` 56.13。

**断点续跑（新增，通用）**：runner 每 50 题把结果追加进
`predictions/*.partial.jsonl`，重跑同一条命令自动跳过已完成的题，指纹（模型名+题量）
对不上就忽略断点重跑。1534 题 × thinking 要跑 2–4 小时，之前崩一次就全丢。

**下一步**：① `--gold-as-pred --cross-check` 钉死天花板并验证两套实现一致；
② 10 题冒烟量真实成本；③ 用户跑全量；④ 数字进 `docs/BIRD.md`。

## BIRD 适配层（2026-07-26 立项并完成，已被上一节重整）

设计 `docs/superpowers/specs/2026-07-26-bird-adapter-design.md`、
计划 `docs/superpowers/plans/2026-07-26-bird-adapter.md`（两者都在 gitignore 的 docs/ 下）。

**范围红线（用户拍板）**：这一层**只做数据加载与评测**，`model/`、`model/pipeline/`
的模型逻辑与提示词模板一个字不改，不注册任何 `bird-*` 档位。

**模块边界**：BIRD 专属逻辑全部收进顶层 `bird/` 包——`paths.py`（唯一知道官方包目录
布局的地方）、`convert.py`、`extras.py`、`prompt.py`、`evaluate.py`、`__main__.py`。
对外只在 `config.py` 加 `DATASETS["bird_dev"]` + `DATASET_DB_DIRS` + `db_dir_for()`。
**不把 BIRD 的库拷进 `database/`**：两边都有 `formula_1` 且内容不同（13 表 vs 14 表），
混在一个目录里会悄悄串库。

入口不再硬编码 `config.DB_DIR`，改走 `config.db_dir_for(<数据集>)`（`model/__main__.py`
×3、`model/prompts.py` ×2、`model/pipeline/__main__.py` ×1、`archer_eval/__main__.py` ×1、
`scripts/check_databases.py`）。**Archer 侧逐字节不变**——`db_dir_for("en_dev")` 回落
`DB_DIR`，有测试锁死，且有一条源码级红线测试禁止这四个入口再出现 `config.DB_DIR`。

**评测用 BIRD 自己那套口径**（用户拍板），不复用 archer_eval 的 VA/EX/SIM：
判对 = `set(pred_rows) == set(gold_rows)`（行序无关、列序有关、重复行折叠），
异常/超时判 0，报 simple/moderate/challenging/total 四档。
**两处有意偏离官方脚本，写进每份报告的 `meta.deviations`**：① 只读连接（官方用可写
connect；差异只可能出现在写操作预测上，那本来就该判 0）；② 超时用 `archer_eval`
的 progress handler 而非 `func_timeout`（同样 30s、同样判 0，不引新依赖）。
**`tied_sql` 默认关**——已核对官方 `evaluation.py` 根本不读 `dev_tied_append.json`；
`--tied` 是本项目的非官方宽松复判，打印与报告都标注 "NOT the official number"。

**额外资料 → 提示词函数**（`bird/prompt.py`，五个纯函数）：`evidence_block` /
`column_descriptions_block` / `data_format_block` / `schema_meta_block` / `extras_block`。
**约定：无副作用、无内容返回空串、绝不隐式注入**，用不用由调用方决定。
这条约定同时解决了 evidence 的口径冲突——BIRD 官方协议把 evidence 当输入，
与 Archer 侧"主实验 w/o knowledge"相反，纯函数 + 默认不注入两边都满足。

数据源实测（`bird/extras.py` 的容错都由此而来，改动前先看 `tests/test_bird.py`）：
75 个描述 CSV 与库内表 **75/75** 大小写不敏感全覆盖，列 **798/798** 能匹配到 CSV 行，
其中 **652** 列有 `column_description`、**278** 列有 `value_description`；
**4 个 CSV 不是 UTF-8**（latin-1 回退）、**1 个 CSV 表头多一个空列名**；
`dev_tables.json` 另给 11 库共 **102** 对外键——外键是现有 schema 提示词
（DDL + 3 行样本）完全没有的增量。

**健全性实测（2026-07-26，`python -m bird eval --gold-as-pred`）**：
`bird_dev` **EX 99.87%（1532/1534）**——simple 925 题 100.00 / moderate 464 题 99.78 /
challenging 145 题 99.31。两道失败题是 **#518（card_games）** 与 **#701
（codebase_community）**，报错均为 `OperationalError: interrupted`（30s 超时被
progress handler 掐断），与 2026-07-25 记录的诊断逐条吻合。**bird_dev 官方口径的
EX 天花板即 99.87%**，报数按 1534 分母，不必特殊处理。报告落在
`results/bird/bird_dev_gold.json`。

**遗留待办**：① `evidence` 相当于白送外部知识，做知识类消融时需要统一屏蔽开关
（现在靠调用方自觉不调 `evidence_block`）；② `analysis/server.py` 仍写死
`config.DB_DIR`，BIRD 的 run 在审查页看不到 schema；③ 未实现官方第二指标 VES
（需每题重复计时，成本高且与本项目论点无关）。

## RSL-SQL few-shot 可行性核查（2026-07-27）

**最新 BIRD 实测**（官方脚本，dev-1106，n=1534）：
`bird-pro-t-direct` 57.37（880/1534）→ `bird-pro-t-dsl` 60.76
（932/1534），净增 **+3.39 EX**；分档为 simple 70.70、moderate 57.79、
challenging 29.44。`docs/BIRD.md` 已同步。

核查论文 `docs/2411.00073v2.pdf` 与上游仓库
`Laqcce-cao/RSL-SQL`（本次查看 commit
`fb1dcf02923e5fd89171cc6cfe1ae3e4e5bc3b94`）后确认：

- few-shot 与 RSL-SQL 其余组件**无运行时耦合**。它只从训练集抽取
  `(question, gold SQL)`，用本地 `all-mpnet-base-v2` 生成问题向量，按欧氏距离
  取 top-k（README/论文默认 k=3），再格式化成提示词文本。
- 上游实现是离线脚本链：
  `construct_QA.py` → `get_example_modules.py` → `slg_main.py` →
  `add_example.py`；示例随后被重复注入 SQL1、SQL2、二选一与纠错阶段。
- 上游 `EuclideanDistanceQuestionMaskSelector` 名字虽有 Mask，实际没有遮蔽实体或
  数值，`mask_token/value_token` 也未使用；本质是原始问题的语义近邻检索。
- 论文在旧版 BIRD dev 上报告 DeepSeek 加 few-shot 由 42.96→55.48
  （+12.52 EX），但该数据难度分布（925/464/145）与本项目 dev-1106
  （860/443/231）不同，且基础提示词/模型也不同，**不能把 +12.52 当成本项目预期增益**。

**可行性结论：可行，抽取本身容易，多数据集工程属中等难度。** 推荐做成独立
`FewShotSelector`：每个数据集单独登记 train corpus 与向量索引，运行时只返回
结构化 examples/渲染文本；direct 与 DSL 通过显式开关消费，关闭时消息逐字节不变。
Archer en/zh 与 BIRD 不混用同一个 corpus；zh 需要多语言向量模型。评测 train 时必须
做 leave-one-out/样本 ID 排除，防止把目标题自己的 gold SQL 检索回来。

主要风险不是检索代码，而是 **DSL 输出格式不匹配**：RSL 示例只有
`question + SQL`，本项目 DSL 要输出 `SQL + declarations` JSON。第一轮建议把示例明确
标成“仅供 SQL 语义参考”，保持目标输出协议不变；若 JSON 解析率或修复轮数恶化，
再离线给训练 SQL 生成声明表，做 DSL 同格式示例。推荐消融矩阵为
`direct / direct+FS / DSL / DSL+FS`，先在小规模分层样本上验方向，再决定是否跑满
BIRD 1534 题。当前只完成研究与评估，尚未实现。用户已确认理解并要求进入任务规划；
完整执行计划写在
`docs/superpowers/plans/2026-07-27-few-shot-retrieval.md`。计划冻结第一阶段为英文
RSL 原样复现（本地 all-mpnet-base-v2、欧氏距离、k=3、无 Flash 重排），中文、
DSL 同格式示例与 Flash 重排均在四格结果后另开计划。

## 决策记录

- 2026-07-26 · **BIRD 适配独立成 `bird/` 包，评测用官方口径**（用户拍板）：
  历史上有过一版适配（`test` 分支 commit `9c50023`）把改动散在 17 个文件里，本次
  重做就是为了把 BIRD 逻辑与 Archer 主线解耦。评测不复用 archer_eval——用户原话
  "肯定得用 bird 自己的那套评测工具"，故另实现官方 `set(rows)` 口径 + 难度分层，
  两套指标各自独立报数、不并排。范围严格限定在数据加载与评测，模型/pipeline 不动。
- 2026-07-26 · **修 `.gitignore` 的裸 `bird` 模式为 `data/bird/`**：commit ee5d227
  加的 `bird` 本意是忽略数据集，但裸模式会连顶层源码包 `bird/` 一起吞掉
  （首次提交时被拦下才发现）。改成 `data/bird/` 后数据集仍被忽略、源码正常入库。


- 2026-07-23 · **路线 A（约定＝知识）升格为主线，M3-d 成为唯一活跃消融轴**（用户拍板）：
  依据三条——① OraPlan 消融中 guidelines 值 +27.9 EX（44.23→72.12，量级参照，
  非直接采用其内容，M1 已否决抄附录 5.1）；② 真知 NL2KE 架构主张"知识＝带定义的
  词表＋强制绑定"，与本项目 CK 审计一致；③ train `commonsense_knowledge` 133 条
  错题相关知识里 97 条模型本来就会——真正的增量集中在"规定值/口径约定"这一类
  （见上）。同时 **画像前置注入（m3a/m3b）判负收档**：dev 实测 −2.9/−1.9 分（相对基线
  45.19），McNemar p≥0.65 落在噪声区，且有因果实锤——#4/#5 两题模型在
  `considered` 字段承认看到画像知识却仍判 `displaced=false`，即"给了知识不强制
  用＝漏"。m3c 得 49.04（+3.85 vs 基线 45.19），但在噪声区间（McNemar p≈0.45）
  不下正结论，其 C5b/C6 检查器机制并入 M3-d 强制臂的 C7 以更高功效复验。
  这正反证了路线 A 要求"约定必须配强制表态/执行"的设计（C7 检查器 + m3dc 双臂）。
  注册项（m3a/b/c）保留作对照，不再投入新工作。
- 2026-07-23 · **知识层吸收 train 的 `commonsense_knowledge`（48 条去重口径）**（用户拍板）：
  PROGRESS 已记录禁的是用 dev 的字段，从 train 蒸馏是合法路线；48 条全部复用 ≥2 次、
  零单例，说明是通用口径不是逐题答案。但实测后只保留"Archer 规定值 ≠ 常识值"的少数条目
  （见上），其余是模型本来就会的，注进去等于噪声。
- 2026-07-23 · **不给 dev 库手写/生成列义注释**（用户否决后经实测确认）：train/dev/test
  三组库互不相同，产出物没有迁移价值；且实测 dev 的知识需求 0 条需要它。
- 2026-07-23 · **库画像同时注入 planner 与 dslgen**（用户纠正后改正）：
  **dev 62% 的错断在 plan 阶段**（planner 已经把锚猜错，dslgen 只能补救），
  知识必须在犯错之前到达。
  ~~曾一度只注入 dslgen，理由是"planner 冻结、保 M2−M1 可归因"——这个理由是错的~~：
  M1/M2 的数已跑完冻结，M3 是新的一支，改 M3 的 planner 动不到 M1↔M2 的对比；
  唯一失去的是"知识层纯通过声明层起作用"这句话，而它不是本项目的论点。
  实现上用 `use_profile` 开关保证关闭时 planner 消息与 M1 **逐字节相同**（有测试锁死）。
- 2026-07-23 · **不采纳论文的 schema embedding 检索**（沿用 M1 决策）：论文 §2.1 对大库
  取 top-k，Archer 单库表数少，全量 schema 更简单且不损失效果。

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
- 2026-07-25 · **接入 BIRD dev 作为第二块跑分场地**（`--data bird_dev`，1534 题 / 11 库）。
  转换脚本 `scripts/convert_bird.py`：`SQL→query`、`evidence→commonsense_knowledge`，
  `difficulty`/`question_id`/`tied_sql`（42 题的官方并列答案）进 `Sample.extras`。
  三个设计取舍：
  1. **数据库根目录改成按数据集查**（`config.DATASET_DB_DIRS` + `db_dir_for()`），不是
     把 BIRD 的库拷进 `database/`——两边都有 `formula_1` 且内容不同，混在一个目录里会
     悄悄串库；改完 `--db-dir` 不用手写，`check_databases.py` 同时校验两个根目录。
  2. **`by_difficulty` 分层按需出现**（样本带 difficulty 才加这一栏），Archer 报告的键集
     保持不变，`analysis/server.py` 和既有 results/*.json 不受影响。
  3. **`tied_sql` 只存不用**：本项目 EX 是自研实现，跟 BIRD leaderboard 口径本就不可直接
     并排；要对齐官方数字时再加"主 gold 判错后比并列答案"这一步。
  两个待办：`evidence` 相当于白送外部知识，做知识相关消融时要能屏蔽它（现在无开关）；
  `analysis/server.py` 仍写死 `config.DB_DIR`，BIRD 的 run 在审查页看不到 schema。
- 2026-07-25 · **bird_dev 健全性检查：VA/EX/SIM 均 99.87%（1534 题，`results/bird_dev_gold.json`）**。
  2 题 gold 自己跑不完，默认 30s 超时被掐断，**不是**正确性问题也不需要 tied_sql：
  - #518 card_games — 281s 能跑完（cards 表 250 MB，CTE join 无索引）。
  - #701 codebase_community — **600s 仍跑不完**。`EXPLAIN QUERY PLAN` 显示
    `SELECT MAX(Reputation) FROM users` 被编译成 co-routine 且对 posts 的每一行重跑一次：
    92k × 40k ≈ 37 亿次行读。加索引无解，是 SQLite 没物化标量子查询。
  结论：这 2 题对**任何**模型都不可得分（gold 跑不出来 → EX 恒为 0），bird_dev 的 EX 天花板
  是 99.87%，报数时按 1534 分母即可，不必特殊处理。默认超时保持 30s 不动——改它会同时
  动 Archer 的历史口径；真要放宽就跟数据库根目录一样做成按数据集查。

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
