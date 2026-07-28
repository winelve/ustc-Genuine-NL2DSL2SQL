# BIRD 跑分（NL2DSL2SQL 泛化性第二场地）

> BIRD 侧的**结果视图**：用哪份数据、提示词长什么样、偏离了官方什么、分数是多少。
> Archer 侧的消融结果在 `docs/ABLATION.md`，两套指标**不可并排**（见 §5）。
>
> 最后更新：2026-07-27

---

## 1. 用哪份数据：`dev-1106`（对齐 DeepSeek-R1 那一行）

BIRD 清洗过多次 dev。**两版题号一一对应、库完全相同**，只换题目文件就能切换——
所以搞错了不会报错，只会悄悄得到一个不可比的分数。两版分别对应榜单的两条线：

| 版本 | 规模 | 榜单上谁在用 |
|---|---|---|
| **`dev_20251106`（本项目计分用）** | simple 860 / moderate 443 / challenging 231，1377 题带 evidence | **`DeepSeek-R1 (Baseline)` Dev 61.67 / Test 60.93**（Single Trained Model 赛道，标 "New Dev"） |
| `dev_20240627` | simple 925 / moderate 464 / challenging 145，1386 题带 evidence | 主榜 EX 表：GPT-4 46.35、DeepSeek 56.13、AskData + GPT-4o 77.64 |

计分用 dev-1106，因为 `DeepSeek-R1 (Baseline)` 是榜上**与我们形态最接近**的一行：
reasoning 骨干 + 单模型 + 单次调用（Self Consistency 空 = 单候选）+ 给 evidence。

| | 来源 | 字节 | sha256 |
|---|---|---:|---|
| `dev_20251106` | HuggingFace `birdsql/bird_sql_dev_20251106` | 946,793 | `ffd8018378ddb1a8794753e0a31cfc81862ff7318a5184c22f3dc4ce03a03feb` |
| `dev_20240627` | 官网 `dev.zip` 内 `dev_20240627/dev.json` | 741,332 | `630272f2b1c44d8cef2c3b246f623355cf0bbc1e832c81061df895530dfc2f06` |

### ⚠️ 两版分数不可互比

逐题比对实测：**182 题问题被改写**（`question_id=0` 从 simple 的单值查询变成带 CTE
的多列题）、**450 条 gold SQL 被改**、gold 平均长度 **161 → 278 字符**、
challenging **145 → 231**。**dev-1106 明显更难**。

所以：我们的数只跟 **61.67** 比；主榜那些行（56.13 / 46.35 / 77.64）是在
`dev_20240627` 上跑的，**不能**跟我们的数并排。

### 版本钉死

`bird/paths.py` 把两版的 sha256 都记着，`SCORING` 指向计分那版。`fetch` 校验不过
直接报错，`convert` 发现本地文件哈希对不上也拒绝转换——不钉死就会出现
"拿另一份考卷的分数跟榜单并排"。两份原件都留在 `data/bird/official/`。

运行时别名也显式分开：`bird_dev` 指向 `dev_20251106`，旧版
`dev_20240627` 指向 `bird_dev_20240627`。旧版 fixed few-shot 使用独立档位
`bird-pro-t-dsl-fs-20240627` 和 selection
`bird_dev_20240627_rsl_k3.json`，不复用新版题面生成的 top-3。

---

## 2. 提示词：官方 baseline 逐字复刻

实现在 `bird/official.py`，对着 `bird-bench/mini_dev` 的 `llm/src/{table_schema,prompt}.py`
复刻（`python -m bird preview --index 0` 看实际发出去的东西）：

```
<全库 CREATE TABLE DDL，"\n\n" 连接>

-- Using valid SQLite and understanding External Knowledge, answer the following questions for the tables provided above.
-- {question}
-- External Knowledge: {evidence}

Generate the SQLite for the above question after thinking step by step:

In your response, you do not need to mention your intermediate steps. ...
You only need to return the result SQLite SQL code start from SELECT
```

