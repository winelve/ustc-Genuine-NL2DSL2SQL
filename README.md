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

旧版已单独注册为 `bird_dev_20240627`，并使用独立的 top-3 selection 和模型档位：

```bash
# 旧版 BIRD dev：生成
python -m model --model bird-pro-t-dsl-fs-20240627 --data bird_dev_20240627

# 旧版 BIRD dev：官方评测 + 交叉验证
python -m bird eval --official --cross-check \
    --data bird_dev_20240627 \
    --pred predictions/bird-pro-t-dsl-fs-20240627_bird_dev_20240627.json
```

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
..\.venv-ustc-fewshot\Scripts\python.exe -m pip install `
  -r requirements.txt -r requirements-fewshot.txt
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

旧版 BIRD dev 必须按旧题面重建 selection，不能复用新版文件：

```powershell
..\.venv-ustc-fewshot\Scripts\python.exe scripts\build_fewshot.py select `
  --corpus data\fewshot\corpora\bird_train.json `
  --targets data\bird\dev_20240627.json `
  --target-format bird-json `
  --encoder data\fewshot\models\all-mpnet-base-v2 `
  --k 3 `
  --output data\fewshot\selections\bird_dev_20240627_rsl_k3.json
```

选择文件记录 encoder、corpus SHA-256、`k`、逐题近邻和距离；重复运行应产生
逐字节相同的 JSON。若 corpus 与 targets 是同一文件，目标必须带 `source_id`，
对应训练项会被强制排除，避免把答案本身作为示例。

### SFS：结构感知 few-shot

SFS（Structure-aware Few-Shot）先按问题语义召回 top-30，再用一份冻结的
zero-shot Direct 草案 SQL 与候选 gold SQL 做结构匹配，最后以固定
`0.5 × semantic rank + 0.5 × structure rank` 选出 top-3。结构由 SQLite
方言的 sqlglot AST 提取；无法解析草案时严格退回原语义顺序。

Direct 与 DSL 必须共用同一份 draft 和 selection。Archer `en_dev` 的构建命令：

```powershell
..\.venv-ustc-fewshot\Scripts\python.exe -m model.fewshot.offline select `
  --corpus data\fewshot\corpora\archer_en_train.json `
  --targets data\en_data\dev.json `
  --target-format archer-json `
  --encoder data\fewshot\models\all-mpnet-base-v2 `
  --k 30 `
  --output data\fewshot\selections\archer_en_dev_rsl_k30.json

python -m model.fewshot.offline rerank-sfs `
  --selection data\fewshot\selections\archer_en_dev_rsl_k30.json `
  --targets data\en_data\dev.json `
  --draft-predictions predictions\direct\pro-t-direct_en_dev.json `
  --candidate-k 30 `
  --k 3 `
  --output data\fewshot\selections\archer_en_dev_sfs_k3.json

python -m model.fewshot.offline audit `
  --selection data\fewshot\selections\archer_en_dev_sfs_k3.json
```

先跑 10 题冒烟，确认 API、trace 和评测链路：

```powershell
# Direct + SFS
python -m model --model pro-t-direct-sfs --data en_dev --limit 10 --eval

# DSL + SFS
python -m model --model pro-t-dsl-sfs --data en_dev --limit 10 --eval
```

冒烟正常后去掉 `--limit` 跑 104 题全量；断点会自动复用已完成的前 10 题：

```powershell
# Direct + SFS 全量
python -m model --model pro-t-direct-sfs --data en_dev --eval

# DSL + SFS 全量
python -m model --model pro-t-dsl-sfs --data en_dev --eval
```

selection trace 会额外记录 target/draft/语义 selection 的 SHA-256、语义名次、
结构名次、结构相似度与融合分数。SFS artifact 与其他 few-shot 数据一样位于
`data/fewshot/`，不进入 git。

### CHESS-IR：Value Evidence

