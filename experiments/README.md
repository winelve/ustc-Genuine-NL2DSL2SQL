# 探索实验索引

最终论文主线只保留 DSL 与 fixed semantic few-shot。Direct 是对照，不是第三个
idea。`model.MAIN_MODELS` 给出最终四格；下列代码与档位统一属于探索或历史复现。

这些源码不加入 `.gitignore`，因为负结果和复现能力仍有价值；只有模型权重、
checkpoint、下载仓库和批量运行输出被忽略。

| 方向 | 主要代码 | 状态 |
|---|---|---|
| 自由文本 Plan / Plan+DSL | `model/pipeline/stages/plan.py`、`ProTPlan*` | 历史对照；thinking 骨干上 Plan 会锁死错误决策 |
| Profile / conventions / checks | `model/pipeline/archive.py`、`conventions.py`、`archived_checks.py` | 探索/消融；不属于最终两个 idea |
| Learned knowledge / rules | `model/pipeline/knowledge.py`、`dsl/rules.py` | 探索；不进入最终方法 |
| SFS 结构感知 few-shot | `model/fewshot/structure.py`、`*-sfs` 档位 | 判负；Archer Direct 42.31，低于 semantic FS 44.23 |
| Value Evidence / CHESS-IR | `model/value_evidence/`、`*-ve*` 档位 | 判负；重复实验无稳定增益 |
| Direct/DSL selector | `model/selection/` | 判负；BIRD 61.34，低于 DSL+FS 62.58 |
| DPC-1x1 pilot | `model/dpc_pilot/` | 20 题触发停止规则，净 −1 |
| BIRD 2024-06-27 | `bird-pro-t-dsl-fs-20240627` | 旧版数据归档；61.60，不与 2025-11-06 横比 |

详细实验过程、停止规则与逐题归因保留在 `docs/PROGRESS.md`。运行期输出继续留在
本地 `predictions/`、`results/`、`analysis/` 和 `data/dpc/`；最终四格与必要旧版
快照位于 `artifacts/`。
