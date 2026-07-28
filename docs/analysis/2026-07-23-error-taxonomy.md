# Archer 错因分类体系（en_train 414 + en_dev 104）

> 分析对象：`dslsql-pro-thinking`（M2 半程 IR，deepseek-v4-pro + thinking）
> 数据：`results/m2-dslsql/en_{train,dev}_dslsql-pro-thinking.json` + 对应 trace
> 代码：`analysis/error_taxonomy/`，可对任意预测文件重跑
> 日期：2026-07-23

## 0. 摘要

| 数据集 | 题数 | EX | 错题 | 检测器覆盖 |
|---|---|---|---|---|
| en_train | 414 | 52.2% | 198 | 88.9%（未覆盖 22） |
| en_dev | 104 | 44.2% | 58 | 96.6%（未覆盖 2） |

**三个总体结论**：

1. **错误几乎全在语义层，不在语法层。** VA 98–100%，SQL 都能跑，跑出来的东西不对。
2. **模型缺的主要不是知识，是触发。** 单位换算常量（`1.609344`）、世界常识实体
   （`Russia`、`San Jose`）都是 LLM 明确知道的东西，但在思维链里一次都没出现。
3. **DSL 四组校验与最终正确性几乎无关**（见 §5），M2 的价值在"逼出显式声明"，
   不在"判对错"。

## 1. 方法

三条独立的证据链，互相交叉验证：

| 方法 | 文件 | 做什么 | 局限 |
|---|---|---|---|
| A 指纹差分 | `fingerprint.py` | 抽 16 维 SQL 能力指纹，gold 与 pred 做差 | 表达等价维度假阳高 |
| B 检测器 | `detectors.py` | 16 个针对具体失效模式的判据，一题可多标 | 只覆盖已识别的模式 |
| C 思维链缺口 | `cot_gap.py` | gold 用到、题面没给、`plan`+`declarations` 也没提的常量与列 | 部分循环性，见 §4 |

**检测器的准入约定**：只用 `question` / `gold_sql` / `pred_sql` / shape / schema 列名，
不用 gold 之外的标注；必须给可复核的 `evidence`。

**精确率是取舍依据**。同一维度在答对的题上也频繁触发 = 该维度只是表达等价，不是错因：

| 高精度（≥0.9，可直接定类） | 中（0.6–0.8，需人工复核） | 低（<0.6，仅供参考，**不得单独引用**） |
|---|---|---|
| `OUTCOL` 1.00 · `UNITPREC` 1.00 · `DATEFMT` 1.00 · `AGEALGO` 0.92 · `NOWMISS` 0.90 | `GROUPKEY` 0.68 · `WORLDCONST` 0.66 · `ABSMISS` 0.75 · `TIEBREAK` 0.75 · `RATIOMISS` 0.75 · `TABLESET` 0.63 | `ENTITY` 0.50–0.56 · `TABLESET`(dev) 0.55 · `NULLFILT` 0.46–0.52 · `DISTRUST` 0.43 · `LITCOL` 0.25 |

`TABLESET` / `LITCOL` 低精度的原因是 `NOT IN` vs `EXCEPT` vs `LEFT JOIN IS NULL`、
子查询 vs JOIN 这类等价改写——模型换个写法照样答对。

**两条使用纪律**：

1. **检测器发现的是"gold 与 pred 的可观测差异"，不是"错误原因"。**
   原因是分析者对差异的解释，写在各节的"成因"里，那部分未经检测器验证。
2. **`OUTCOL` 的 1.00 精确率有部分定义性**——列数不同评测器几乎必然判错，
   所以它不是独立预测，而是"重述评测器为什么说不"。它的价值在于指出
   **修法是输出规约而非知识注入**，不在于预测。

核对稿：`analysis/error_taxonomy/review_{dev,train}.md`，按检测器分组，
每条给证据 + gold/pred 对照，**并列出全部假阳（答对却被命中）供判断可信度**。

---

## 2. 分类体系

按**修复所需的手段**分五层。这个分层直接决定知识层怎么设计：L0/L3 靠规约与校验，
L1/L2 靠知识注入，L4 不可修。

