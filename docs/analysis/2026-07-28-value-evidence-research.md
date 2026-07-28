# Value Evidence 调研：CHESS / SEED / SQL-R1

日期：2026-07-28

## 结论先行

三篇论文讨论的并不是同一个实验变量：

- **CHESS** 最接近本项目要验证的命题：从问题中提取关键词，检索相关数据库值和
  列描述；相对“随机示例 + 全列描述”，在 subsampled BIRD dev 上提高
  **4.76 EX 百分点**。
- **SEED** 生成的是一段自然语言 evidence，不是简单挑选 sample values。
  它与“无 evidence”比较，收益依赖下游模型，BIRD dev 上从 **−0.58 到
  +17.73 EX**；论文没有提供“相关值 vs 随机值”的直接消融。
- **SQL-R1** 的 representative values 实现基本是无排序 `SELECT DISTINCT ... LIMIT N`，
  即任意/数据库顺序取值。RL 训练中加值只提高 **1.2 EX**，论文明确称该增益
  不显著，且输入变长、训练效率下降。

本仓库当前 `model/prompts.py::schema_with_rows()` 已经对每张表执行无排序
`SELECT * ... LIMIT 3`。因此 SQL-R1 式任意值基线事实上已经存在；下一步若做，
应该验证“**同等 token 预算下，问题相关值是否优于任意值**”，而不是继续多塞几行。

## 1. 消融实验对齐

### 1.1 CHESS：唯一的直接随机对照

论文模块消融（subsampled BIRD dev）：

| 设置 | EX | 相对完整系统 |
|---|---:|---:|
| 完整 CHESS | 64.62 | — |
| 去掉 entity & context retrieval | 59.86 | −4.76 |
| 去掉 individual column filtering | 61.90 | −2.72 |
| 去掉 table selection | 58.50 | −6.12 |
| 去掉 final column selection | 59.18 | −5.44 |
| 去掉 revision | 57.82 | −6.80 |

论文明确说明：去掉 entity/context retrieval 后，改为取一个**随机示例**，并给出
所有列描述。因此 64.62 对 59.86 是目前最接近“相关 evidence value vs 随机值”的
对照，相关检索净增 **4.76 个百分点**。

限制：这个消融同时去掉了 entity value retrieval 和 description/context retrieval，
不是纯 value-only 消融；而且是在 CHESS 完整多阶段系统和 subsampled dev 上得到，
不能把 4.76 直接当作本项目的预期收益。

来源：

- Paper: https://arxiv.org/abs/2405.16755
- Code: https://github.com/ShayanTalaei/CHESS

### 1.2 SEED：evidence 对无 evidence，不是随机值对照

SEED Table IV 的 BIRD dev EX：

| 下游方法 | 无 evidence | BIRD 人工 evidence | SEED-GPT | SEED-DeepSeek |
|---|---:|---:|---:|---:|
| CHESS IR+CG+UT / GPT-4o-mini | 54.69 | 63.04 (+8.35) | 56.26 (+1.57) | 54.11 (−0.58) |
| CHESS IR+SS+CG / GPT-4o-mini | 49.61 | 60.43 (+10.82) | 54.82 (+5.21) | 53.65 (+4.04) |
| RSL-SQL / GPT-4o | 54.50 | 65.78 (+11.28) | 58.28 (+3.78) | 58.15 (+3.65) |
| CodeS-15B | 44.39 | 55.35 (+10.96) | 56.78 (+12.39) | 57.69 (+13.30) |
| CodeS-7B | 41.92 | 54.76 (+12.84) | 56.52 (+14.60) | 56.58 (+14.66) |
| DAIL-SQL / GPT-4 | 35.46 | 56.32 (+20.86) | 51.63 (+16.17) | 53.19 (+17.73) |

可得出的可靠结论：

- 正确 evidence 很有价值：人工 evidence 相对无 evidence 提高
  **8.35–20.86 EX**。
- 自动 evidence 不保证提升：SEED 相对无 evidence从 **−0.58 到 +17.73 EX**，
  与下游 prompt/模型强相关。
- evidence 的正确性很重要：论文在 105 条错误 BIRD evidence 上修正后，
  CodeS-1B/3B/7B/15B 分别提高 **9.53 / 7.62 / 10.48 / 9.53 EX**。
- SEED-DeepSeek 在 CHESS IR+CG+UT 上反而 −0.58；论文归因之一是 evidence 格式
  携带了不适合该下游系统的 join 信息。这说明 evidence 不是越丰富越好。

论文没有随机值基线，所以不能用这张表回答“相关值比随机值高多少”。

来源：

- Paper: https://arxiv.org/abs/2506.07423
- Code: https://github.com/felix01189/SEED

### 1.3 SQL-R1：任意 representative values 的反例

SQL-R1 Table 9（BIRD dev，RL training）：

| 设置 | EX |
|---|---:|
| Qwen2.5-Coder-7B base | 58.2 |
| SQL-R1，训练不加数据库值 | 61.9 |
| SQL-R1，训练加入数据库值 | 63.1 |