Value Evidence 按 CHESS 的离线流程准备：扫描 distinct TEXT values 并建立
character 3-gram MinHash/LSH；DeepSeek Flash（关闭 thinking）用 CHESS 原提示词
从 question + BIRD evidence 中抽关键词；LSH/edit similarity 召回后，由本地
`all-mpnet-base-v2` 过滤和排序。BIRD 的列描述也使用同一个本地模型检索。
生成阶段只读取固定 JSON，不加载 datasketch、Torch 或 SentenceTransformers。

关键词抽取覆盖 Archer `en_dev` 和 BIRD `dev` 时，预估约 **115–118 万**
DeepSeek token；建议账户至少预留 **140 万 token**。每题 usage 会写入关键词
artifact，失败题保留在 `.partial.jsonl`，原命令重跑时只补失败项。

先在独立 Python 3.11/3.12 环境准备 Archer artifact：

```powershell
# 1. 每个数据库离线建索引
..\.venv-ustc-fewshot\Scripts\python.exe -m model.value_evidence.offline index `
  --data en_dev

# 2. DeepSeek 非思考关键词；需要 $env:DEEPSEEK_API_KEY
..\.venv-ustc-fewshot\Scripts\python.exe -m model.value_evidence.offline keywords `
  --data en_dev `
  --chunk 50 `
  --concurrency 10

# 3. 本地 all-mpnet 检索并生成固定 selection
..\.venv-ustc-fewshot\Scripts\python.exe -m model.value_evidence.offline select `
  --data en_dev `
  --encoder data\fewshot\models\all-mpnet-base-v2

# 4. 严格审计
python -m model.value_evidence.offline audit `
  --data en_dev `
  --path data\value_evidence\selections\archer_en_dev_chess_ir.json
```

BIRD 使用同一套命令，只把三处 `--data en_dev` 改成 `--data bird_dev`；
审计命令的 `--data` 也改成 `bird_dev`，路径改为
`data\value_evidence\selections\bird_dev_chess_ir.json`。BIRD
官方 human evidence 始终保持开启；VE 插在 DDL 与官方 question/evidence 块之间。

artifact 准备完成后，最少先跑两个 10 题 smoke：

```powershell
python -m model --model pro-t-direct-ve --data en_dev --limit 10 --eval
python -m model --model bird-pro-t-direct-ve --data bird_dev --limit 10
python -m bird eval --official `
  --pred predictions\bird-pro-t-direct-ve_bird_dev.json `
  --limit 10
```

smoke 正常后先只跑相关值 Direct 全量：

```powershell
python -m model --model pro-t-direct-ve --data en_dev --eval
python -m model --model bird-pro-t-direct-ve --data bird_dev
python -m bird eval --official `
  --pred predictions\bird-pro-t-direct-ve_bird_dev.json
```

只有 `ve` 相对原 Direct baseline 有正向信号，才跑等数量、同列、
近似长度随机值对照 `ve-r`；只有 Direct 信号成立，才继续支付 DSL 成本：

```powershell
# 相关性对照
python -m model --model pro-t-direct-ve-r --data en_dev --eval
python -m model --model bird-pro-t-direct-ve-r --data bird_dev
python -m bird eval --official `
  --pred predictions\bird-pro-t-direct-ve-r_bird_dev.json

# DSL（条件实验）
python -m model --model pro-t-dsl-ve --data en_dev --eval
python -m model --model pro-t-dsl-ve-r --data en_dev --eval
python -m model --model bird-pro-t-dsl-ve --data bird_dev
python -m model --model bird-pro-t-dsl-ve-r --data bird_dev
```

`ve-r` 与 `ve` 共享同一 selection、列描述和 value 数量，只切换逐项
`control_value`；trace 会记录 artifact/encoder/keyword SHA-256、阈值、关键词、
相关值和实际注入值。全部 `data/value_evidence/` 产物均不进入 git。

#### VE2：严格过滤 + 追加式 Value Evidence

`pro-t-direct-ve` 的首次实验相对 baseline 下降 5 EX。复盘发现 v1 允许
substring 命中绕过 embedding/列内相对阈值，并用 DDL + retrieved values
替换了 baseline 的 CT-3 三行样例。VE2 保留 v1 结果不覆盖，并同时修正这两个
混杂因素：