```
L0 输出规约      —— 语义已对，输出形态不合评测口径      不需要任何知识
L1 值与实体      —— 指称→库内值的解析                需要世界知识 + 库内值表
L2 口径与公式    —— 同一概念的不同算法约定              需要 Archer 标注惯例
L3 结构与范围    —— 聚合基数、分组粒度、连接路径         程序/LLM 可判
L4 基准噪声      —— gold 本身有问题                  不可修，需剔除后再算分
```

---

### L0 · 输出规约（语义已对，白丢分）

#### L0-1 输出列数不符 `OUTCOL`

- **判据**：`pred_shape[1] != gold_shape[1]`
- **频次**：train 32 / dev 7，**精确率 1.00（答对的题中零命中）**
- **样例**（dev #80）：问 "which country has the largest reduction in GNP"

  ```sql
  gold: SELECT Name FROM country WHERE ... ORDER BY GNPOld-GNP DESC LIMIT 1
  pred: SELECT c.Name, c.GNPOld-c.GNP AS Reduction FROM ... ORDER BY Reduction DESC LIMIT 1
  ```

  库上验证：pred 正确取到 `Japan`，**只是多输出了 `Reduction` 一列**。删掉即与 gold 一致。
- **成因**：模型把"计算过程中的中间量"也当成了要输出的答案。
- **可检验性**：**程序可判**。声明 `outputs` 的条数 vs 问题问了几样东西。
- **修复手段**：输出规约（提示词层面）+ C 类校验。**零知识需求。**

#### L0-2 数值类型不符 `(未纳入检测器，人工发现)`

- **样例**（dev #100/#101）：

  ```sql
  gold: SELECT CAST(IndepYear + LifeExpectancy AS INT)   → 2001
  pred: SELECT IndepYear + LifeExpectancy               → 2001.2
  ```

- **频次**：dev 2（即 §0 中"未覆盖 2 条"的全部）
- **成因**：年份是整数，gold 取整，pred 保留小数。
- **可检验性**：**程序可判**（输出语义是"年份/人数/个数"时结果应为整数）。

> **L0 合计：train 32 + dev 9 = 41 题，全部零知识需求。** 这是投入产出比最高的一档。

---

### L1 · 值与实体（需要外部知识把指称落到库内值）

#### L1-1 世界知识实体未解析 `ENTITY`

- **判据**：gold 用了一个**题面没出现**的字符串字面值，而 pred 没用
- **频次**：train 23（精确率 **0.56**）/ dev 3（**0.50**）
- **⚠️ 该判据不可单独引用。** 精确率约 0.5 意味着一半的命中是假阳——gold 与 pred
  用不同字面值达成同一语义的情况很常见。下面的样例是人工复核确认过的，
  但**检测器给出的完整列表必须逐条复核后才能用**。
- **修订记录**：初版此项曾报 train 56 / dev 22，是 bug——字面值提取把
  `strftime("%Y","now")` 里的 `'now'` 当成了待解析实体。已在 `_strlits` 中
  排除 SQL 函数参数与格式串后重算。
- **样例**：

  | 题号 | 题面指称 | gold 用的库内值 | 需要的知识 |
  |---|---|---|---|
  | train #42 | "third most populous city in California" | `San Jose` | 地理常识 |
  | train #194/195 | "largest country by land area" | `Russia` | 地理常识 |
  | train #189 | "capital of Portugal" | `Lisbon` | 地理常识 |
  | train #198 | "footballer Cristiano Ronaldo's nationality" | `Portuguese` | 人物常识 |

- **成因**：题面用间接指称，必须先用世界知识解析成具名实体，再匹配库内写法。
- **注意**：train #194/#195 还叠加了**库内写法差异**——题面说 "United States"，
  库里存的是 `USA`。pred 用了 `'United States'`，查不到任何行。
- **可检验性**：**LLM 可判**（"这个指称解析成了什么？库里有这个值吗？"），
  程序只能判后半段（值在不在库里——C3 已有基础设施）。

#### L1-2 字面值挂错列 `LITCOL`

