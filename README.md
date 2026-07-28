# 运行文档

---

## 项目结构

```
.
├── config.py              # 全局配置：路径、数据集简写、超时、精度（唯一配置源）
├── requirements.txt   # openai / pydantic / sqlglot
├── data/              # Archer 数据集（en/zh 的 train/dev）
├── database/          # SQLite 库，只读，不进 git
├── model/             # 阶段一·生成：模型接口 + pipeline（plan/DSL/校验修复）
├── archer_eval/       # 阶段二·评测：VA/EX/SIM（Algorithm 1）
├── predictions/       # 两段间接口：模型生成的 SQL
├── results/           # 评测报告，可再生，不进 git
├── scripts/           # 独立工具（数据库齐全性检查等）
├── docs/              # 开发规范、进度、消融结果
└── tests/             # pytest
```



### 测试分数:

**模型**：`pro-t-dsl-conv-chk`(deepseek-v4-pro-thinking + pipeline), 使用官方指定评分方式进行测评.

| 数据集   | EX        | VA    |
| -------- | --------- | ----- |
| en_dev   | **63.46** | 100.0 |
| zh_dev   | **62.50** | 96.15 |

---

## 1. 环境(建议使用uv创建虚拟环境)

- Python **3.11+**



**全局安装依赖**

```bash
pip install -r requirements.txt
```

**使用uv安装依赖**

```
uv pip install -r requirements.txt
```



## 2. API 密钥

pipeline 调用 DeepSeek。密钥通过**环境变量**读取.

```powershell
# Windows PowerShell
$env:DEEPSEEK_API_KEY = "sk-..."
```
```bash
# Linux/macOS
export DEEPSEEK_API_KEY="sk-..."
```

评测机需要能访问 `api.deepseek.com`。



## 3. 数据库

请在项目目录下, 直接解压文件目录下的`database.zip`

解压后

```
database
├───bike_1
├───concert_singer
├───customers_and_products_contacts
├───driving_school
├───formula_1
├───hospital_1
├───riding_club
├───soccer_1
├───wine_1
│   └───.ipynb_checkpoints
└───world_1
```



## 4. 运行

**测试能否正常运行**

```shell
python -m model --model pro-t-dsl-conv-chk --data en_dev --limit 1 --eval
```

**复现 dev 分数（生成 + 评测）：**

```bash
# 在英文dev数据集上测试
python -m model --model pro-t-dsl-conv-chk --data en_dev --eval

# 在中文dev数据集上测试
python -m model --model pro-t-dsl-conv-chk --data zh_dev --eval  
```



## 4.5 BIRD 数据集

BIRD（https://bird-bench.github.io/）是第二块跑分场地，dev 集 **1534 题 / 11 库**，
适配层在 `bird/`。**完整说明见 `docs/BIRD.md`**（用哪份数据、提示词、偏离清单、分数表）。

计分用官方 **`dev-1106`** 版题目（`birdsql/bird_sql_dev_20251106`），对齐榜上
`DeepSeek-R1 (Baseline)` Dev **61.67** 那一行——reasoning 骨干、单模型、单次调用，
与本档位形态一致。另一版 `dev_20240627`（主榜那些行用的）也留着记录，两版**分数不可互比**。

### 准备（一次性）

库若已解压在 `data/bird/dev_databases/` 就跳过第 0 步。

```bash
python -m bird fetch      # 下载计分那版题目，校验 sha256
python -m bird convert    # → data/bird/dev.json，即 --data bird_dev
```

### 分批跑（推荐）

档位 `bird-pro-t-direct` = 官方 baseline 提示词 + 单次调用 + evidence。
1534 题跑满约 2–4 小时，所以分批跑，随时可停。

```bash
# 1) 冒烟 10 题，确认链路和成本
python -m model --model bird-pro-t-direct --data bird_dev --limit 10

# 2) 前 500 题
python -m model --model bird-pro-t-direct --data bird_dev --limit 500

# 3) 补完剩下的（去掉 --limit，前 500 题不重跑）
python -m model --model bird-pro-t-direct --data bird_dev

# 4) 全部跑完后算最终分数
python -m bird eval --official --cross-check \
    --pred predictions/bird-pro-t-direct_bird_dev.json
python -m bird scores
```

**跑了多少就能看多少分**：给 `bird eval` 带上跟生成时一样的 `--limit`。
比如只跑了前 10 题：

```bash
python -m bird eval --official --pred predictions/bird-pro-t-direct_bird_dev.json --limit 10
```

`--limit` 必须带——预测文件里只有 10 条，不带它会拿 1534 题去对，直接报错。

**为什么能续着跑**：结果按数据集下标写进 `predictions/*.partial.jsonl`，每 50 题落一次盘
（`--chunk` 可调，`0` 关闭）。重跑同一条命令自动跳过已完成的题，中断最多丢一块。
断点只在整个数据集跑完后才删。分几批、每批多大都随意。

### 两个评测入口

| 命令 | 用途 |
|---|---|
| `bird eval --official --pred ...` | 跑官方脚本（`bird/official_eval/` 里原样搬来的），**对外说的分数用这个** |
| `bird eval --pred ...` | 跑我们自己的实现，同一套判分规则，多写一份**逐题对错**到 `results/bird/`，用来查是哪几题错了 |
| `bird eval --cross-check --pred ...` | 两个都跑，分数必须一样，不一样退出码 1 |

