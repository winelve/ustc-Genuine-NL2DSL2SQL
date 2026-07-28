# CHESS-IR Value Evidence 设计

日期：2026-07-28  
状态：已批准，进入实现

## 1. 目标与实验口径

在 Archer `en_dev` 与 BIRD `bird_dev` 上引入问题相关数据库值和列描述，验证
CHESS Information Retriever 的增量价值。

- BIRD 原始人工 evidence **保持开启**。若相关值被人工 evidence 覆盖而没有增益，
  结论就是该方法在本项目协议下不成立。
- 不迁移 CHESS 的 Schema Selector、Candidate Generator、Revision、Unit Tester
  或 LangGraph 多 Agent 框架。
- Direct 与 DSL 必须共用同一份逐题检索 artifact。
- 正式 SQL 生成阶段不扫描数据库、不加载 embedding 模型、不额外调用关键词 LLM；
  只读取固定 JSON。
- 预测 JSON 仍然只包含 SQL；所有检索来源、分数与 checksum 只进入 trace。

## 2. 实验臂

新增八个模型档位：

| 数据集 | 相关值 | 等预算随机值对照 |
|---|---|---|
| Archer Direct | `pro-t-direct-ve` | `pro-t-direct-ve-r` |
| Archer DSL | `pro-t-dsl-ve` | `pro-t-dsl-ve-r` |
| BIRD Direct | `bird-pro-t-direct-ve` | `bird-pro-t-direct-ve-r` |
| BIRD DSL | `bird-pro-t-dsl-ve` | `bird-pro-t-dsl-ve-r` |

`ve` = Value Evidence；`ve-r` = 相同检索列、相同描述、相同值数量、长度尽量匹配的
确定性随机值。`ve` 与 `ve-r` 的唯一差异是单元格值本身，可以隔离 value relevance。

另保留现有 baseline：

- baseline vs `ve`：完整 CHESS-IR 上下文的净效果；
- `ve-r` vs `ve`：相关值相对任意值的净效果。

为减少真实 API 测试，先跑 `ve`。只有 `ve` 相对既有 baseline 有正向信号时，
再跑 `ve-r` 做归因；否则直接判负。

## 3. 离线与在线边界

### 3.1 数据库级离线预处理

每个 SQLite 数据库只做一次：

1. 只读扫描非系统表；
2. 仅索引非主键 TEXT 列；
3. 按 CHESS 规则过滤 ID、URL、email、web、time、phone、date、address 列；
4. 按 distinct 数、总长度、平均长度过滤不适合建索引的列；
5. 对每个值建立 character 3-gram、100 permutations 的 MinHash/LSH；
6. 读取 BIRD `database_description/*.csv`；
7. 使用 `all-mpnet-base-v2` 为 column name、column description、
   value description 建本地向量。

索引写入 `data/value_evidence/indexes/<dataset>/<db_id>/`，全部 gitignored。

### 3.2 逐题关键词

使用 `deepseek-v4-flash`、thinking disabled、temperature 0、`max_tokens=256`，
输入 CHESS 原始 keyword prompt，动态字段为：

- question；
- BIRD 原始 evidence（保持开启）；
- Archer commonsense knowledge（数据有则使用，与 CHESS question+hint 契约一致）。

结果按 chunk 断点保存，最终写入：

`data/value_evidence/keywords/<dataset>.json`

预计 Archer+BIRD dev 共约 115–118 万实际 token；含重试和小规模校准预留 140 万。

### 3.3 逐题检索

对每个 keyword 复现 CHESS 核心链路：

1. keyword 本身、空格切分和 `column=value` 右值作为查询片段；
2. LSH 每个片段召回 top 10；
3. `difflib.SequenceMatcher` edit similarity `< 0.3` 的候选删除；
4. exact/substring 命中永远保留；
5. 其他候选用归一化 `all-mpnet-base-v2` cosine 过滤；
6. 每列保留接近该列最佳 edit 与 embedding 分数的候选；
7. 每列最多 3 个值，全题最多 12 个值；
8. description retrieval 对 `question + keyword` 与 `evidence + keyword`
   做精确 cosine top-k，合并后最多 8 个不同列；
9. 为每个相关值从同一 table.column 中选一个不同、长度最接近的确定性随机值。