- **判据**：同一字面值，gold 与 pred 绑在不同的列上
- **频次**：train 2（精确率 0.25，噪声大）/ dev 4（1.00）
- **样例**（dev #68/#69）：`Kang-won` 是 `city.District` 的值，不是 `city.Name` 的值

  ```sql
  gold: ... >= 2 * (SELECT SUM(Population) FROM city WHERE District = "Kang-won")
  pred: ... >= 2 * (SELECT Population     FROM city WHERE Name     = 'Kang-won')
  ```

  连带错误：District 对应多个城市，必须 `SUM`；pred 当成单城市直接取 `Population`。
- **可检验性**：**程序可判**。C3 现在只查"值存不存在"，改成"值出现在**哪些列**里"
  即可直接报错。这是现有代码的小改动。

#### L1-3 值拼写错误 `(未纳入检测器)`

- **样例**（train #399）：pred 写 `Grape = 'Cabernet Sauvingnon'`（少一个 `u`，
  且列名也选错——gold 用 `name`）。查不到任何行。
- **可检验性**：**程序可判**。C3 的 difflib 近邻已有此能力，当前未对所有字面值强制执行。

---

### L2 · 口径与公式（同一概念的不同算法约定）

这一层是**知识注入的主战场**。共同特征：模型的做法在数学上往往说得通，
只是与 Archer 标注方的约定不同。

#### L2-1 缺当前时间锚 `NOWMISS`

- **判据**：gold 含 `'now'`/`strftime`，pred 完全没有当前时间引用
- **频次**：dev 19（精确率 0.90）/ train 4（1.00）
- **两个子型**（按 `declarations.time_context.displaced` 切分）：

  | 子型 | dev n | 含义 |
  |---|---|---|
  | 未察觉要回算 | 9 | 声明 `displaced=false`，压根没意识到有时点问题 |
  | 察觉了但口径算错 | 10 | 声明 `displaced=true`，但算式与声明矛盾 |

- **样例（未察觉）** dev #0：问 "age at the time of the release of Gentleman"

  ```sql
  gold: SELECT Name, Age + (SELECT Song_release_year FROM singer WHERE Song_Name="Gentleman")
                          - strftime("%Y","now") AS target_age FROM singer
  pred: SELECT Name, Age FROM singer WHERE Song_Name = 'Gentleman'
  ```

- **样例（口径错）** dev #3，**声明与算式自相矛盾**：

  ```
  anchors: {"Age": "current age of the singer as stored in the database"}   ← 写对了
  expr   : Age - (CAST(Song_release_year AS INTEGER) - 2001)                ← 当成了发行当年的年龄
  ```

- **关键事实：`singer.Age` 的口径无法从数据推断，且数据会误导。**

  ```
  Joe Sharp Age 52 / 1992    Timbaland 32 / 2008    Justin Brown 29 / 2013    Tribal King 25 / 2016
  ```

  按 gold 口径（Age = 当前年龄），这批歌手发歌时全是 14–18 岁；
  按另一种读法（Age = 发行时年龄），Joe Sharp 生于 1940、现年 86，**更合理**。
  这是 Archer 的标注约定，不是库里的事实。
- **可检验性**：**"声明正确性"程序判不了，"声明与算式一致性"程序可判。**
  这是本项目最重要的可检验性区分（见 §6）。

#### L2-2 年龄算法口径 `AGEALGO`

- **判据**：gold 用「年差 − 生日是否已过」，pred 用 `julianday/365.25`
- **频次**：train 11（精确率 0.92）
- **样例**（train #150）：

  ```sql
  gold: AVG(strftime("%Y","now") - strftime("%Y",dob) - (strftime("%m-%d","now") < strftime("%m-%d",dob)))
  pred: AVG((julianday('now') - julianday(date_of_birth)) / 365.25)
  ```

- **成因**：两种算法在边界日期上差 1 岁。Archer 一律用前者。
- **可检验性**：**程序可判**（出现 `/365` 即报）。**约定需注入。**

#### L2-3 日期存储格式误判 `DATEFMT`