**官方不给的，我们一样不给**（有测试锁死，见 `test_official_prompt_carries_no_unofficial_material`）：

| 资料 | 官方 baseline | 依据 |
|---|---|---|
| evidence（外部知识） | **给** | `use_knowledge='True'`；主榜 Oracle Knowledge 列全 ✔️ |
| 全量 CREATE TABLE DDL | **给** | `generate_schema_prompt_sqlite`，不做 schema 检索/裁剪 |
| 每表样本行 | 不给 | `num_rows` 不传 → `None` → 走不进那个分支 |
| `database_description/*.csv` 列描述 | 不给 | 只读 `sqlite_master`，从不打开 CSV |
| 外键 / `dev_tables.json` | 不给 | 同上 |
| few-shot 例子 | 不给 | 源码里 `few_shot()` 是注释掉的 |
| system message | 不给 | `messages=[{"role": "user", ...}]` 只有一条 |

列描述与外键的读取/渲染函数留在 `bird/extras.py`，**标注为非官方**、不进默认导出，
供将来做"多给资料值多少分"的消融——那种数不可跟榜单并排。

---

## 3. 评测：官方脚本当裁判

官方 EX 的全部判分逻辑就是一句 `set(predicted_res) == set(ground_truth_res)`。
**没有 ORDER BY/LIMIT 并列处理，也没有并列 gold 复判**——官方包里的
`dev_tied_append.json` 两个官方脚本都没读过，所以本项目也不留这条支路。

| 入口 | 用途 |
|---|---|
| `python -m bird eval --official --pred …` | **报数用这个**。跑 `bird/official_eval/evaluation.py`（原样 vendor，来源见 `SOURCE.md`），子进程调用 |
| `python -m bird eval --pred …` | 日常用：同口径的本项目实现，快、只读、出逐题明细与 by_db |
| `python -m bird eval --cross-check --pred …` | 两套都跑，总分必须一致；不一致退出码 1 |

### 四条对官方的偏离（也写进每份报告的 `meta.deviations`）

| # | 偏离 | 理由 |
|---|---|---|
| 1 | 只读连接 | 项目铁律；官方用可写 connect，对 SELECT 无差别，写操作预测本来就该判 0 |
| 2 | 超时用 sqlite progress handler | 不引新依赖；**预算口径已对齐**——官方那一次 `func_timeout(30)` 罩着"预测 + gold"两条，我们也让两条共享一个 30s |
| 3 | 空预测直接判 0 | 官方会把空串交给 sqlite（返回空结果集，可能与空 gold 意外相等）；生成失败不该有机会蒙对 |
| 4 | 不发 `stop` / `max_tokens` / `temperature` | 官方 `stop=["--","\n\n",";","#"]` + `max_tokens=512` 是给 completion 式短输出设的，thinking 输出遇第一个空行就被截断；thinking 模式本来也静默忽略 temperature |

前三条属评测侧（`bird/evaluate.py`），第四条属生成侧（`model/bird.py`）；
`--official` 那条路径上前三条不适用（跑的就是官方脚本本身）。

### 天花板 99.87%，不是 100%

`#518`（card_games）与 `#701`（codebase_community）两题的 **gold 自己** 30 秒内跑不出来
（#701 是 SQLite 不物化标量子查询，600 秒也跑不出）。官方脚本同样 30 秒超时、
gold 超时同样判 0，所以这两题对**任何**模型恒为 0。分母照报 1534，不特殊处理。

---

## 4. 档位与分数

两个档位都在 `model/bird.py`，同骨干（`deepseek-v4-pro` + thinking）、同数据、
evidence 都给（BIRD 官方协议）：

