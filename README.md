# Archer Text-to-SQL 评测框架

基于论文 *Archer: A Human-Labeled Text-to-SQL Dataset with Arithmetic, Commonsense and Hypothetical Reasoning* (EACL 2024)。评测指标 VA / EX 严格按论文附录 B 的 **Algorithm 1** 实现。

## 整体流程

整个复现工作分两个阶段，**本仓库的 `archer_eval` 包只负责阶段二**：

```
[阶段一·生成]   数据集问题 ──(你的模型: GPT / T5 / ...)──▶ predictions/xxx.json
[阶段二·评测]   predictions/xxx.json + database/ ──(archer_eval)──▶ results/xxx.{json,md}
```

## 目录结构

```
ustc/
├── data/                       # 数据集
│   ├── en_data/{train,dev}.json
│   └── zh_data/{train,dev}.json
├── database/                   # SQLite 库（不进 git，太大）：database/<db_id>/<db_id>.sqlite
├── archer_eval/                # ★ 评测框架（只做评测）
├── scripts/                    # 独立工具脚本（不属于评测包）
│   ├── check_databases.py      #   检查数据集引用的库是否齐全可读
│   └── build_prompts.py        #   阶段一用：构造 CT-3 prompt（评测不依赖）
├── tests/                      # pytest 测试
├── predictions/                # 评测输入：模型生成的 SQL（见其中 README）
└── results/                    # 评测输出：报告（不进 git，可重新生成）
```

全局配置集中在 `archer_eval/config.py`：所有目录路径、数据集简写（`en_dev` 等）、
查询超时、浮点比较精度。改路径只改这一个文件；临时覆盖用 CLI 参数（`--db-dir` 等）。

## archer_eval 包内各文件职责与依赖

按依赖顺序从下到上（每个文件只依赖它上面的）：

| 文件 | 职责 | 依赖 |
|---|---|---|
| `config.py` | 全局配置：路径、数据集简写、超时、浮点精度 | 无 |
| `data.py` | 读数据集 JSON → `Sample` 列表；读预测 JSON → SQL 列表 | 无 |
| `execution.py` | 把一条 SQL 在一个 SQLite 库上执行（只读、超时、编码容错），返回 `ExecutionResult` | 无 |
| `metrics.py` | **Algorithm 1**：比较两个执行结果是否等价（`execution_match`） | execution, config |
| `evaluate.py` | 编排：逐条样本执行预测+gold、算 VA/EX、按库/推理类型汇总成 report 字典 | data, execution, metrics |
| `report.py` | 把 report 字典落盘：`results/<名>.json`（完整）+ `<名>.md`（可读摘要+错误明细） | data |
| `__main__.py` | 命令行入口：解析参数 → load → evaluate → write_report | 以上全部 |

## 使用方法

```powershell
# 检查数据库完整性
.venv\Scripts\python.exe scripts\check_databases.py

# 自检：拿 gold SQL 当预测，应得 VA=100% EX=100%
.venv\Scripts\python.exe -m archer_eval --data en_dev --gold-as-pred

# 评测模型预测（--data 支持简写 en_train/en_dev/zh_train/zh_dev 或文件路径）
.venv\Scripts\python.exe -m archer_eval --data en_dev --pred predictions/gpt35_ct3_en_dev.json

# 跑测试
.venv\Scripts\python.exe -m pytest tests -q
```

### 输出接口（本地落盘）

每次评测在 `results/` 下写两个文件（`archer_eval.report.write_report`）：

- **`<数据集>_<预测名>.json`** — 机器可读，供脚本/画图使用：
  - `meta`：数据集、预测文件、时间戳、超时设置
  - `summary`：`n / n_valid / n_match / VA / EX`
  - `by_db`、`by_reasoning_type`：分组的 n/VA/EX
  - `samples`：每条样本的 `{index, db_id, valid, match, pred_error, gold_error}`
- **`<数据集>_<预测名>.md`** — 人读的：总分、分组表格、**每条错误样本的问题 + gold SQL + 预测 SQL + 失败原因**，直接打开看即可定位问题。

### Python API

```python
from archer_eval import load_dataset, load_predictions, evaluate, write_report
from archer_eval import config

samples = load_dataset(config.DATASETS["en_dev"])
predictions = load_predictions("predictions/xxx.json", expected_len=len(samples))
report = evaluate(samples, predictions, config.DB_DIR)
write_report(report, samples, predictions, config.RESULTS_DIR, "my_run")
```

## 评测逻辑（Algorithm 1）

- **VA**：预测 SQL 能成功执行（不管结果对错）。
- **EX**，按顺序判定：
  1. 预测 SQL 执行失败 → False；
  2. 执行结果与 gold 完全相等 → True；
  3. 行数或列数不同 → False；
  4. gold SQL 最外层含 `ORDER BY` → 比较**列的多重集合**（行序固定、容忍列排列）；
  5. 否则 → 比较每行、每列的**元素频率多重集合**（容忍行、列任意排列）。

实现细节：数据库只读打开（预测里的 DROP/DELETE 不会破坏数据）；每条查询默认 30s 超时（`config.DEFAULT_TIMEOUT_S`）；浮点按 6 位小数取整比较，吸收浮点噪声。

## 已知事项

- 发布版数据只涉及 **10 个库**（train 8 + dev 2），`database/` 已齐全；论文完整版的 16 个 train 库与 2 个 test 库未随数据发布。
- 各库目录下的 `<db_id>.db` 是 0 字节占位，框架自动选用非空的 `.sqlite`。
- 个别 gold SQL 用了 `strftime("%Y","now")`，结果随日期变化；同次评测中预测与 gold 同时执行，框架内部无影响，但与论文原始数字对比可能有细微出入。
- 论文主设定评测**不提供** `commonsense_knowledge`；`build_prompts.py --with-knowledge` 仅用于 §6.2 类分析实验。
