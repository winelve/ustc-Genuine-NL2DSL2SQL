# predictions/ — 模型预测文件目录

这里存放**你的模型（GPT、T5 等）对每个问题生成的 SQL**，即评测的输入。

评测流程是两阶段的，本仓库只做第二阶段：

```
[阶段一·生成]  数据集问题 → 你的模型 → 每题一条 SQL   ←← 产物放到本目录
[阶段二·评测]  python -m archer_eval --data en_dev --pred predictions/xxx.json
```

## 文件格式

一个 JSON 数组，**与数据集文件同顺序、同长度**（如 en_dev 是 104 条）。
元素是 SQL 字符串，或带 `predicted_sql` 键的对象（其余键随意，评测只读这个键）：

```json
["SELECT name FROM singer", "SELECT count(*) FROM concert"]
```

```json
[{"predicted_sql": "SELECT name FROM singer", "model": "gpt-4", "latency_ms": 812}]
```

命名约定：`<方法>-<骨干>[-<变体>]_<数据集>.json`，pipeline 另附同名 `.trace.json`。
runner 默认把新跑的结果写在**本目录顶层**；跑完确认无误后按下面的里程碑归档到子目录。

还没有模型时，可用 `--gold-as-pred` 代替 `--pred` 自检评测框架（应得满分）。

## 目录结构（按里程碑归档）

| 目录 | 内容 |
|---|---|
| `m0-direct/` | M0 裸基线：CT-3 prompt 直出 SQL，无 pipeline |
| `m1-plansql/` | M1 plan 式 pipeline（对照组，OraPlan-SQL 复现） |
| `m2-dslsql/` | M2 DSL 中间层（半程 IR：SQL + 声明表 + 校验循环） |
| `smoke/` | 小样本冒烟（`.5q` = 只跑前 5 题）与框架自检 |
| `_duplicates/` | 与正式文件逐字节相同的历史副本，留着只为防手滑，可安全删除 |

`results/` 用同一套子目录与同一套 tag（文件名是 `<数据集>_<tag>.json`），两边一一对应。

## 索引（en_dev 104 题，除非另注；EX = 执行准确率）

| 文件 tag | 配置 | VA | EX | 备注 |
|---|---|---|---|---|
| **m0-direct** |
| `deepseek-v4-pro-thinking` | pro + thinking 直出 | 100 | **40.4** | M0 最强基线，M1/M2 的比较基准 |
| `deepseek-v4-pro` | pro 非 thinking 直出 | 81.7 | 22.1 | 19 条无效 SQL |
| `deepseek-v4-flash` | flash 直出 | 96.2 | 33.7 | |
| `deepseek-v4-flash`（zh_dev） | flash 直出·中文 | 100 | 27.9 | 唯一的 zh 跑分 |
| `deepseek-v4-pro-knowledge` | pro + 知识提示词消融 | 79.8 | 24.0 | prompt 消融，已否决 |
| `deepseek-v4-pro-type` | pro + 题型提示词消融 | 84.6 | 20.2 | prompt 消融，已否决 |
| **m1-plansql** |
| `plansql-pro-thinking` | thinking + 反事实原则，n=1 | 100 | **40.4** | M1 定稿对照组 |
| `plansql-pro-thinking-bare` | thinking + 裸 plan（无反事实原则） | 100 | 30.8 | 消融①的对照，原 `*.bare-plan.*` |
| `plansql-pro` | 非 thinking，n=1 | 99.0 | 29.8 | 对非 thinking 骨干 +7.7 |
| `plansql-pro-n3` | 非 thinking，n=3 投票 | 100 | 27.9 | 原 `plansql-pro-3`，投票 -1.9 |
| **m2-dslsql** |
| `dslsql-pro-thinking` | thinking 骨干（主线） | 98.1 | **44.2** | M2 当前最好成绩 |
| `dslsql-pro` | 非 thinking 骨干 | 100 | 38.5 | 骨干消融 |
| **smoke** |
| `first_table` | 每题取第一张表的哑基线 | 100 | 0.0 | 框架自检 |
| `plansql-flash.5q` | flash pipeline 冒烟 | — | — | 只有 5 题 |
| `deepseek-v4-pro-thinking.5q` | 直出冒烟 | — | — | 只有 5 题 |

（`results/smoke/en_dev_gold.*` 是 `--gold-as-pred` 自检，EX 100，没有对应预测文件。）
