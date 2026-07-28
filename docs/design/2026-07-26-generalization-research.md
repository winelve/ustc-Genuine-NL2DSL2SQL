# 泛化性调研：知识闭环与纠错闭环

> 2026-07-26 · 调研文档（不含实现）。触发问题：满配 en_dev 63.46，但在 BIRD 上
> 整套 pipeline 相对裸直出净 +3 题（p=0.66，零效应）。
> 本文先用本项目已有数据把病因定死，再对照文献给出可借鉴的三条路线。

---

## 0. 结论摘要

1. **用户的两点诊断方向正确，但病因定位需要改**。不是"K1–K11 太死板"这么简单——
   是**整套架构解决的问题在 BIRD 上不存在**。我们造的是一台「约定对齐机」，
   BIRD 用 `evidence` 字段把约定直接发给模型，于是没东西可对齐。
2. **retry 不对称是结果，不是原因**：Archer 触发 43–49%，BIRD 14%。差异几乎全部
   来自「反事实假设」与「时间锚」两族检查——这两族是 Archer 的**题型专属**，
   BIRD 一题都没有。检查器不是"在 BIRD 上失灵"，是**在 BIRD 上无靶可打**。
3. **BIRD 上 +1.5 分其实是文献的正常量级**，不是我们特别差：ErrorLLM 在强 pipeline
   (OpenSearch-SQL) 上 +1.27，SQLens 平均 +3.47，MAGIC +2.61。**Archer 上的 +23
   才是异常值**，因为 Archer 把约定藏起来考。这一点对论文叙事是好事也是风险。
4. **真正该做的泛化测试不是"跑 BIRD"，是"跑 BIRD 且屏蔽 evidence"**。这是唯一
   能让本项目机制有靶子的跨库设定，且文献里有整条支线（Knowledge-to-SQL / SEED）
   专门做这件事，可直接对标。**这个格子现在是空的**（见 §6.1）。
5. 三条可借鉴路线，按与本项目距离排序：
   - **SQLens**（信号库 + 弱监督聚合 + 防过度修改的 Auditor）→ 直接替换我们
     手写 C1–C7 的架构，14 个信号里 9 个零人工规则。**首选**。
   - **MAGIC**（三 agent 从 train 错题自动产出纠错指南）→ 直接把 K1–K11 的
     人工蒸馏换成闭环归纳，且论文明确验证了跨数据集迁移。
   - **Knowledge-to-SQL / SEED**（把 evidence 变成自动生成的产物）→ 让"知识层"
     按库现场生成而非硬编码，是"不死板"的标准答案。
6. 但必须知道：**2025–2026 的 BIRD SOTA 基本不靠 self-correction**，靠
   多候选 + 训练过的选择器（CHASE-SQL 73.0）或 execution-reward RL
   （Arctic-Text2SQL-R1 68.9）。纠错闭环是我们的差异化命题，不是当前主流的胜负手——
   这要在论文里说清楚，否则会被审稿人拿 SOTA 表打。

---

## 1. 你的诊断：数据核对

### 1.1 「dev 好、train 差」——**这条不成立**

| 数据集 | 满配 `pro-t-dsl-conv-chk` | 对照 | 增益 |
|---|---:|---:|---:|
| en_dev (104) | **63.46** | `pro-t-dsl` 52.88 | +10.58 |
| en_train (414) | **59.18** | `pro-t-dsl` 52.90 | **+6.28** |

（train 数取自 `results/en_train_pro-t-dsl-conv-chk.json`，2026-07-25 跑，
PROGRESS.md 尚未记录。）

train 59.18 不是"表现不好"，且满配相对 `pro-t-dsl` 在 414 题大样本上 +6.28——
比早先 `noplan` 单步在 train 上的 +3（p=0.78 噪声）扎实得多。
**注意混杂**：K1–K11 蒸馏自 train 错题，train 上的 +6.28 含污染，只能当上界读。
但至少"dev-only 过拟合"这个说法被 train 部分证伪了。

### 1.2 「BIRD 一坨」——**这条成立，且比你说的更彻底**

BIRD dev 200 题抽样（`results/dev_s200_*.json`，2026-07-25）：

| 配置 | EX | VA |
|---|---:|---:|
| `pro-t-direct-know`（裸直出 + evidence） | 49.50 | 98.5 |
| `pro-t-dsl-conv-chk-know`（满配 + evidence） | **51.00** | 97.5 |
| `pro-t-dsl-conv-chk`（满配，无 evidence） | 42.50 | 97.5 |

逐题 McNemar（同 200 题对齐）：

```
direct+evi → full+evi :  49.50 → 51.00   +12/−9   net +3   p = 0.664   ← 零效应
full 无evi → full+evi :  42.50 → 51.00   +29/−12  net +17  p = 0.012   ← 显著
```

