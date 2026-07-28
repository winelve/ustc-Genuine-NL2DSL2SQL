# Few-shot 消融实验

记录四个实验模块：

- `pro-t-direct`：直接生成 SQL。
- `pro-t-dsl`：直接生成 SQL + DSL 声明层。
- `pro-t-direct-fs`：直接生成 SQL + 3 条检索示例，即此前口头所说的 `pro-t-fs`。
- `pro-t-dsl-fs`：DSL 声明层 + 相同的 3 条检索示例。
- `pro-t-direct-sfs`：Direct + SFS 结构感知 top-3。
- `pro-t-dsl-sfs`：DSL + 与 Direct 完全相同的 SFS top-3。

BIRD 使用对应的 `bird-pro-t-*` 模型名，并采用 BIRD 官方 EX；不能和 Archer
的 EX 直接横向比较。

## 结果总览

| 模型 | en_dev | zh_dev | en_train | zh_train | bird_dev |
|---|---|---|---|---|---|
| `pro-t-direct` | 40.38（42/104，历史）<br>36.54（38/104，本轮） | — | — | — | 57.37（880/1534，全量） |
| `pro-t-dsl` | 52.88（55/104，历史）<br>52.88（55/104，本轮） | — | 52.90（219/414，全量） | — | 60.76（932/1534，全量） |
| `pro-t-direct-fs` | 44.23（46/104，全量） | — | — | — | 60.23（924/1534，全量） |
| `pro-t-dsl-fs` | 58.65（61/104，全量） | — | — | — | 62.58 |
| `pro-t-direct-sfs` | 42.31（44/104，全量） | — | — | — | — |
| `pro-t-dsl-sfs` | 40.00（4/10，仅 smoke） | — | — | — | — |

说明：

- 两个 `en_dev` 冒烟结果都被断点续跑复用，104 题全量不是独立的第二次运行。
- `pro-t-direct` 的 40.38 和 36.54 是两次独立全量运行。thinking 模式存在波动，
  所以历史 40.38 保留，但本轮消融使用同期的 36.54。
- `pro-t-dsl` 在 `en_dev` 上有两次独立全量运行，EX 都是 52.88。
- `—` 表示尚未运行。

## SFS 结构感知实验（2026-07-28）

本阶段不加入 RB-lite。SFS 使用同一份冻结的 `pro-t-direct` zero-shot 预测，
在语义 top-30 内按 SQLite AST 结构相似度重排；Direct 与 DSL 共用最终 selection，
prompt 与生成参数不变。

固定配置与 provenance：

- candidate pool `k=30`，最终 `k=3`；
- semantic/structure rank fusion 权重各 0.5，未用 dev gold 调参；
- semantic top-30 SHA-256：
  `BCE07E58CBE0DB4397A691807BE69846FE1233E4494145E62CD36BD046516F79`；
- frozen Direct draft SHA-256：
  `D6EA9904C7D6B39BB36C2BB65075379A9509D8F85035BA71F173CEDB01F1C434`；
- Archer `en_dev` target SHA-256：
  `865DF28A35EA86D04C572C17C2C949860394B1A28B18818175BB1C554E7EDFD1`；
- SFS top-3 SHA-256：
  `4045B19B77A88468B64C39C459D2C4C4E43E1617809FA7C3C8491C3380261322`；
- 104 个 record，0 parser fallback、0 duplicate source ID、0 self-selection；
- proxy draft-structure top-3 均值：语义检索 0.3372 → SFS 0.4613；
- 100/104 题的 top-3 至少变化一条；平均保留 1.45/3 条，SFS 所选例题的
  平均原语义名次为 4.71。

仅用于诊断、未参与选择或调参的 dev-gold 结构相似度为
0.3399 → 0.3962；73 题提升、9 题持平、22 题下降。这说明草案结构有信号，
也保留了“错误草案会带偏部分题目”的风险。

**真实结果：**

- Direct SFS：VA 99.04%、EX 42.31%、SIM 47.30%；相对同骨干语义 top-3 的
  44.23% / 48.86%，EX **−1.92**（少 2 题）、SIM −1.56。
- 配对翻转为语义 FS 独对 8 题、SFS 独对 6 题；精确 McNemar/binomial
  双侧 `p=0.791`，没有正向效果证据，也不能把 −2 题与 thinking 波动严格分开。
- 100 题改了示例集合，93 题生成 SQL 文本改变。4 题示例和顺序完全不变时，
  4 题 SQL 文本仍全部改变，确认 thinking 骨干的单次运行有明显随机性。
- frozen Direct draft 只对 38/104。draft 正确的 38 题中 SFS 净增 1 题；
  draft 错误的 66 题中净减 3 题，错误草案结构被传给检索器是主要风险。
- 等权 Borda 过于激进：312 个入选位置中 161 个来自原语义 top-3 之外，
  42 个原语义名次不高于第 10（即 rank ≥10）。AST 算子计数会把
  “GNP 增长率”和“足球评分求和”视为近结构，结构 proxy 的提升没有转化为 EX。
- DSL SFS 前 10 题 smoke 为 4/10；语义 FS 在同一前 10 题为 6/10，
  同样没有继续花费 94 题 API 成本的正向信号。

结论：当前 `sfs-v1` 收档为负结果；不通过继续调 0.5 权重追 dev 分，也暂不跑
DSL SFS 全量。后续若重开结构检索，必须先解决错误 draft 与“SQL 外形相似但语义
变换不同”两个根因，并使用重复运行或非 thinking 骨干隔离随机波动。

## 基本分析

`en_dev` 使用本轮 Direct 结果计算：

| | 无 few-shot | 加 few-shot | few-shot 增益 |
|---|---:|---:|---:|
| Direct | 36.54 | 44.23 | **+7.69** |
| DSL | 52.88 | 58.65 | **+5.77** |
| DSL 增益 | **+16.34** | **+14.42** | — |

- DSL 和 few-shot 单独加入都有效；当前 DSL 的增益更大。
- 两者组合达到最高分 58.65，相对本轮 Direct 提升 **+22.11**。
- few-shot 在 DSL 上的增益比在 Direct 上低 1.92，当前没有额外协同增益。

BIRD 已有 Direct 57.37、Direct + FS 60.23、DSL 60.76；DSL + FS 尚无全量结果，
因此暂时不能完成 BIRD 的四格分析。

## 尚缺实验

- BIRD：补 `bird-pro-t-dsl-fs` 全量。
- Archer：`zh_dev`、`en_train`、`zh_train` 三个数据集全部待补。
- 这三个 Archer 数据集还没有对应的 fixed few-shot selection，需先生成并接入，
  再运行两个 few-shot 模型。

## 结果文件

- 历史 Direct：`results/direct/en_dev_pro-t-direct.json`
- 历史 DSL：`results/dsl/en_dev_pro-t-dsl.json`、
  `results/dsl/en_train_pro-t-dsl.json`
- 本轮 Archer：`results/en_dev_pro-t-direct.json`、
  `results/en_dev_pro-t-dsl.json`、`results/en_dev_pro-t-direct-fs.json`、
  `results/en_dev_pro-t-dsl-fs.json`
- BIRD：`results/bird/*.official.json`
