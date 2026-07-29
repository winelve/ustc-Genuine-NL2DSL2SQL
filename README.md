# NL2DSL2SQL 运行文档

---

## 项目定位

本项目在 Archer 与 BIRD benchmark 上研究 NL2SQL。实验收尾后，最终只保留两个
确定使用的 idea：

1. **DSL**：模型在生成 SQL 的同时输出结构化声明，经规则检查和修复循环得到最终 SQL。
2. **Fixed semantic few-shot**：使用 `all-mpnet-base-v2` 对问题做语义检索，
   以欧氏距离固定选择 top-3 训练示例。

Direct generation 只作为对照。Plan、Structure Few-Shot、Value Evidence、knowledge/rules、
selector 和 DPC 等方案属于探索或负结果，不进入最终方法。

最终实验矩阵固定为：

| 模型 | DSL | Few-shot |
|---|:---:|:---:|
| Direct | — | — |
| Direct + FS | — | ✓ |
| DSL | ✓ | — |
| DSL + FS | ✓ | ✓ |

---

## 项目结构

```text
.
├── config.py                 # 路径、数据集、数据库目录和运行参数
├── requirements.txt          # 主运行环境依赖
├── requirements-fewshot.txt  # 离线语义检索依赖
├── data/
│   ├── en_data/              # Archer 英文 train/dev
│   ├── zh_data/              # Archer 中文 train/dev
│   ├── bird/                 # BIRD 数据与数据库，本地生成，不进 Git
│   └── fewshot/
│       └── selections/       # 已冻结的 semantic top-3
├── database/                 # Archer SQLite 数据库，只读，不进 Git
├── model/                    # Direct、DSL、few-shot 与公共生成框架
├── archer_eval/              # Archer VA / EX / SIM 评测
├── bird/                     # BIRD 数据适配与官方 EX 评测
├── predictions/              # 运行期 SQL 输出，不进 Git
├── results/                  # 运行期评测报告，不进 Git
├── artifacts/                # 已冻结的最终预测、trace、报告与 manifest
├── experiments/              # 探索/负结果索引
├── scripts/                  # 数据准备与检查工具
└── tests/                    # pytest
```

---

## 最终结果

### Archer `en_dev`

| 模型档位 | EX | VA | SIM |
|---|---:|---:|---:|
| `pro-t-direct` | 36.54 | 99.04 | 41.78 |
| `pro-t-direct-fs` | 44.23 | 99.04 | 48.86 |
| `pro-t-dsl` | 52.88 | 97.12 | 57.76 |
| `pro-t-dsl-fs` | **58.65** | 98.08 | **63.07** |

### BIRD `dev_20251106`

BIRD 使用官方 EX 脚本，不报告 Archer 的 VA/SIM。

| 模型档位 | EX | 正确题数 |
|---|---:|---:|
| `bird-pro-t-direct` | 57.37 | 880 / 1534 |
| `bird-pro-t-direct-fs` | 60.23 | 924 / 1534 |
| `bird-pro-t-dsl` | 60.76 | 932 / 1534 |
| `bird-pro-t-dsl-fs` | **62.58** | **960 / 1534** |

完整快照及 SHA-256 位于 `artifacts/manifest.json`。

---

## 1. 环境

建议使用 Python **3.11+** 和独立虚拟环境。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

也可以使用 uv：

```powershell
uv pip install -r requirements.txt
```

离线重建 few-shot selection 时需要单独的 Python 3.11/3.12 CPU 环境，避免把
Torch 和 SentenceTransformers 装进主运行环境：

```powershell
py -3.12 -m venv ..\.venv-ustc-fewshot
..\.venv-ustc-fewshot\Scripts\python.exe -m pip install `
  -r requirements.txt -r requirements-fewshot.txt
```

---

## 2. API 密钥

模型通过 DeepSeek 的 OpenAI-compatible API 运行，密钥只从环境变量读取。

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
```

Linux/macOS：

```bash
export DEEPSEEK_API_KEY="sk-..."
```

不要把密钥写入源码、JSON、README 或提交记录。

---

## 3. Archer 数据库

将仓库根目录的 `database.zip` 解压为：

```text
database/
├── bike_1/
├── concert_singer/
├── customers_and_products_contacts/
├── driving_school/
├── formula_1/
├── hospital_1/
├── riding_club/
├── soccer_1/
├── wine_1/
└── world_1/
```

检查数据库是否齐全：

```powershell
.\.venv\Scripts\python.exe -m scripts.check_databases
```

数据库连接必须保持只读。

---

## 4. Archer 四格实验

### 4.1 冒烟测试

以下命令会产生真实 API 调用：

```powershell
.\.venv\Scripts\python.exe -m model `
  --model pro-t-dsl-fs `
  --data en_dev `
  --limit 1 `
  --eval
```

### 4.2 完整运行

```powershell
# Direct
.\.venv\Scripts\python.exe -m model --model pro-t-direct --data en_dev --eval

# Direct + fixed semantic few-shot
.\.venv\Scripts\python.exe -m model --model pro-t-direct-fs --data en_dev --eval

# DSL
.\.venv\Scripts\python.exe -m model --model pro-t-dsl --data en_dev --eval

# DSL + fixed semantic few-shot
.\.venv\Scripts\python.exe -m model --model pro-t-dsl-fs --data en_dev --eval
```