两个数字并排看就是全部病情：

- **我们整套 pipeline（声明层 + 校验 + 修复环 + K1–K11 + C5b/C6）在 BIRD 上值 net +3 题，
  p=0.66。** 对照 en_dev 上同一对比（`pro-t-direct` 40.38 → 满配 63.46，
  +26/−2，p≈3e-5）。同一套代码，一边 +23 分显著，一边 0 分。
- **而 BIRD 自带的 evidence 一个字段值 net +17 题，p=0.012。**
  外部知识 >> 我们的架构。

churn 也说明问题：+12/−9 意味着这套机制在 BIRD 上**修好 12 题、弄坏 9 题**，
是在制造方差而不是提升能力。

### 1.3 retry 不对称：原因查清了

从 `.trace.json` 直接统计修复轮数与触发的 issue（`predictions/*.trace.json`）：

| 数据集 | 1 轮过 | 2 轮 | 3 轮（轮尽） | 至少触发一次检查 |
|---|---:|---:|---:|---:|
| Archer en_dev (104) | 53 | 11 | **40** | **51 (49.0%)** |
| Archer en_train (414) | 234 | 65 | **115** | **180 (43.5%)** |
| BIRD dev_s200（无 evi） | 172 | 22 | 6 | 28 (14.0%) |
| BIRD dev_s200（+evi） | 177 | 19 | 4 | 23 (11.5%) |

**你的观察完全正确。但原因不是"检查器在 BIRD 上失效"，是无靶可打：**

Archer 触发榜首几乎全是同一族——

```
9×  假设 player.Rank = "'1st'" 的假设值没有出现在 SQL 里——反事实假设必须参与计算
7×  假设 wine.Price = 'Price * 1.15' ...
6×  假设 Procedures.Cost = 'Cost * 1.5' ...
6×  假设 Affiliated_With.Physician = "(SELECT ...)" ...
```

这是 C2 的反事实分支（Archer 的 H 类题型）。**BIRD 里反事实题为零**，
这一族在 BIRD 上触发 0 次。

BIRD 触发榜首则是另一幅画面：

```
11–12×  time_context.displaced=true 但没有任何输出列是 derived
 3×     输出列 'website' 的 expr 引用的列 'key' 不在 schema 的任何表里
 2×     输出列 'symptom' 的 expr 引用的列 'sym' 不在 schema 的任何表里
 1×     输出列 'avg_loans_per_account' 的 expr 引用 'subquery_count' 不在 schema
```

后三条是**检查器自身的假阳性**：模型在 SQL 里用了 CTE / 子查询别名
（`cnt`、`sym`、`key`、`subquery_count`），C3 拿 schema 去核对，当然找不到。
这不是"发现了真实存在的问题"，是白烧一轮修复。BIRD 上 28 个触发里，
这类假阳性 + `displaced` 空转占了大半。

**这正是你要的"检测出真实存在的问题"的反面教材，而且是我们自己的代码。**

### 1.4 一个白送的通用信号，我们没用

统计"合法但返回空结果集"的题（`pred_shape[0]==0`）：

| 数据集 | 判错且空集 | **判对且空集**（误报代价） |
|---|---:|---:|
| BIRD 满配（无 evi） | 13 / 115 错题 | **0** |
| BIRD 满配（+evi） | 9 / 98 | **0** |
| BIRD 裸直出（+evi） | 7 / 101 | **0** |
| Archer en_dev | 7 / 38 | 1 |
| Archer en_train | 9 / 169 | 7 |

BIRD 上空结果集是**精度 100% 的错误指示器**（0 假阳性），能覆盖 9–13% 的错题；
Archer 上精度较差（train 9 vs 7）因为 Archer 有真的该返回空集的题。
我们的 C1–C7 一个都没用执行结果，全在 SQL 文本和 schema 上做静态检查——
SQLens 把这个信号叫 *Abnormal Result*，是它 9 个零人工规则信号之一（§3.2）。

### 1.5 K1–K11 的性质审计

读 `model/pipeline/conventions.py` 逐条判：这 11 条里大部分不是"领域知识"，
是**Archer 的标注惯例（annotation convention）**。

