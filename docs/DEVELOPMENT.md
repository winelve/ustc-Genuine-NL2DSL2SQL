# 开发规范（必读）

本文档定义这个项目**必须遵守的结构、接口与约定**。README 只管"怎么跑"，这里管"怎么写"。

## 1. 整体结构：两段式

整个系统只有两段，中间用**预测文件**衔接，这是全项目最重要的一条边界：

```
┌─ 阶段一 · 生成（model/ 包）────────────────────────────────┐
│  data/xx.json ─→ 构造 prompt ─→ SQLGenerator.predict() ─→ │
│                        predictions/<模型名>_<数据集>.json  │
└───────────────────────────┬───────────────────────────────┘
                            │  唯一接口：预测文件（见 §3）
┌─ 阶段二 · 评测（archer_eval/ 包）──────────▼───────────────┐
│  predictions/xxx.json + database/ ─→ VA/EX (Algorithm 1)  │
│                        ─→ results/<名>.json               │
└───────────────────────────────────────────────────────────┘
```

## 2. 铁律（改代码前先读）

1. **依赖单向**：`model` 可以 import `archer_eval`；`archer_eval` **永远不准** import `model`。评测器必须能独立评测任何来源的预测文件。
2. **路径只写在一处**：所有目录路径、数据集简写、超时、精度都在根目录 `config.py`（两个包都依赖它，它不依赖任何人）。任何文件不得硬编码路径；临时改动用 CLI 参数。模型/实验专属参数不在全局 config 预留字段，等实现出现时随模型走（构造参数或 `configs/*.toml`）；密钥只走环境变量。
3. **两段只通过预测文件通信**：模型不许直接调评测内部函数改结果；评测不关心 SQL 是谁生成的。
4. **数据库是只读的**：一律用 `mode=ro` 打开（参照 `execution.py`）。任何人不得写 `database/`。
5. **提交前测试必须全绿**：`.venv\Scripts\python.exe -m pytest tests -q`。新增功能带新增测试。
6. **不进 git 的东西**：`database/`（超 100MB）、`results/`（可再生）、`*.zip`、`.venv`。见 `.gitignore` 注释。

## 3. 接口约定

### 3.1 预测文件（阶段一的输出 = 阶段二的输入）

- 位置与命名：`predictions/<模型名>_<数据集简写>.json`（如 `first_table_en_dev.json`）
- 内容：JSON 数组，**与数据集文件同顺序、同长度**；元素二选一：
  - SQL 字符串：`"SELECT name FROM singer"`
  - 对象（评测只读 `predicted_sql` 键，其余键随意）：`{"predicted_sql": "...", "model": "gpt-4"}`
- 生成失败的条目放空串 `""`（评测记 VA=0），**不许缺条目**。

### 3.2 模型接口（`model/base.py` 的 `SQLGenerator`）

```python
class MyModel(SQLGenerator):
    name = "my_model"                                   # 用于文件命名

    def predict(self, sample: Sample, db_path: Path) -> str:
        prompt = build_ct3_prompt(sample, db_path)      # model/prompts.py
        sql = call_your_llm(prompt)                     # 你唯一要写的部分
        return "SELECT " + sql                          # 返回纯 SQL
```

约定：返回纯 SQL（无解释文字/markdown 栅栏）；单条失败返回 `""` 而非抛异常；
需要批量并发时覆写 `predict_all`。写完后在 `model/__init__.py` 的 `MODELS` 注册。

API 模型继承 `model/api.py` 的 `APIModel`（OpenAI 兼容 `/chat/completions`），
填类属性后在 `MODELS` 注册，运行命令与本地模型相同：

```python
class Qwen(APIModel):        # model/api.py 里加子类，再在 MODELS 注册
    name = "qwen-plus"       # 注册名 = --model 用的名字 = 预测文件名前缀
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = "qwen-plus"      # 请求体里的模型名
    key_env = "DASHSCOPE_API_KEY"   # 密钥所在环境变量
```

### 3.3 评测报告（阶段二的输出）

每次评测写一个文件 `results/<数据集>_<模型名>.json`（实现在 `archer_eval/report.py`）。
报告自描述，落盘就是一次 json dump：

- 概览：`meta` / `summary`(n, n_valid, n_match, VA, EX, SIM) /
  `by_db` / `by_reasoning_type`(A, A+C, A+H, A+C+H)，分组表都带 VA/EX/SIM
- 逐题：`samples`，与数据集同序，每条含
  `index` `db_id` `question` `reasoning_type`（原始细标签，如 `- + C H`）
  `gold_sql` `pred_sql` `valid` `match` `similarity` `sim_row` `sim_col`
  `pred_shape` `gold_shape`（`[行数, 列数]`）`pred_error` `gold_error`

**SIM（相似度）**：`metrics.py` 的 `result_similarity()`，与 Algorithm 1 同源——
行、列各取"每个向量的元素频次"签名，两侧签名多重集求 Jaccard，取平均。
判 match 的必为 1.0；预测执行失败记 0.0；行列数不同时 Jaccard 自然下降，无需特判。
用途是把"差一行"和"完全跑偏"区分开，不参与论文指标。

预测执行失败时不会再跑 gold（省一次执行），此时 `gold_shape` 为 `null`。

### 3.4 Python API（跳过 CLI 自己写脚本时用）

```python
import config
from archer_eval import load_dataset, load_predictions, evaluate, write_report

samples = load_dataset(config.DATASETS["en_dev"])
preds   = load_predictions("predictions/xxx.json", expected_len=len(samples))
report  = evaluate(samples, preds, config.DB_DIR)      # 纯函数，不落盘
write_report(report, config.RESULTS_DIR, "my_run")
```

## 4. 可用工具一览

| 命令 | 干什么 |
|---|---|
| `python -m model --model first_table --data en_dev --eval` | 跑一个已注册模型：生成预测并立刻评测 |
| `python -m archer_eval --data en_dev --pred predictions/x.json` | 评测一份已有的预测文件 |
| `python -m archer_eval --data en_dev --gold-as-pred` | 自检：gold 当预测，应得 VA=EX=100% |
| `python scripts/check_databases.py` | 检查数据集引用的库是否齐全可读 |
| `python -m model.prompts --data en_dev --index 0` | 预览/导出 CT-3 prompt |
| `python -m pytest -q` | 跑全部测试 |

`--data` 都支持简写 `en_train / en_dev / zh_train / zh_dev` 或文件路径。
首次使用先执行 `pip install -e .`（把 config 和两个包装成可导入模块）。
（命令前缀 `.venv\Scripts\python.exe`，或先激活虚拟环境。）

## 5. 目录职责速查

| 目录 | 职责 | 依赖 |
|---|---|---|
| `config.py` | 全局配置（根目录单文件） | 无 |
| `archer_eval/` | 阶段二·评测（data/execution → metrics → evaluate → report → cli） | config |
| `model/` | 阶段一·生成（base 接口 → prompts → 各模型实现 → runner） | config, archer_eval |
| `scripts/` | 独立小工具，不被任何包 import | 两个包都可用 |
| `tests/` | pytest；test_metrics（算法）、test_end_to_end（评测全流程）、test_model（生成接口） | — |
| `data/` `database/` | 输入数据（database 不进 git） | — |
| `predictions/` `results/` | 两段之间的接口文件 / 评测报告 | — |