- **判据**：gold 用 `substr` 切片，pred 用 `strftime` 解析同一列
- **频次**：train 3，**精确率 1.00**
- **样例**（train #158/#159）：`formula_1.drivers.dob` 存的是 `DD/MM/YYYY` 字符串，
  SQLite 的 `strftime` **解析不出**，返回 NULL。gold 用 `substr(dob,7,4)` 取年。
- **可检验性**：**程序可判**，且**可从样本行自动发现**——这属于库画像该做的事。

#### L2-4 缺具名比率相除 `RATIOMISS`

- **判据**：gold 把两个 schema 列相除，pred 中分母列完全未出现
- **频次**：dev 6（精确率 0.75）/ **train 0**
- **样例**（dev #24/#40/#41）："attendance rate" = `Average / Capacity`，
  pred 直接拿 `Average` 排序，连除都没除。
- **重要观察：train 上此类为 0。** train 8 库没有这种"两列相除的具名比率"结构，
  dev 两库（`stadium.Average/Capacity`、`country.Population/SurfaceArea`、
  `GNP/Population`）密集。**这是 dev 比 train 难 8 个百分点的一个直接原因，
  也说明该类知识无法从 train 蒸馏，只能从 schema 派生。**

#### L2-5 派生指标被反事实劫持 `(人工发现)`

- **频次**：dev 4，**全部答错**
- **判据**：全 104 题中只有这 4 题的 pred 完全没引用 `GNPOld`
- **样例**（dev #74/#75/#90/#91）：`world_1` 的 "GNP growth rate" 锚在 `GNPOld` 上，
  即 `(GNP - GNPOld)/GNPOld`。同类题只要**没有反事实**（#80）或假设不改 GNP
  （#58/#82/#86），模型都正确用了 `GNPOld`。一旦假设修改的目标就是 GNP 本身，
  模型就把 growth 重新解释成"假设造成的变化"（`调整后GNP/原GNP - 1`），绕开 `GNPOld`。
- **成因**：**反事实语境覆盖了模型已有的正确理解。** 不是不知道公式。
- **含义**：知识条目必须写成**带锚的形式**——`growth ≜ (GNP-GNPOld)/GNPOld，
  锚列 GNPOld，反事实修改 GNP 时锚不变`——而不只是一条公式。

#### L2-6 缺题面未给的外部常量 `WORLDCONST`

- **频次**：train 59（精确率 0.66）/ dev 9（0.60）
- **高频缺失常量**（错题中）：`1.609344`（英里→公里）4 次、`0.45` 3 次、
  `609.344` 2 次、`136`（地球最高气温 °F）2 次
- **关键观察**：`1.609344` 在模型的思维链里**一次都没出现过**。LLM 当然知道
  1 英里 = 1.609344 公里——**它缺的不是知识，是触发。**
- **样例**（train #45）：地球最高温 gold 用 `136`，pred 用 `134`（记错了）
- **样例**（train #31）：gold `*1.609344`，pred `*1.60934`（精度不足，`UNITPREC` 捕获，
  train 4 次，精确率 1.00）
- **可检验性**：**程序判不了，LLM 可判但可能记错。** 常量表需注入。

#### L2-7 差值未取绝对值 `ABSMISS`

- **频次**：train 12（精确率 0.75）
- **样例**（train #320）：gold `ABS(overall_rating - potential)`，pred 不取绝对值
- **依据**：train 的 `commonsense_knowledge` 明确写着
  "difference between two values should be an absolute value"
- **可检验性**：**LLM 可判**（题面出现 "difference / how much ... than" 而 SQL 无 `ABS`）。
  **约定需注入。**

#### L2-8 统计量定义 `(未纳入检测器)`

- **样例**（train #104/#105）：variance。gold 用 `(x-AVG(x))²/COUNT(*)`（总体方差），
  pred 用 `(Σx² - (Σx)²/n)/(n-1)`（样本方差）。**分母 n vs n−1。**
- **可检验性**：**LLM 可判**。约定需注入。

---

### L3 · 结构与范围（程序/LLM 可判，多数不需要外部知识）

#### L3-1 不信任题面给定事实 `DISTRUST` / `GIVENVAL`

**这是本轮新发现的、值得单独命名的失败模式。**