| 注册名 | 是什么 | 官方 EX |
|---|---|---:|
| `bird-pro-t-direct` | 官方 baseline 提示词 + 单次调用，不走 pipeline、不注 K1–K11 | **57.37**（880/1534） |
| `bird-pro-t-dsl` | Archer 主线的 `pro-t-dsl` 原样搬过来：no-plan + 声明层 + C1–C4 + 2 轮修复环 | **60.76**（932/1534） |

`bird-pro-t-dsl` 实测（2026-07-27，官方脚本）：相对 direct **+3.39 EX**
（57.37→60.76）；simple 68.84→70.70，moderate 50.11→57.79，
challenging 28.57→29.44。报告：
`results/bird/bird_dev_bird-pro-t-dsl_bird_dev.official.json`。

`bird-pro-t-dsl` 的**唯一变量红线**：相对 en_dev 上那个 EX 52.88 的 `pro-t-dsl`
只有 `evidence=True` 一处不同（Archer 官方设定 w/o knowledge，BIRD 官方设定给
evidence），knowledge / learned_rules / sqlens_checks / conventions / extra_checks
全关。开关矩阵与消息字节两级都有测试锁死（`tests/test_bird.py`）。

**读数口径（写死）**：`bird-pro-t-dsl − 57.37` = 本项目 pipeline 相对官方 baseline
的净值。这个差含**两个变量**——声明层+修复环，以及 schema 表示（官方是纯 DDL，
pipeline 是 DDL + 每表 3 行样本，见 §2 那张表）。样本行是本项目 pipeline 的固有
组成，按"我们的 pipeline vs 官方 baseline"的口径报，说明清楚即可；要拆开归因得
另跑一个 CT-3 格式的直出臂，那是另一份钱。

```bash
python -m model --model bird-pro-t-dsl --data bird_dev          # 生成（分块断点续跑）
python -m bird eval --official --cross-check \
    --pred predictions/bird-pro-t-dsl_bird_dev.json             # 报数
```

⚠️ **生成命令不要加 `--eval`**：runner 的 `--eval` 走 `archer_eval` 的 VA/EX/SIM，
与 57.37 和榜单都不可比。BIRD 的数一律从 `python -m bird eval` 出。

档位 `bird-pro-t-direct`（`model/bird.py`）：官方 baseline 提示词 + 单次调用 +
`deepseek-v4-pro` 开 thinking + evidence 给。不走 pipeline、不注 Archer 的约定表 K1–K11。

```bash
python -m bird fetch                                          # 官方包 → 题目文件（校验 sha256）
python -m bird convert                                        # → data/bird/dev.json
python -m bird eval --gold-as-pred --cross-check              # 天花板 + 两套实现一致性
python -m model --model bird-pro-t-direct --data bird_dev --limit 10   # 冒烟
python -m model --model bird-pro-t-direct --data bird_dev             # 全量（分块断点续跑）
python -m bird eval --official --cross-check --pred predictions/bird-pro-t-direct_bird_dev.json
python -m bird scores                                         # 汇总成表
```

### 天花板（2026-07-26，`--gold-as-pred --cross-check`）

**99.61%（1528/1534）**，两套实现逐档一致。跑不满分的 6 题：

- `#518 #693 #701 #1126 #1131` —— gold 自身 30s 跑不完（`#701` 是 SQLite 不物化标量子查询，600s 也跑不出）；
- `#178` —— gold 里写了 `julianday('now')`，亚秒级抖动。全库共 6 条 gold 有此问题
  （`#127 #143 #146 #158 #178 #1118`），**所以天花板有零点几个百分点的浮动，不是定数**。

交叉验证抓出的两个真 bug（都会改变分数，已修）：

| 问题 | 影响 | 修法 |
|---|---|---|
| gold 压成一行时 `--` 行注释吃掉后半条查询 | `#3 #11 #19 #32` 全 challenging 被误判 0 | 压平前剥注释，字符串字面量里的不动 |
| 官方脚本开 4 进程 | 重查询抢磁盘 → 30s 墙钟超时 → 多挂 1 题、分数不稳 | 回到官方自己的默认 1 进程 |