`pro-t-*-fs` 当前冻结的是英文 `en_dev` selection。中文 few-shot 尚未建立独立的
多语言 selection，不应把英文 top-3 静默用于 `zh_dev`。

### 4.3 只评测已有预测

```powershell
.\.venv\Scripts\python.exe -m archer_eval `
  --data en_dev `
  --pred predictions\pro-t-dsl-fs_en_dev.json
```

---

## 5. BIRD 数据集

项目使用 `dev_20251106`，共 1534 题、11 个数据库。它与
`dev_20240627` 的题面、gold SQL 和难度分布不同，分数不可横比。

### 5.1 准备

如果 `data/bird/dev_databases/` 已存在，可以跳过数据库下载部分。

```powershell
# 需要先去官网下载bird的数据库,并且放在 .\data\bird\dev_databases.zip  后解压
.\.venv\Scripts\python.exe -m bird fetch
.\.venv\Scripts\python.exe -m bird convert

# 最终需要是这样的目录结构(忽略了文件)
.\data\bird
├───dev_databases
│   ├───california_schools
│   │   └───database_description
│   ├───card_games
│   │   └───database_description
│   ├───codebase_community
│   │   └───database_description
│   ├───debit_card_specializing
│   │   └───database_description
│   ├───european_football_2
│   │   └───database_description
│   ├───financial
│   │   └───database_description
│   ├───formula_1
│   │   └───database_description
│   ├───student_club
│   │   └───database_description
│   ├───superhero
│   │   └───database_description
│   ├───thrombosis_prediction
│   │   └───database_description
│   └───toxicology
│       └───database_description
└───official
```

转换后 `data/bird/dev.json` 对应 `--data bird_dev`。

### 5.2 BIRD 四格生成

1534 题运行时间较长。runner 每 50 题写入 `.partial.jsonl`，重复同一命令会自动
续跑。

```powershell
# Direct
.\.venv\Scripts\python.exe -m model --model bird-pro-t-direct --data bird_dev

# Direct + FS
.\.venv\Scripts\python.exe -m model --model bird-pro-t-direct-fs --data bird_dev

# DSL
.\.venv\Scripts\python.exe -m model --model bird-pro-t-dsl --data bird_dev

# DSL + FS
.\.venv\Scripts\python.exe -m model --model bird-pro-t-dsl-fs --data bird_dev
```

建议先给任一命令增加 `--limit 10` 做冒烟，再去掉 `--limit` 续跑全量。

---

## 6. Fixed semantic few-shot

### 6.1 已冻结 selection

仓库保留三份可直接运行的 top-3：

```text
data/fewshot/selections/
├── archer_en_dev_rsl_k3.json
├── bird_dev_rsl_k3.json
└── bird_dev_20240627_rsl_k3.json
```

当前主实验只使用前两份；旧版 BIRD 文件用于历史复现。

selection 自带：

- encoder 名称；
- corpus SHA-256；
- `k=3`；
- 每题的 target key；
- 示例问题、gold SQL、source ID 和欧氏距离。

线上生成只读取 JSON，不加载 Torch 或 SentenceTransformers。

### 6.2 审计

```powershell
.\.venv\Scripts\python.exe -m model.fewshot.offline audit `
  --selection data\fewshot\selections\archer_en_dev_rsl_k3.json

.\.venv\Scripts\python.exe -m model.fewshot.offline audit `
  --selection data\fewshot\selections\bird_dev_rsl_k3.json
```

审计必须满足：每题恰好 3 例、无重复 source ID、无 self-selection。

### 6.3 重建 Archer selection

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
```

重建后必须重新运行 audit，并与 `artifacts/manifest.json` 中的 SHA-256 比较。

---

## 7. 输出与冻结产物

运行时仍保持两段式边界：

```text
model/ → predictions/*.json → archer_eval/ 或 bird/
```

例如：

```text
predictions/
├── pro-t-dsl-fs_en_dev.json
└── pro-t-dsl-fs_en_dev.trace.json

results/
└── en_dev_pro-t-dsl-fs.json
```

`predictions/` 和 `results/` 是可再生运行目录，默认不进入 Git。最终论文四格复制到：

```text
artifacts/
├── final/archer/en_dev/
├── final/bird/dev_20251106/
├── archive/bird/dev_20240627/
└── manifest.json
```

trace 记录每题的 DSL 声明、检查/修复过程、few-shot 示例 ID、耗时与 DeepSeek
返回的 token usage。prediction JSON 始终只包含与数据集同序的 SQL 数组。

---

## 8. 测试与常用命令

提交前必须全量通过：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

其他常用命令：

```powershell
# 分组查看最终主线与探索档位
.\.venv\Scripts\python.exe -m model --list

# 不调用 API，预览 Archer DSL+FS 第 0 题的实际首轮消息
.\.venv\Scripts\python.exe -m model.pipeline `
  --model pro-t-dsl-fs --data en_dev --preview 0

# 不调用 API，预览 BIRD DSL+FS 第 0 题
.\.venv\Scripts\python.exe -m model.pipeline `
  --model bird-pro-t-dsl-fs --data bird_dev --preview 0

# 检查 Git diff 格式
git diff --check
```

探索方案的状态与代码位置见 `experiments/README.md`；其运行命令和历史结论不再放入
这份最终主线 README。