- **判据**：题面直接给出了数值/事实，gold 当常量用，pred 却回库重新查/聚合
- **频次**：`DISTRUST` train 6 + dev 1；`GIVENVAL` train 12 + dev 1；
  人工在未覆盖集里另找到 ≥6 条（#183/#190/#191/#197/#207/#15）
- **样例**：

  | 题号 | 题面已给 | gold | pred |
  |---|---|---|---|
  | train #183 | "the **two** racing circuits in Japan" | `HAVING COUNT(*) > 2*2` | `> 2*(SELECT COUNT(*) ... WHERE country='Japan')` |
  | train #190/191 | "If **5** races were held in Lisbon" | `HAVING COUNT(*) > 3*5` | `CASE WHEN location='Lisbon' THEN 5 ...` |
  | train #197 | "If the USA has **two** circuits" | `1.0*2/COUNT(*)` | 复杂 `UNION ALL` 重构 |
  | train #207 | "Allen Berg's **10** competitive races" | `HAVING COUNT(*) >= 2*10` | `>= 2*(SELECT COUNT(*) ...)` |
  | train #15 | "duration ... **666** which is the average" | `duration >= 2*666` | `>= 2*(SELECT AVG(duration) ...)` |

- **成因**：模型不信任题面给定值，坚持"从数据库求证"。**与反事实（H）高度相关**——
  反事实假设本身就是一种题面给定值。
- **可检验性**：**程序可判**（题面出现的数字，gold 直用而 pred 换成了聚合子查询）。
  **零知识需求**，属提示词/校验问题。

#### L3-2 聚合基数被预过滤改变 `NULLFILT`

- **频次**：dev 14（精确率 0.52）/ train 6（0.46）——精确率低，需人工复核
- **样例**（dev #73/#88/#89）：pred 自加 `WHERE GNP IS NOT NULL AND GNPOld > 0`，
  gold 不过滤（靠 `SUM` 自动忽略 NULL）。两者的 `SUM(Population)` 分母集合不同。
- **样例**（train #122/#123）："never attended a class" 的 gold 口径是
  `NOT IN (SELECT customer_id FROM Lessons WHERE lesson_status_code != "Cancelled")`
  ——**被取消的课不算"上过课"**。pred 用了 `NOT IN (SELECT customer_id FROM Lessons)`。
- **可检验性**：前者**程序可判**（SQL 有 `IS NOT NULL` 而题面未要求）；
  后者是口径，**LLM 可判 + 需注入**。

#### L3-3 分组粒度 / 表集合 `GROUPKEY` / `TABLESET`

- **频次**：`GROUPKEY` train 67 / dev 16；`TABLESET` train 79 / dev 21
- **精确率低（0.55–0.68），大量是表达等价**，不可直接定类
- **真实错误样例**（train #20）：gold 从 `trip` 表 `GROUP BY end_station_name`；
  pred `LEFT JOIN station`，把零行站点也带了进来 → 多出若干 NULL 行
- **样例**（train #47）：gold 的百分比分母是 "San Francisco 的总站数"，
  pred 用了"全部站数" → **比较基准范围错**
- **可检验性**：**LLM 可判**（需要理解题面的范围限定）。程序只能给候选，不能定论。

#### L3-4 并列截断语义 `TIEBREAK`

- **判据**：gold 用 `= (SELECT MAX ...)` 保留并列，pred 用 `ORDER BY ... LIMIT 1` 截断
- **频次**：train 3（精确率 0.75）
- **可检验性**：**程序可判**。约定需注入（"最值题默认保留并列"）。

---

### L4 · 基准噪声（gold 本身有问题，不可修）

- **样例**（train #192）：题面问 **Lewis Hamilton**，gold SQL 查的是
  `surname = "Albers" AND forename = "Christijan"`。**gold 与题面不符。**
- **样例**（train #300）："before the 21st Century" gold 写成 `Start_year < 2006`
- **样例**（train #108）：题面拼 `Damon Sanford`，gold 里是 `Dameon Sanford`
- **影响**：这类题无论模型怎么做都不可能答对。**建议在最终评测中单列统计**，
  避免把基准噪声计入模型失败。目前未系统清点，属已知未完成项。