OpenAI `text-embedding-3-small` 的 `0.6` 不能直接视为 all-mpnet 的稳定阈值。
实现将阈值写入 artifact，并提供训练集诊断接口；首版默认 `0.6`，但 exact/substring
命中不受该阈值影响。任何阈值调整只能使用 train，不准用 dev EX 调参。

最终写入：

- `data/value_evidence/selections/archer_en_dev_chess_ir.json`
- `data/value_evidence/selections/bird_dev_chess_ir.json`

## 4. Artifact 契约

selection 顶层字段：

```json
{
  "format_version": 1,
  "strategy": "chess-ir-mpnet-v1",
  "dataset": "bird_dev",
  "dataset_sha256": "...",
  "keywords_sha256": "...",
  "encoder": "sentence-transformers/all-mpnet-base-v2",
  "encoder_sha256": "...",
  "parameters": {
    "signature_size": 100,
    "n_gram": 3,
    "lsh_threshold": 0.01,
    "lsh_top_n": 10,
    "edit_threshold": 0.3,
    "embedding_threshold": 0.6,
    "max_values_per_column": 3,
    "max_values_total": 12,
    "max_context_columns": 8
  },
  "records": []
}
```

逐题 record：

```json
{
  "target_key": "sha256(db_id + question)",
  "db_id": "financial",
  "question": "...",
  "keywords": ["..."],
  "values": [
    {
      "table": "account",
      "column": "frequency",
      "value": "POPLATEK TYDNE",
      "control_value": "POPLATEK MESICNE",
      "keyword": "weekly issuance",
      "edit_similarity": 0.4,
      "embedding_similarity": 0.72
    }
  ],
  "contexts": [
    {
      "table": "account",
      "column": "frequency",
      "description": "...",
      "score": 0.81
    }
  ]
}
```

加载器必须严格校验版本、策略、有限数值、重复 target、重复 value 和字段类型；
目标题缺 record 时 fail closed，不允许退回 baseline。

## 5. Prompt 表示

VE 档位使用纯 DDL 加紧凑的检索块，不再使用每表前三行：

```text
CREATE TABLE ...

/* Retrieved database context:
- account.frequency: Frequency of account statement issuance.
  Example values: 'POPLATEK TYDNE'
*/
```

`ve-r` 使用完全相同的 DDL、description、列和条数，只替换为 `control_value`。
因此相关值与随机值的 prompt 结构和大部分 token 完全一致。

- Archer Direct 通过 `build_ct3_prompt(..., schema=...)` 注入；
- Archer/BIRD DSL 在 `PipelineContext.schema` 注入；
- BIRD Direct 在官方 DDL 与 comment block 之间插入检索块；
- BIRD evidence 仍按官方格式保留。

Baseline 在关闭 VE 时逐字节不变，且不读取任何 VE 文件。

## 6. Trace 与错误策略

每题 trace 增加 `value_evidence`：

- selection artifact 名与 SHA-256；
- strategy、encoder 与 parameters；
- mode：`relevant` 或 `random`；
- keywords；
- 实际注入的 table/column/value；
- description；
- 检索分数；
- 渲染字符数。

错误策略：

- 索引缺失：离线 CLI 明确报缺哪个 db_id；
- keyword record 缺失：检索 CLI fail closed；
- selection record 缺失：生成 fail closed；
- 无相关值：允许空 values，但仍记录 keywords/contexts；
- 无 BIRD descriptions：允许空 contexts；
- embedding 模型不可用：离线 CLI 报安装命令，不静默退回字符串排序；
- 数据库只用项目 `connect_ro()` 打开。

## 7. 验证

实现测试只覆盖风险边界，不运行真实 API：

1. CHESS 列过滤与 distinct value 提取；
2. keyword 输出解析；
3. LSH/edit/embedding 后处理与 exact 保留；
4. deterministic length-matched random control；
5. selection JSON 严格加载和缺记录 fail closed；
6. relevant/random 渲染只差值；
7. Direct/DSL/BIRD prompt 接入与 baseline 逐字节不变；
8. model 注册、trace、CLI 参数。

开发期间只运行对应测试文件；完成时按仓库约定运行一次全量
`.venv\Scripts\python.exe -m pytest -q`。