> 判对 = `set(pred_rows) == set(gold_rows)`（行序无关、列序有关、重复行折叠），
> 异常/超时判 0，无 VA 概念——与 `python -m archer_eval` 的 VA/EX/SIM 是
> **两套独立指标，数字不可并排**。四条对官方的有意偏离见 `docs/BIRD.md` §3。

**天花板不是 100%**（`python -m bird eval --gold-as-pred` 可复测）：
① `#518`/`#701` 等几题 gold 自身 30s 内跑不完，官方脚本同样判 0；
② 6 条 gold 用了 `julianday('now')`（`#127 #143 #146 #158 #178 #1118`），
亚秒级抖动，任何模型都不可能稳定答对。**所以天花板是个约 99.5% 的浮动值，不是定数。**

**非官方资料**：列描述 CSV、外键等在 `bird/extras.py`，官方 baseline 不用它们，
接进 prompt 分数就不可跟榜单并排，故不进 `bird` 的默认导出。

---

## 4.6 离线 few-shot 检索

few-shot 使用 RSL-SQL 相同的 `all-mpnet-base-v2` 问题向量和欧氏距离，
默认固定选最近的 3 个训练问题。检索只在实验准备阶段运行；线上生成只读取
已经落盘的选择 JSON，因此不需要加载 Torch。

重依赖请装在单独的 Python 3.11/3.12 CPU 环境，不要装进本项目的 Python 3.13
环境：

```powershell
py -3.12 -m venv ..\.venv-ustc-fewshot
..\.venv-ustc-fewshot\Scripts\python.exe -m pip install -r requirements-fewshot.txt
```

Archer 英文训练集转 corpus、检索 dev、审计：

```powershell
..\.venv-ustc-fewshot\Scripts\python.exe scripts\build_fewshot.py corpus `
  --input data\en_data\train.json `
  --format archer-json `
  --name archer_en_train `
  --output data\fewshot\corpora\archer_en_train.json

..\.venv-ustc-fewshot\Scripts\python.exe scripts\build_fewshot.py select `
  --corpus data\fewshot\corpora\archer_en_train.json `
  --targets data\en_data\dev.json `
  --target-format archer-json `
  --encoder data\fewshot\models\all-mpnet-base-v2 `
  --k 3 `
  --output data\fewshot\selections\archer_en_dev_rsl_k3.json

..\.venv-ustc-fewshot\Scripts\python.exe scripts\build_fewshot.py audit `
  --selection data\fewshot\selections\archer_en_dev_rsl_k3.json
```

BIRD 训练 Parquet 转 corpus 后，用同一条 `select` 命令检索；目标格式改为
`bird-json`：

```powershell
..\.venv-ustc-fewshot\Scripts\python.exe scripts\build_fewshot.py corpus `
  --input data\fewshot\raw\bird_train.parquet `
  --format bird-parquet `
  --name bird_train `
  --output data\fewshot\corpora\bird_train.json

..\.venv-ustc-fewshot\Scripts\python.exe scripts\build_fewshot.py select `
  --corpus data\fewshot\corpora\bird_train.json `
  --targets data\bird\dev.json `
  --target-format bird-json `
  --encoder data\fewshot\models\all-mpnet-base-v2 `
  --k 3 `
  --output data\fewshot\selections\bird_dev_rsl_k3.json
```

选择文件记录 encoder、corpus SHA-256、`k`、逐题近邻和距离；重复运行应产生
逐字节相同的 JSON。若 corpus 与 targets 是同一文件，目标必须带 `source_id`，
对应训练项会被强制排除，避免把答案本身作为示例。

---

## 5. 输出

```shell
# 在英文dev数据集上测试
python -m model --model pro-t-dsl-conv-chk --data en_dev --eval	

# 会输出三个文件
predictions/
	pro-t-dsl-conv-chk_en_dev.json    # json数组,对应LLM生成的每一个题目的答案
	pro-t-dsl-conv-chk_en_dev.trace.json # 记录了架构运行过程中的一些中间信息, 帮助溯源和分析
results/
	en_dev_pro-t-dsl-conv-chk.json # 经过判题系统, 评测后的反馈结果.
```



## 6. 成本估算

最终模型每题发 **1–3** 次 deepSeek-v4-pro-thinking 请求.
dev 数据集 104 题 , 每次测试,建议准备5元. 
train数据集 400+题, 每次测试,建议准备25元.



## 7. 常用指令

```bash
# 冒烟测试（跑 1 条）
python -m model --model pro-t-dsl-conv-chk --data en_dev --limit 1 --eval

# 生成 + 评测（复现 dev 分数）
python -m model --model pro-t-dsl-conv-chk --data en_dev --eval
python -m model --model pro-t-dsl-conv-chk --data zh_dev --eval

# 只生成，不评测
python -m model --model pro-t-dsl-conv-chk --data en_dev

# 对已有预测文件单独评测
python -m archer_eval --data en_dev --pred predictions/pro-t-dsl-conv-chk_en_dev.json

# 预览/导出 CT-3 prompt（第 0 题）
python -m model.prompts --data en_dev --index 0

# 预览所选 pipeline 模型实际发送的首轮消息（第 0 题，不调用 API）
python -m model.pipeline --model pro-t-dsl-fs --data en_dev --preview 0

# BIRD DSL + few-shot 的实际首轮消息（第 0 题）
python -m model.pipeline --model bird-pro-t-dsl-fs --data bird_dev --preview 0
```
