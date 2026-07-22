# NL2DSL2SQL @ Archer benchmark

新会话必读顺序（读完即可开工，无需用户再交代背景）：

1. **docs/PROGRESS.md** — 当前进度、里程碑路线图、下一步任务、决策记录
2. **docs/DEVELOPMENT.md** — 框架铁律与接口约定（改代码前必读）
3. **README.md** — 运行命令

## 一句话背景

在 Archer benchmark（https://sig4kg.github.io/archer-bench/）上构建 NL2SQL pipeline：
先复现 OraPlan-SQL（`docs/material/2510.23870v1.pdf`，2025 挑战赛第一名）作为对照组，
再引入 **DSL 中间层**补充语义逻辑（本项目的核心命题），用消融对比证明其价值。

## 关键约定速记（完整版见 DEVELOPMENT.md）

- 两段式：`model/` 生成 → `predictions/*.json` → `archer_eval/` 评测，**只通过预测文件通信**
- `archer_eval` 永远不准 import `model`；路径只写 `config.py`；数据库一律只读；密钥只走环境变量
- 新模型 = 继承 `SQLGenerator` + 在 `model/__init__.py` 的 `MODELS` 注册
- 提交前 `.venv\Scripts\python.exe -m pytest -q` 必须全绿

## 会话结束时

把本次进度写回 `docs/PROGRESS.md`：完成了什么、做了什么决策（附原因）、下一步是什么。