同一 SQL-R1 训练设置中，数据库值只带来 **+1.2 EX**。论文明确说提升不具统计显著性，
同时增大输入长度、降低训练效率，所以最终训练阶段放弃 representative value
annotations。

注意：这是 **RL 训练时有/无值**，不是推理时的相关值检索实验，不能与 CHESS 的
4.76 直接横比；它只能支持“任意塞值性价比不高”这一谨慎结论。

来源：

- Paper: https://arxiv.org/abs/2504.08600
- Code: https://github.com/DataArcTech/SQL-R1

## 2. 官方代码实现与迁移难度

### 2.1 CHESS

官方实现链路：

1. 离线扫描数据库中的 distinct TEXT values，过滤主键、ID/URL/email/date/address
   等列和过长/过多值。
2. 对字符串构造 character 3-gram MinHash/LSH，并按数据库持久化 pickle 索引。
3. LLM 从 question + hint 中抽取关键词。
4. LSH 召回候选值，先用 edit similarity（阈值 0.3），再用
   `text-embedding-3-small`（阈值 0.6）过滤；每列保留接近该列最佳分的候选。
5. 另建列描述向量库，为关键词检索相关 catalog descriptions。
6. 将值作为 `Example Values`、描述作为 column context 注入 schema。

关键文件：

- `src/database_utils/db_values/preprocess.py`
- `src/database_utils/db_values/search.py`
- `src/workflow/agents/information_retriever/tool_kit/extract_keywords.py`
- `src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py`
- `src/workflow/agents/information_retriever/tool_kit/retrieve_context.py`

迁移判断：

- **完整迁移：高难度。** 需要 `datasketch`、离线索引、embedding/vector DB、
  额外关键词 LLM 调用、描述文件管线，并且 CHESS 原仓库是多 agent 框架。
- **CHESS-lite：低到中等难度。** Archer dev 只有两个小库，不需要 LSH/vector DB。
  可以只读扫描 distinct text values，用问题中的字符串/数字候选做 exact、substring、
  edit similarity，最后每题固定 top values。它能复用本仓库统一的 schema 构造入口。

### 2.2 SEED

官方 `make_evidence.py` 基本是一个完整的离线 evidence 生成系统：

1. 从 schema、CSV descriptions 和数据库中采样列值；目标库每列最多 30 个，
   few-shot 示例库每列 3 个。
2. 用 `all-mpnet-base-v2` 找最相近的 BIRD train question，再补同库相关问题，
   把它们的人工 evidence 当生成示例。
3. LLM 抽取 question 中的 schema-value pairs。
4. 执行探索 SQL：distinct samples、Jaro-Winkler 最近值、`LIKE '%value%'` 候选。
5. 再调用 LLM，把 schema、训练 evidence 示例和探索 SQL 结果压成自然语言 evidence。
6. DeepSeek 长度受限配置还会增加 schema summarization 调用。

迁移判断：

- **完整迁移：高难度、高成本。** 每题约增加 3–4 次 LLM 调用；依赖 BIRD train
  的人工 evidence 作为 few-shot target，而 Archer train 没有这个字段；其密钥、
  SQLite 打开方式、硬编码模型和输出协议也都不符合本仓库约定。
- **仅迁移“探索 SQL”子步骤：中等难度。** 候选短语确定后，用只读 SQL 获取 distinct、
  LIKE 和最近值是可复用部分；自然语言 evidence 生成不应作为第一步。

### 2.3 SQL-R1

`sample_table_values()` 对每列执行：

```sql
SELECT column
FROM (
  SELECT DISTINCT column
  FROM table
  WHERE column IS NOT NULL AND column != ''
)
LIMIT N;
```

没有 `ORDER BY`，所以是任意/数据库顺序样本。代码虽然支持合并 question-relevant
hits，但实际 `get_input_seq()` 路径传入 `db_id2relevant_hits=None`，最终主要使用
缓存的 representative values。

迁移判断：**几乎零难度，但没有迁移价值。** 本仓库当前每表前三行已经提供同类任意值，
且通常比 SQL-R1 的每列少量值占用更多 token。它适合作为 control，不适合作为新方法。

## 3. 与当前仓库的接入判断

统一接入点已经存在：

- `model/prompts.py::schema_with_rows()` 负责 Direct prompt；
- `model/pipeline/models.py` 也调用同一个函数准备 pipeline context；
- 因而 Direct / DSL 可以共用同一份 value-selection artifact，不需要分别实现。

最小可行研究变量应是：

- control：当前无排序 `LIMIT 3`，或固定 seed 的任意值；
- treatment：question-relevant values；
- 两组保持相同的 value 数量或近似 token 预算；
- 只改变 value selection，不同时增加列描述、额外 few-shot 或自然语言 evidence；
- selection 固定落盘并进 trace，避免运行时随机性掩盖差异。

这会把 CHESS 的核心价值检索思想迁过来，同时避开 CHESS/SEED 的多 agent、
额外 LLM 和向量基础设施。是否进入实现、具体选哪一组实验臂，等待讨论后再定。