- 所有候选都必须通过 embedding >= 0.6、列内 90% edit 和 90% embedding；
- 完整保留 CT-3 DDL + 三行样例，只在其后追加 retrieved context。

复用已有关键词和索引重建 VE2 selection，不调用 DeepSeek：

```powershell
..\.venv-ustc-fewshot\Scripts\python.exe -m model.value_evidence.offline select `
  --data en_dev `
  --encoder data\fewshot\models\all-mpnet-base-v2 `
  --strategy chess-ir-mpnet-v2

python -m model.value_evidence.offline audit `
  --data en_dev `
  --strategy chess-ir-mpnet-v2 `
  --path data\value_evidence\selections\archer_en_dev_chess_ir_v2.json
```

只需跑两个全量实验：

```powershell
# 严格相关值
python -m model --model pro-t-direct-ve2 --data en_dev --eval

# 同列、等数量、近似长度的随机值对照
python -m model --model pro-t-direct-ve2-r --data en_dev --eval
```

两者都以 `pro-t-direct` 为 baseline。先看 `ve2` 是否恢复/超过 baseline，
再用 `ve2 - ve2-r` 判断收益是否来自值的相关性；Direct 没有正信号时不跑 DSL/BIRD。

### DPC-1x1：低成本候选验证 Pilot

DPC pilot 不重新生成 SQL。它复用已有 BIRD Direct+FS / DSL+FS，只从上一轮
391 道真实执行分歧题中按 difficulty 分层、固定 hash 抽 80 道。DSL+FS 作为
champion；DPC 只有在 Minimal Distinguishing Database 上得到更强的独立
Pandas 证据时才切到 Direct+FS，失败或平票保持 DSL。

官方 DPC 仓库不能直接 `pip install git+...`（flat layout 会触发 setuptools
package discovery 错误），因此首次使用时检出已审查的官方 commit，再安装三个
额外依赖：

```powershell
python -m model.dpc_pilot bootstrap
python -m pip install -r requirements-dpc.txt
```

先运行不需要 API key、不会产生费用的完整链路自检。它使用脚本化回复实际执行
官方 Tester → Solver → BS-F1 → selection pipeline：

```powershell
python -m model.dpc_pilot self-test
```

预期输出包含 `winner=direct`、`Challenger Won Duel` 和
`scripted_calls=2`。

准备固定 pilot；此步不调用 API：

```powershell
python -m model.dpc_pilot prepare
```

先跑 5 题 API smoke。正常后原命令去掉 `--limit 5`，会从 checkpoint 续跑到
固定 80 题：

```powershell
# 5 题 smoke
python -m model.dpc_pilot run --limit 5

# 80 题 pilot（自动复用前 5 题）
python -m model.dpc_pilot run
```

输出是完整 1534 条预测：非 pilot 题保持 DSL+FS，pilot 题采用 DPC 选择，因此
直接使用现有 BIRD evaluator：

```powershell
python -m bird eval --data bird_dev `
  --pred predictions\bird\bird-pro-t-dpc80_bird_dev.json
```

这是低成本 `DPC-1x1`：确定性 SQL AST schema slicing（零 API）+
1 个 test data + 1 个 solver，DeepSeek 默认关闭 thinking；每题通常两次 API。
逐题耗时、调用和 token 写入 trace，生成 Python 在 AST 限制后的子进程执行。
旧版 checkpoint 缺少可靠 token/fallback 信息时会自动重跑，不需要手动删文件。
相对 DSL+FS 的 960/1534，80 题 pilot 净增至少 4 题才扩大；持平或下降立即收档。

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

每道题的 `.trace.json` 都包含 `metrics`：

- `elapsed_seconds`：该题从上下文准备到最终 SQL 的端到端耗时；
- `api_calls` / `api_elapsed_seconds`：API 调用次数与累计等待时间；
- `usage`：该题所有调用汇总后的输入、输出、总量、缓存命中/未命中及 reasoning token；
- `calls`：每次 API 调用的耗时与 token 明细。

token 数量直接读取 DeepSeek 返回的 `usage`，不做本地估算。DSL 的修复调用会计入
同一道题的汇总；API 未返回的字段记为 `null`。



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