| 条目 | 内容 | 跨库性质 |
|---|---|---|
| K1 | 缺参考时间就锚到 `strftime('%Y','now')`，禁止编年份 | **Archer 专属**。BIRD gold 多用固定日期，此条在 BIRD 上可能有害 |
| K2 | 整年龄用 `strftime` 分段式，禁 `julianday()/365.25` | 半通用，BIRD 常用更粗的年差 |
| K3 | 1 lb = 0.45 kg / 1 inch = 25 mm（明知有更精确常数也用这个） | **纯标注怪癖**，在任何真实场景和 BIRD 上都是错的 |
| K4 | "difference between A and B" ⇒ `ABS(A−B)` | Archer train 实测 39 有用 / 36 有害（近对半）；BIRD gold 常是有向减法 |
| K5 | 年 + 小数量 ⇒ `CAST(... AS INT)` 截断 | Archer 专属 |
| K6 | 反事实"若 X 为 v" ⇒ 改写匹配行，非过滤、非总量分摊 | **Archer H 题型专属**，BIRD 零适用 |
| K7 | 多快照表里实体属性 = 全历史聚合而非最新快照 | Archer soccer_1 立项；BIRD 同构表（european_football_2）口径可能相反 |
| K8 | 占比 = 单列 `100.0*part/total`，不输出中间计数 | **通用**，且与 BIRD 惯例一致 |
| K9 | 专名照库内拼写；题面给了数就用那个数 | **通用** |
| K10 | 人均 = `SUM(X)/SUM(pop)` 而非 `AVG(X/pop)` | 半通用，BIRD 有时要 AVG |
| K11 | "最高和最低……分别" ⇒ 一行宽表 | Archer 输出形态约定 |

**11 条里只有 K8/K9 明确跨库；K1/K3/K6/K11 是 Archer 标注惯例，在 BIRD 上是噪声
甚至反向知识。** 这解释了为什么"死板"——不是写得太具体，是**类别错了**：
把 per-benchmark 的标注惯例当成了 per-domain 的领域知识。

> 上表除 K4 有 train 实测数外，其余是基于 BIRD 惯例的判断，**未测量**。
> §6.1 给出验证它的实验（一跑即知）。

外部佐证：VLDB 2026 的标注质量研究报告 BIRD Mini-Dev **52.8%** 的标注错误/歧义率，
修正 100 道 dev 题后重评 16 个开源 agent，相对成绩变动 −7%~+31%、排名变动 ±9 位。
也就是说**"约定"这层东西在 benchmark 之间不但不通用，在 benchmark 内部都不自洽**。

---

## 2. 关键重构：我们造的是「约定对齐机」

把 §1 串起来，本项目的真实定位是：

> Archer 在测试时**不给** `commonsense_knowledge`，把口径/常数/输出形态的约定
> 全部藏进 gold SQL 里考。我们的声明层 + 校验 + 修复环 + K 表，本质是一台
> **把隐藏约定重新挖出来并强制执行**的机器。它在 Archer 上值 +23 分。
>
> BIRD 在测试时**逐题发** `evidence`，约定直接写在输入里。挖掘机开进已经挖好的坑，
> 于是值 +1.5 分（p=0.66）。

这个重构有三个直接推论：

1. **BIRD 常规设定（带 evidence）根本不是本项目的泛化测试场**，它测不出我们的机制。
   要测，必须**屏蔽 evidence**——那才是"约定隐藏"的跨库版本。
2. **"知识闭环"的目标应该被重写**：不是"生成更通用的 K 表"，而是
   **在测试时自动产出 BIRD 的 evidence 那种东西**。这在文献里是一条成熟支线
   （Knowledge-to-SQL、SEED），有现成对标数字。
3. **"检测器闭环"的目标也要重写**：现在的 C1–C7 是"约定违规检测器"，
   靶子随 benchmark 变。要泛化，检测器的信号必须来自
   **schema + 执行结果**（跨库恒有），而不是题型正则。

---

## 3. 文献：三条可借鉴路线

### 3.1 路线 A：知识闭环——把 K 表变成产出物