---

## 3. 频次总表

| 层 | 代码 | 名称 | train 错题 | dev 错题 | 精确率 | 可检验性 |
|---|---|---|---|---|---|---|
| L0 | `OUTCOL` | 输出列数不符 | 32 | 7 | **1.00** | 程序 |
| L0 | — | 数值类型不符 | — | 2 | — | 程序 |
| L1 | `ENTITY` | 世界知识实体未解析 | 23 | 3 | ⚠️0.56 / 0.50 | LLM |
| L1 | `LITCOL` | 字面值挂错列 | 2 | 4 | 0.25 / 1.00 | 程序（C3 扩展） |
| L2 | `NOWMISS` | 缺当前时间锚 | 4 | 19 | **0.90+** | 一致性可判 |
| L2 | `AGEALGO` | 年龄算法口径 | 11 | 0 | **0.92** | 程序 |
| L2 | `DATEFMT` | 日期存储格式误判 | 3 | 0 | **1.00** | 程序 |
| L2 | `RATIOMISS` | 缺具名比率相除 | 0 | 6 | 0.75 | 声明层可判 |
| L2 | — | 派生指标被反事实劫持 | — | 4 | — | 需注入 |
| L2 | `WORLDCONST` | 缺外部常量 | 59 | 9 | 0.66 | 需注入 |
| L2 | `UNITPREC` | 换算常量精度 | 4 | 0 | **1.00** | 程序 |
| L2 | `ABSMISS` | 差值未取绝对值 | 12 | 0 | 0.75 | LLM |
| L3 | `DISTRUST`+`GIVENVAL` | 不信任题面给定事实 | 18 | 2 | 0.43–0.75 | 程序 |
| L3 | `NULLFILT` | 自加 NULL 预过滤 | 6 | 14 | 0.46 / 0.52 | 程序 + LLM |
| L3 | `GROUPKEY` | 分组键不同 | 67 | 16 | 0.68 | LLM |
| L3 | `TABLESET` | 表集合不同 | 79 | 21 | 0.63 | LLM |
| L3 | `TIEBREAK` | 并列截断语义 | 3 | 0 | 0.75 | 程序 |

一题可命中多个代码（错误常是复合的），故合计大于错题数。

---

## 4. 思维链缺口（`cot_gap.py`）

度量：**gold 用到、题面没给、模型 `plan`+`declarations` 也没提**的常量与列。
不依赖 `commonsense_knowledge`，因此 dev 上同样可算。

train 呈单调的剂量—反应关系：

| 思维链漏掉的项数 | n | EX |
|---|---|---|
| 0 | 287 | 58.9% |
| 1 | 97 | 40.2% |
| 2 | 21 | 28.6% |
| ≥3 | 9 | 22.2% |

dev 同向（n 小）：漏 0 → 47.4%，漏 1 → 43.5%，漏 2 → 0%（n=5）。

**局限（必须写进论文）**：该指标有部分循环性——答对通常就意味着用了那些列，
所以"漏了→更可能错"有一部分是定义使然。**它的价值不在预测，在定名。**

**它自动重现了人工归因**：dev 上漏得最多的四个列与人工通读结论一一对应——
`Capacity`(5)→L2-4、`District`(4)→L1-2、`GNPOld`(4)→L2-5、`Song_release_year`(2)→L2-1。
这说明归因可自动化，换预测文件重跑即得。

**CK 有无 × 对错**（两数据集一致）：

| | 有 CK | 无 CK | 差 |
|---|---|---|---|
| train | 40.1%（222 题） | 66.1%（192 题） | **−26.0** |
| dev | 34.5%（58 题） | 56.5%（46 题） | **−22.0** |

---

## 5. DSL 校验器与正确性无关（M2 的负面证据）

en_dev，四组校验（C1 完整性 / C2 一致性 / C3 接地 / C4 锚完整）：

| | 答对 | 答错 |
|---|---|---|
| `checks.passed = True` | 34 | 34 |
| `checks.passed = False` | 12 | 24 |

