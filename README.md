# Genuine NL2DSL2SQL 复现

基于论文 *Archer: A Human-Labeled Text-to-SQL Dataset with Arithmetic, Commonsense and Hypothetical Reasoning* (EACL 2024)。两段式结构：**`model/` 生成 SQL → `archer_eval/` 评测 VA/EX**（指标严格按论文附录 B 的 Algorithm 1 实现）。

**开发前必读：[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** —— 框架规则、接口约定、可用工具都在那里。

## 快速开始

```powershell
.venv\Scripts\python.exe -m pip install -e .                             # 首次：安装为可导入包
.venv\Scripts\python.exe scripts\check_databases.py                      # 数据库齐全性检查
.venv\Scripts\python.exe -m archer_eval --data en_dev --gold-as-pred     # 评测器自检（应满分）
.venv\Scripts\python.exe -m model --model first_table --data en_dev --eval  # 跑示例模型全流程
.venv\Scripts\python.exe -m pytest -q                                    # 跑测试
```

评测结果看 `results/<名>.md`（人读版：总分 + 分组表 + 每条错误样本的对比）。

## 目录

```
├── config.py        # 全局配置：路径、数据集简写、超时、精度
├── data/            # Archer 数据集（en/zh 的 train/dev）
├── database/        # SQLite 库（不进 git；database/<db_id>/<db_id>.sqlite）
├── model/           # 阶段一：模型接口(base.py)、CT-3 prompt、示例基线、runner
├── archer_eval/     # 阶段二：VA/EX 评测框架
├── predictions/     # 两段的接口：模型生成的 SQL（格式见其中 README）
├── results/         # 评测报告（不进 git，可再生）
├── scripts/         # 独立工具：数据库检查
└── tests/           # pytest
```

## 指标含义

- **VA**：预测 SQL 能被 SQLite 成功执行的比例（不管结果对错）。
- **EX**：预测 SQL 的执行结果与 gold SQL 一致的比例（核心指标；比较时容忍行列排列差异，gold 带最外层 ORDER BY 时行序敏感）。

## 数据说明

- 发布版数据涉及 10 个库（train 8 + dev 2），已齐全；论文完整版的其余库未随数据发布。
- 个别 gold SQL 用 `strftime("%Y","now")`，结果随日期变化，与论文数字对比可能有细微出入。
- 论文主设定评测不提供 `commonsense_knowledge` 字段（难度的一部分）。