**MAGIC**（AAAI 2025，[arXiv:2406.12692](https://arxiv.org/abs/2406.12692)）——
**与我们最同构的工作，直接可抄架构。**

- 三 agent 在 **train 集失败样本**上闭环：feedback agent 拿 pred 与 gold 对比讲清错在哪 →
  correction agent 照着改 → 执行验证 → 改对了就把这条 feedback 存进记忆；
  manager 每积累 10 条成功 feedback 就归纳/更新一版**纠错指南**（guideline）。
  改不对时 manager 还会重写 agent 自己的提示词。上限 5 轮。
- **产出物形态** = 编号的常见错误提醒 + 错/对 SQL 例子 + 让模型自问的检查问题。
  ——这正是我们 K1–K11 的形态，只不过我们是手写的。
- 数字：DIN-SQL 基线 56.52 → 人类专家指南 57.76 → **MAGIC 59.13**。
  即"自动归纳的指南打败人类手写的指南"。
- 饱和曲线：0 批 56.52 → 1 批 57.4 → 5 批 58.8 → **10 批 59.13 → 39 批 59.13（平台）**。
  **100 条成功 feedback 就到顶了**。对我们意味着：闭环不需要跑满 414 题 train。
- 跨方法迁移：从 DIN-SQL 失败归纳出的指南，套到 zero-shot GPT-4 上 40.18 → **48.19（+8.01）**。
- 防过拟合：明确要求归纳数据与评测数据分离——**与本项目 train-only 红线完全一致**。

> 对本项目的意义：K1–K11 的人工蒸馏（含"证据 ≥2 题"、"≤12 条"这些手工红线）
> 可以整体换成一个可跑的归纳循环。而且 MAGIC 的记忆里存的是
> **"有效的 feedback"**（能把错 SQL 改对的那句话），比我们存"规则陈述"更可执行。

**Knowledge-to-SQL**（ACL 2024 Findings，[arXiv:2402.11517](https://arxiv.org/abs/2402.11517)）——
训一个 Data Expert LLM (DELLM) 专门产出 evidence，用执行反馈做偏好优化。
BIRD 上给 GPT-4 加 +4.69 EX。**这是"把 evidence 变成模型产物"的原型工作。**

**SEED**（[arXiv:2506.07423](https://arxiv.org/pdf/2506.07423)）——自动 evidence 生成，
**按库离线算一次、跨题复用**（与我们 `profile.py` 的定位一样，但目标是 evidence 而非事实）。
⚠️ 该 PDF 抽取质量差，具体数字待复核。

**反面证据（重要）**：XiYan 团队的自动库描述生成
（[arXiv:2502.20657](https://arxiv.org/html/2502.20657)，coarse-to-fine + fine-to-coarse 双过程）
在 BIRD 上只值 **+0.93%**。
——这与本项目 m3a/m3b 判负（画像前置注入 −2.9/−1.9）**方向一致**。
**结论：自动生成"列义/库描述"这类静态知识，收益极薄，别再往那里投入。**
知识的价值在"约定/口径"，不在"这列是什么意思"。这条我们自己已经用 CK 审计
（133 条 CK 里 97 条模型本来就会）得出过，文献独立证实。

### 3.2 路线 B：检测器闭环——**SQLens 是首选参考**

**SQLens**（[arXiv:2506.04494](https://arxiv.org/html/2506.04494v1)）——
端到端错误检测 + 修正，架构上正是我们 C1–C7 该长成的样子。

**14 个错误信号，9 个零人工规则（只需 schema 元数据 + 执行）**：

| 信号 | 机制 |
|---|---|
| Suboptimal Join Tree | Kruskal 求最小 Steiner 树，找出多余表 |
| Incorrect Join Predicate | join 条件与 PK/FK 关系比对 |
| **Empty Predicate** | **单独执行每个 WHERE 谓词，看哪个返回空** |
| **Abnormal Result** | **输出空集 / 全 NULL / 全零** |
| Incorrect Filter in Subquery | 子查询返回多行 |
| Incorrect GROUP BY | 有 GROUP BY 无聚合 |
| Unnecessary Subquery | 嵌套层数 ≥3 |
| Value Ambiguity | 离线倒排索引找语义相近的其它列 |
| Table Similarity | 按表分组找结构等价的替代列 |

另 5 个是 LLM 信号（Evidence Violation、Insufficient Evidence、Column Ambiguity、
Question-Clause Linking、LLM Self-Check）。

三个设计要点，每一个都直击我们的痛点：

1. **信号作用在子句粒度**（FROM/WHERE/SELECT/子查询），不是"这条 SQL 对不对"的二元判断。
   ——我们的 C2/C6 是整句级别，反馈太粗，模型顶不动（m3dc 实测 C7-dodge 修复转化率 0/5）。
2. **弱监督聚合**：每个信号视为一个 noisy labeling function，用生成式概率模型
   （Snorkel 式 label model）**无需 ground truth**就学出各信号的准确率与相关性，
   输出带置信度的概率标签，再训下游分类器。
   ——这是"检测器约束由框架自己总结"的**标准答案**。我们现在是人肉调
   `\brate\b` 正则（调参过程被测量纠正三次，写在 docstring 里），
   弱监督直接把"哪个信号可信、可信多少"变成学出来的参数。
3. **SQL Auditor 防过度修改**：修完之后拿原版和改版对比，选更好的那个。
   ——这正是我们缺的那一环。C7-abs train 39 有用 / 36 有害、dev 2 触发 2 有害，
   BIRD 上 +12/−9 的 churn，全是"没有 Auditor"的症状。

数字：检测 F1 **78.88**（precision 81.64 / recall 76.41），对照 LLM 自评布尔 57.43；
修正平均 +3.47 EX，**修好 50–303 题、弄坏仅 12–20 题**
（对照 Self-Reflection：修好 1–209、弄坏 11–27）。DB 类信号精度普遍 60%+，
其中 Empty Predicate 与 Incorrect Join Predicate 最稳。

**ErrorLLM**（[arXiv:2603.03742](https://arxiv.org/html/2603.03742)）——
把"检测"独立成一个训练出来的模型，12 类错误 taxonomy。

对我们最关键的两个数字：

- **静态规则检测：精度 100%，召回仅 6.5%。** ——这就是 C1–C4 的天花板，
  文献已经量好了。想靠写规则拿召回是没戏的。
- 训练数据构造有两条路，都可复用：① **AST 层规则扰动**——拿 train 的正确 SQL
  注入指定类型的错误，执行验证确实不匹配（**免标注造检测器训练集**）；
  ② LLM 给自然产生的错误预测打类型标签，只在"照标签改完能通过执行验证"时才接受。
- 明确点出我们踩的坑："当 LLM 被要求修正一条**本来就对**的 SQL 时，
  它倾向于无论如何都服从修正指令，改完反而错。"
- 数字：GPT-4o 55.87 → **66.23（+18.54）**；但在强 pipeline OpenSearch-SQL 上
  只有 **+1.27**。**骨干越强，纠错收益越薄——我们 BIRD 上的 +1.5 完全在这个规律上。**

**GBV-SQL**（[arXiv:2509.12612](https://arxiv.org/pdf/2509.12612)）——
SQL2Text 回译验证：把生成的 SQL 翻回自然语言描述，与原问题比对语义差异，
不一致就要求修正。**零人工规则、完全跨库**，是我们没有的一类信号。
相关的还有 *execution consistency* 的形式化定义
（[ACM SIGMOD 2025](https://dl.acm.org/doi/10.1145/3725271)）。

**PV-SQL**（[arXiv:2604.17653](https://arxiv.org/pdf/2604.17653)）——
数据库探针 + 规则验证的协同。⚠️ PDF 抽取质量差，摘要不可靠，需重读原文再引用。

### 3.3 路线 C：主流其实在绕开纠错（必须知道，否则论文会被打）

**CHASE-SQL**（ICLR 2025，[arXiv:2410.01943](https://arxiv.org/abs/2410.01943)）——
BIRD test **73.0%**。三种不同思路各生成候选（divide-and-conquer / 基于执行计划的 CoT /
实例感知的合成 few-shot），再用一个**微调过的二分类选择器做两两比较**、
按累积得分选最终答案。**关键：它不 self-correct，它选。**

**EvoSQL**（[arXiv:2607.20489](https://arxiv.org/html/2607.20489)，2026-07）——
generator/critic 共演化，每轮采 K=16 候选，执行接地 + critic 打分 + 记忆管理，
效用函数 `γ^(t−t')·Conf(q) + λ·log(1+N_t(q))` 兼顾时间折扣与一致性奖励。
消融：**有 critic 的共演化比纯执行反馈的自演化在 BIRD-Dev 上高 2.99–6.13 分，
弱模型上差距更大**——这是"程序级纠错框架有价值"的直接证据。
但注意：它的记忆是**题内的**（每题推理完就清空），不是跨题学习。
BIRD-Dev：Coder-3B 51.24 → 60.43；Qwen3-4B 65.19 → 66.56。
**同一机制在弱骨干上 +9.2、强骨干上 +1.4** ——又一次印证"纠错收益 ∝ 骨干弱点"。

**Arctic-Text2SQL-R1**（[arXiv:2505.20315](https://arxiv.org/abs/2505.20315)）——
GRPO + **仅执行正确性**的极简奖励，7B 拿 BIRD-dev 68.9。
论文明确说：避开脆弱的中间监督和复杂奖励整形。
——对我们是一记警告：**我们整个声明层就是"脆弱的中间监督"**。

**当前榜单量级**（2026-07）：单模型 Gemini-SQL2（Gemini 3.1 Pro）80.04；
整体榜首 AskData + GPT-4o 81.95（test）；人类 92.96。
我们 BIRD 200 题抽样 51.0（自研 EX 口径，与官方不可直接并排）。

> **论文风险提示**：直接把"我们的 pipeline"和 BIRD 榜单并排会很难看。
> 正确做法是死守 Archer 主场 + **BIRD-无 evidence** 这个受控设定，
> 论点是"隐藏约定的恢复"，不是"BIRD 刷分"。

---

## 4. 泛化性的真正难点：知识必须分三层，不是两层

PROGRESS 里现有的分层是「通用层跨库 / 库画像层每库现算」。BIRD 的数据说明
这个二分法漏了最要紧的一层：

| 层 | 内容 | 来源 | 跨库性 | 我们的现状 |
|---|---|---|---|---|
| L1 **schema 层** | 列义、表关系、值域 | 库自身，程序可算 | 每库现算 | `profile.py` 有，实测 −2.9（文献 +0.93）→ **薄，别投入** |
| L2 **领域层** | 真实世界公式、单位、同义词 | 常识 | 天然跨库 | CK 审计证明模型本来就会 → **空的** |
| L3 **语料约定层** | 标注惯例：口径取舍、输出形态、常数取值、歧义默认解 | **该语料的 gold SQL** | **不跨语料** | K1–K11 在这里，**误当成 L2 写死了** |

**L3 是 EX 分差的主要来源，而它按定义不跨语料。** 所以"通用的知识层"这个目标
本身是自相矛盾的——能通用的（L1/L2）没价值，有价值的（L3）不能通用。

**唯一的出路是把 L3 变成可归纳的**：给定一个新语料的 train 集（问题 + gold SQL），
框架自己跑一遍归纳，产出该语料的 L3 约定表。**通用的是归纳器，不是约定表。**
这正好就是 MAGIC 的形态，也正好是用户说的"由框架在训练中总结得到"。

论文里这句话可以这么写：

> 本项目不主张存在一份通用的外部知识表；我们主张 **L3 语料约定层的存在性与可归纳性**，
> 并给出一个语料无关的归纳器 + 一个语料无关的检测器骨架。
> 泛化性的检验方式是：**同一套归纳器在 Archer 与 BIRD 上各自归纳、各自受益**，
> 而不是同一张表在两个语料上都管用。

这个论点比"我们的知识表更通用"强得多，而且是可证伪的、有对照实验的。

---

## 5. 设计建议

### 5.1 知识闭环（替换手写 K 表）

```
train(问题, gold SQL)  ──► 归纳器（语料无关）
   │                        ① 跑基线，取错题
   │                        ② 对每道错题：pred vs gold 差异 → 生成一句 feedback
   │                        ③ 拿 feedback 让模型重写 → 执行验证是否转对
   │                        ④ 只留"验证有效"的 feedback（MAGIC 的关键筛选）
   │                        ⑤ 每 10 条归纳/合并成 1 版约定表（带编号）
   ▼
L3 约定表（该语料专属，自动带 train 证据计数）
```

四条相对 MAGIC 的改进，都基于我们自己踩过的坑：

1. **成本可控**：MAGIC 曲线在 100 条 feedback 处饱和。Archer train 169 错题
   （满配）足够，甚至可只跑一半。
2. **抗过拟合用我们已有的红线**：证据 ≥2 题、条目 ≤12 —— 这两条现在是人肉执行的
   `tests/test_conventions.py`，改成归纳器的**硬约束**（合并同类项时统计支持度）。
3. **产出带执行验证的转化率**，天然给每条约定一个可信度权重，供 §5.2 的聚合器用。
   现在的 K 表所有条目权重相同，这是 K3/K4（有害）与 K8/K9（有用）混在一起的原因。
4. **必须做"跨语料失效检查"**：在 Archer 上归纳出的表，在 BIRD-无evi 上跑一遍。
   预期是掉分或零效应——**这个负结果是论文里 L3 不跨语料的直接证据**，
   比现在推测 K1/K3/K6 有害要硬。

### 5.2 检测器闭环（替换手写 C1–C7 的门控）

**第一步：把信号池扩到跨库恒有的那些**（按性价比排序，前三条都很便宜）：

| 新信号 | 实现代价 | 我们的数据支持 |
|---|---|---|
| **Abnormal Result**（空集/全 NULL/全零） | 极低，执行已在做 | BIRD 上 0 假阳性、覆盖 9–13% 错题（§1.4） |
| **Empty Predicate**（逐谓词执行找空的那个） | 低，sqlglot 已在依赖 | SQLens 报为最稳信号之一，且给出子句级定位 |
| Join/PK-FK 一致性 + 多余表（Steiner 树） | 中 | BIRD 库表多、join 复杂，Archer 用不上但正好体现跨库 |
| SQL2Text 回译一致性 | 中（多一次 LLM 调用） | 零人工规则，能抓"合法但语义错"——我们 62 道错题的主体 |
| 修掉 C3 对 CTE/子查询别名的假阳性 | **低，是 bug** | BIRD 上白烧修复轮（§1.3） |

**第二步：把"哪个信号可信"变成学出来的**。最小可行版本不必上 Snorkel：

- 现在的 `scripts/measure_checks.py` 已经在算每个检查的 触发/有用/有害——
  **那就是精度估计，只是现在用来给人看、由人决定开关**。
- 改成：在 train 上自动算每个信号的精度 → 精度低于阈值的信号**自动降权/关闭**；
  精度作为反馈强度写进修复提示（"高置信问题" vs "仅供参考"）。
- 这一步就把 C7-abs 那种 39/36 的信号自动挡在门外，不需要人来"交给消融裁决"。
- 想要更强再上 label model（多信号相关性），但先做单信号精度加权即可。

**第三步：补 Auditor（防过度修改）**。这是**当前投入产出比最高的一改**：
修复轮结束后，把原 SQL 与修后 SQL 一起给模型（或用执行结果差异 + 信号是否消解）
二选一。我们有现成证据它值钱——m3dc 的 C7-dodge 五题全部顶不动，
C7-abs 把 #84 改坏；BIRD 上 −9 题全是这个机制。

**第四步（可选，成本高但是文献主流）**：多候选 + 选择器代替单候选 + 纠错
（CHASE-SQL 路线）。若时间允许，这是最可能真正抬高 BIRD 数字的一招，
但它偏离本项目的 DSL 命题，建议只作为对照臂而非主线。

### 5.3 跨库注入内容不一样的问题

这是用户明确点出的设计难点。建议的落法：

```
知识注入 = 语料无关的骨架 + 三个可插槽
  ├ L1 slot：本库画像（profile.py 现算，已实现，保持轻）
  ├ L3 slot：本语料约定表（§5.1 归纳器产出；不同语料挂不同表）
  └ 检测器 slot：信号池固定，但每个信号的权重/开关由本语料 train 精度决定（§5.2）
```

关键约定：**代码里不出现任何语料专属常量**。`conventions.py` 现在把 K1–K11
硬编码在源码里，应改成"归纳产物 = 数据文件（按语料分目录）+ 加载器"。
这样 `--data bird_dev` 自动挂 BIRD 归纳出的表，`--data en_dev` 挂 Archer 的，
且**能跑交叉实验**（Archer 表 × BIRD 数据 = L3 不跨语料的证据）。

---

## 6. 实验清单（先测量，后动手）

按"每分钱信息量"排序。前三项都是纯跑分/纯离线，不写新机制。

### 6.1 三个立刻能跑的测量（回答"病因对不对"）

| # | 实验 | 命令 | 回答什么 |
|---|---|---|---|
| E1 | 裸直出 **无 evidence** on BIRD | `--model pro-t-direct --data dev_s200` | **最重要的空格子**。有了它才能算"无 evidence 设定下我们的架构值多少分"。现在 42.5 只能跟 49.5(带evi) 比，不可比 |
| E2 | 满配 **−conv** 无 evidence | `--model pro-t-dsl-chk --data dev_s200` | K1–K11 在 BIRD 上是**有害**还是**无效**。§1.5 的推测一跑即知 |
| E3 | `measure_checks.py` 跑 BIRD trace | 离线，零 API 费 | 每个 C 在 BIRD 上的 触发/有用/有害。§1.3 已看出假阳性，需要量化 |

E1+E2 两跑 400 次调用，能把 §1、§2 的结论从"推测"变成"实测"，且直接产出
论文里最关键的那张表：**同一架构在"约定隐藏"与"约定给定"两种设定下的分差**。

### 6.2 最小改动的收益验证（写代码但很少）

| # | 改动 | 预期 |
|---|---|---|
| E4 | 修 C3 的 CTE/子查询别名假阳性 | 纯 bug 修复，BIRD 上省掉无效修复轮 |
| E5 | 加 **Abnormal Result** 信号（空集/全NULL） | BIRD 上 0 假阳性覆盖 13/115 错题；Archer 上需按 §1.4 谨慎（train 9 有用 vs 7 有害 → 建议加"题面不含否定/不存在语义"闸门后再开） |
| E6 | 加 **Auditor**（修前修后二选一） | 直接对准 BIRD 的 −9 churn 与 C7-abs 的 36 有害 |

E4–E6 都是小改动，且三者都**不引入任何语料专属知识**——是纯泛化性收益。

### 6.3 中期（真正的闭环）

| # | 内容 | 依赖 |
|---|---|---|
| E7 | §5.1 归纳器：Archer train 上自动重产 L3 表，与手写 K1–K11 对比 | 需 gold SQL（train 有） |
| E8 | 同一归纳器在 BIRD train 上产 BIRD 的 L3 表，评 BIRD-无evi | E1/E2 先做完 |
| E9 | 交叉：Archer 表 × BIRD 数据 / BIRD 表 × Archer 数据 | E7+E8 |
| E10 | §5.2 信号精度自动加权 | E3 提供精度基线 |

E7–E9 是论文的核心贡献结构：**归纳器通用、产物不通用、且交叉实验证明这一点**。
E8 若成立（BIRD 归纳出的表在 BIRD-无evi 上有效），本项目的命题就从
"我们在 Archer 上调出了 63.46"升级为"我们给出了一个语料无关的约定恢复方法"。

---

## 7. 参考文献

**知识生成/闭环**
- MAGIC: Generating Self-Correction Guideline for In-Context Text-to-SQL (AAAI 2025) — [arXiv:2406.12692](https://arxiv.org/abs/2406.12692)
- Knowledge-to-SQL: Enhancing SQL Generation with Data Expert LLM (ACL 2024 Findings) — [arXiv:2402.11517](https://arxiv.org/abs/2402.11517) · [代码](https://github.com/Rcrossmeister/Knowledge-to-SQL)
- SEED: Enhancing Text-to-SQL Performance Through Automatic Evidence Generation — [arXiv:2506.07423](https://arxiv.org/pdf/2506.07423)
- Automatic database description generation for Text-to-SQL — [arXiv:2502.20657](https://arxiv.org/html/2502.20657) · [代码](https://github.com/XGenerationLab/XiYan-DBDescGen)（**+0.93% 的负面参考**）
- Continual Learning of Domain Knowledge from Human Feedback in Text-to-SQL — [OpenReview](https://openreview.net/pdf?id=d98kSd3taW)

**错误检测/纠错**
- SQLens: An End-to-End Framework for Error Detection and Correction in Text-to-SQL — [arXiv:2506.04494](https://arxiv.org/html/2506.04494v1) ★
- ErrorLLM: Modeling SQL Errors for Text-to-SQL Refinement — [arXiv:2603.03742](https://arxiv.org/html/2603.03742) ★
- GBV-SQL: Guided Generation and SQL2Text Back-Translation Validation — [arXiv:2509.12612](https://arxiv.org/pdf/2509.12612)
- Automated Validating and Fixing of Text-to-SQL Translation with Execution Consistency (SIGMOD 2025) — [DOI](https://dl.acm.org/doi/10.1145/3725271)
- SQLCritic: Correcting Text-to-SQL Generation via Clause-wise Critic — [arXiv:2503.07996](https://arxiv.org/pdf/2503.07996)
- PV-SQL: Database Probing + Rule-based Verification — [arXiv:2604.17653](https://arxiv.org/pdf/2604.17653) ⚠️ 需重读
- Understanding, Detecting, and Repairing Real-World ICL-Based Text-to-SQL Errors — [arXiv:2501.09310](https://arxiv.org/pdf/2501.09310) ⚠️ 需重读

**候选选择 / RL / 共演化**
- CHASE-SQL: Multi-Path Reasoning and Preference Optimized Candidate Selection (ICLR 2025) — [arXiv:2410.01943](https://arxiv.org/abs/2410.01943)
- EvoSQL: Memory-Augmented Critic-Generator Co-Evolution — [arXiv:2607.20489](https://arxiv.org/html/2607.20489)
- Arctic-Text2SQL-R1: Simple Rewards, Strong Reasoning — [arXiv:2505.20315](https://arxiv.org/abs/2505.20315)
- CSC-SQL: Corrective Self-Consistency via Reinforcement Learning — [arXiv:2505.13271](https://arxiv.org/pdf/2505.13271)
- XiYan-SQL: A Multi-Generator Ensemble Framework — [arXiv:2411.08599](https://arxiv.org/html/2411.08599v1)
- OpenSearch-SQL: Dynamic Few-shot and Consistency Alignment — [arXiv:2502.14913](https://arxiv.org/pdf/2502.14913)
- Learning to Retrieve: Dual-Level Long-Term Memory for Text-to-SQL Agents — [arXiv:2606.00547](https://arxiv.org/html/2606.00547)

**benchmark 质量（L3 论点的外部支撑）**
- Pervasive Annotation Errors Break Text-to-SQL Benchmarks and Leaderboards (VLDB 2026) — [PDF](https://www.vldb.org/cidrdb/papers/2026/p5-jin.pdf) · [代码](https://github.com/uiuc-kang-lab/text_to_sql_benchmarks)
- BIRD 原始论文 (NeurIPS 2023 D&B) — [PDF](https://proceedings.neurips.cc/paper_files/paper/2023/file/83fc8fab1710363050bbd1d4b8cc0021-Paper-Datasets_and_Benchmarks.pdf)

---

## 附：本文所有本项目数字的复算方式

```bash
# BIRD / train 汇总数
python -c "import json;print(json.load(open('results/dev_s200_pro-t-dsl-conv-chk-know.json',encoding='utf-8'))['summary'])"

# 逐题翻转 + McNemar（§1.2）：加载两个 results 的 samples[i].match，同序对齐
#   b = 错→对, c = 对→错, p = 2·Σ_{k≤min(b,c)} C(b+c,k)·0.5^(b+c)，封顶 1

# 修复轮数分布与 issue 统计（§1.3）：predictions/*.trace.json
#   candidates[winner].checks.rounds → len() 即轮数，rounds[i].issues 即触发项

# 空结果集统计（§1.4）：results/*.json 的 samples[i].pred_shape[0]==0 且 valid
```