通过与否几乎不区分对错（50% vs 33%）。与 M2 设计文档"纯结构校验一条都抓不到"
的预判一致，现在有数了。**校验器的价值在于逼出显式声明供上层判，不在于自己判对错。**

---

## 6. 可检验性三分（对知识层设计的直接输入）

这是本文档最重要的产出。**"能不能检验"决定了每一类该用什么手段修。**

### 程序确定性可判（不需要任何外部知识）

`OUTCOL`、数值类型、`DISTRUST`/`GIVENVAL`、`NULLFILT`（前半）、`LITCOL`、
`AGEALGO`、`DATEFMT`、`UNITPREC`、`TIEBREAK`

合计 train ≈ 75 / dev ≈ 30 人次。**这一档不需要造知识库，只需要写校验规则。**

### LLM 可判（需要语义理解，但不需要模型没有的知识）

`ENTITY`、`ABSMISS`、`GROUPKEY`、`TABLESET`、`NULLFILT`（口径部分）、统计量定义

**关键设计约束**：LLM 检验的正确形态**不是**"你觉得这条 SQL 对吗"——那等于重做一遍，
不产生独立信号。正确形态是**给定声明表，逐条判"这条声明与题面是否吻合"**：
输入封闭、输出是判断题、不重新生成 SQL。这与生成任务不同，能提供独立证据。

### 必须注入（模型判不了也推不出）

- **Archer 标注约定**：年龄算法、并列保留、绝对值、总体方差、取消课不算上课
- **世界常识常量**：`136`（地球最高温 °F）、单位换算精度
- **库画像**：日期存储格式、成对列、具名比率候选（`RATIOMISS` 在 train 为 0，
  证明此类只能从 schema 派生，无法从 train 蒸馏）

### 三条不可修/不该修

1. **L4 基准噪声**——gold 与题面不符，应剔除后统计
2. **表达等价**——`NOT IN` vs `EXCEPT`、子查询 vs JOIN，不是错误，检测器不得定类
3. **`singer.Age` 一类的列口径**——数据无法证伪且会误导（见 L2-1），
   只能靠"声明—算式一致性"兜住，不能靠"判声明正确性"

---

## 7. 已知局限

1. **train 仍有 21 条未覆盖**，多为复合反事实（#10/#11/#412）与复杂嵌套（#331/#364）。
2. **L4 基准噪声未系统清点**，目前只有 3 个人工发现的样例。
3. **检测器为单向判据**：只描述 gold 与 pred 的差异，不证明因果。
   中低精确率的代码（`TABLESET`/`GROUPKEY`/`NULLFILT`/`LITCOL`）必须人工复核后才可引用。
4. **只分析了 en。** zh 未做，`dslsql-pro`（非 thinking）未做。
5. **`cot_gap` 的列通道有噪声**：`soccer_1.player_fifa_api_id` 出现 25 次，
   实为 `player_api_id` vs `player_fifa_api_id` 的连接键之争，属 L3 而非知识缺失。

---

## 8. 复现

```bash
# 1. 指纹 + 人工标签 → labels
.venv\Scripts\python.exe -m analysis.error_taxonomy.build_labels \
    --results results/m2-dslsql/en_dev_dslsql-pro-thinking.json \
    --trace   predictions/m2-dslsql/dslsql-pro-thinking_en_dev.trace.json \
    --out     analysis/error_taxonomy/labels.json --dataset en_dev

# 2. 检测器全量 → 错因标签集 + 覆盖率
.venv\Scripts\python.exe -m analysis.error_taxonomy.run_detectors \
    --labels analysis/error_taxonomy/labels.json \
    --out    analysis/error_taxonomy/detected_dev.json

# 3. 思维链缺口
.venv\Scripts\python.exe -m analysis.error_taxonomy.cot_gap \
    --labels analysis/error_taxonomy/labels.json --data data/en_data/dev.json
```

> **注意**：`manual_labels.py` 里的人工标签**只对 `en_dev` 生效**（`DATASET` 常量控制）。
> 不同数据集的同一 `index` 是不同题目，跨数据集套用会张冠李戴。