### 分数表

<!-- 数字不手打：贴 `python -m bird scores` 的输出 -->

**进行中**：前 500 题（按题号，非随机抽样）

| | n | EX |
|---|---:|---:|
| simple | 241 | 56.02 |
| moderate | 123 | 37.40 |
| challenging | 136 | 12.50 |
| **合计** | **500** | **39.60** |

⚠️ 这一段比全集难：challenging 占 **27%**（全集 15%）。按各档命中率外推全集 ≈ **44%**。
全量跑完再作准。

### 失分构成（前 500 题，302 道错题）

| 类别 | 数量 | 含义 |
|---|---:|---|
| 执行报错 | 9 | 语法/列名错，1.8% |
| 列数与 gold 不同 | ~128 | **输出形态没对上**（要几列、要哪几列） |
| 列数同、行数不同 | 57 | 过滤/聚合粒度不同 |
| 行列数都同、值不同 | 108 | 真的算错 |

生成侧是干净的：**0 条格式坏的预测**、0 条残留 markdown 围栏、0 条混入解释文字。

三个典型例子说明"列数不同"是什么性质的错：

```
#23  pred: ('...Community', '313 West Winton Avenue, Hayward, CA 94544-1136')
     gold: ('...Community', '313 West Winton Avenue')          ← gold 只要 Street 列
#28  pred: ('Mountain Oaks', 'County Office of Education (COE)')
     gold: ('Mountain Oaks', '00')                              ← gold 要的是原始编码列
#22  pred: (None,)   gold: ('Dougherty Valley High',)           ← 这个是真错
```

**前两类是"取哪一列/取什么形态"的标注约定问题，不是推理错误。**
这正是本项目约定层（Archer 侧 K1–K11）针对的那类失分——dev-1106 把问题改写得更长、
要求一次输出多列之后，这类约定在 BIRD 上重新变成了有效靶子
（对照 `docs/design/2026-07-26-generalization-research.md` §1.2：在旧 dev 上整套
pipeline 相对裸直出只值 net +3、p=0.66，因为 evidence 把约定直接给了）。
**这是个待验证的观察，不是结论**——要下结论得跑消融。

### 对照点

**唯一可并排的一行**（同考卷 dev-1106、同形态）：

| 行 | 赛道 | 候选数 | Dev EX | Test EX |
|---|---|---:|---:|---:|
| **DeepSeek-R1 (Baseline)** | Single Trained Model | 1 | **61.67** | 60.93 |

差别只剩骨干：R1 vs `deepseek-v4-pro` + thinking。**同厂、同为 reasoning 单模型、
同为单次调用、同样给 evidence**，所以这是一次干净的骨干对比。

主榜那些行（下表）跑在 `dev_20240627` 上，**只作背景，不与我们的数并排**：

| 行 | Oracle Knowledge | Dev EX（dev_20240627） |
|---|:--:|---:|
| Human Performance | ✔️ | 92.96 |
| AskData + GPT-4o | ✔️ | 77.64 |
| MSL-SQL + DeepSeek-V2.5 | ✔️ | 66.82 |
| RSL-SQL + DeepSeek-v2 | ✔️ | 63.56 |
| DeepSeek (Baseline)，236B | ✔️ | 56.13 |
| GPT-4 (Baseline) | ✔️ | 46.35 |
| ChatGPT (Baseline) | ✔️ | 37.22 |

---

## 5. 与 Archer 侧数字的关系

**不可并排。** `python -m bird eval` 报的是 BIRD 官方 EX（`set(rows)` 相等，
无 VA 概念）；`python -m archer_eval` 报的是本项目的 VA/EX/SIM。两套口径独立，
放同一张表里会被误读。跨库结论只能这样写：

> 同一个骨干、同一套提示词组织方式，在 Archer 上得 X，在 BIRD 上得 Y ——
> 各自与各自场地的对照点比，**不比 X 与 Y 的大小**。
