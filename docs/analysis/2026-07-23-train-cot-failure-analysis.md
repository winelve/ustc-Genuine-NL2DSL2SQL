# train 思维链失效分析 + dev 分析复审

> 分析对象：`dslsql-pro-thinking`
> 材料：`results/m2-dslsql/en_{dev,train}_dslsql-pro-thinking.json` +
> `predictions/m2-dslsql/dslsql-pro-thinking_en_{dev,train}.trace.json`
> 方法：**人工通读**。脚本只用于把 Q/gold/pred/plan/declarations 排版出来给人看，
> 以及最后一节的计数；分类与归因全部人工判读。
> 日期：2026-07-23
> 上一份：`2026-07-23-cot-failure-analysis.md`（dev 58 题）

---

# 第一部分　dev 分析复审

我逐条回查了上一份文档的引文与计数。

## 一、成立的部分（已逐条核对原文）

| 结论 | 复核结果 |
|---|---|
| 发现 1：模型把"我在猜"写进 plan（#2/#5/#12） | ✅ 三条引文**逐字属实**，见下方原文 |
| 发现 3：#24/#25 vs #26/#27 天然对照 | ✅ plan 原文属实，是全文最硬的一条证据 |
| B-3：GNPOld 被反事实劫持（#74/#75/#90/#91） | ✅ 四题 pred 确实完全不含 `GNPOld`；#58 反例也属实 |
| A-2：Kang-won 被当成城市名（#68–#71） | ✅ plan 第 1 步原文 "Find the population of the city named 'Kang‑won'" |
| C 段：#3 声明写对锚、算式用另一假设 | ✅ 属实 |

**发现 1 的三条原文**（我重新拉的，与上一份一致）：

- #5 plan 第 3 步："using the age as stored in the table, **because there is no
  birth year to compute an age at concert time**; the stored age is the only
  available value"
  —— gold 是 `Age + (Year - now)`。模型缺的就是"Age 锚在 now"这一条，**没有它，
  放弃换算是合理推理**。
- #12 plan 第 3 步："(Assume `Age` reflects the singer's age in the concert year
  **or** at the time the data was recorded.)"
- #2 plan 第 2 步：显式写出 "This assumes `Age` represents the singer's age at the
  original `Song_release_year`"

这份文档的引文可信度高，可以放心作为后续设计的依据。

## 二、需要修正的部分

### 修正 1：发现 2 的"每题现编"说法不准，实际有稳定机制

上一份说 `singer.Age` 的锚"六道题给出四个互相矛盾的答案 …… 不是稳定偏差，
而是每道题现编一个"。我把 concert_singer 全 52 题的 Age 锚拉出来看：

| 锚的家族 | 题号 | 条数 |
|---|---|---|
| 锚在**演唱会时点** | #12 #13 #15 #20 #21 #22 | 6 |
| 锚在**歌曲发行年** | #2 #4 #14 | 3 |
| 锚在**当前**（正确） | #3 | 1 |

不是四种，是**三族**；而且分布不随机——**锚总是被题面里出现的那个时间实体吸走**：
题里提演唱会就锚在演唱会，提发行年就锚在发行年。#13 甚至把这个实体的年份
（2015）当成事实写进锚里。

这个修正很重要，因为它改变了结论的性质：
不是"模型没有依据所以乱飘"，而是**"模型有一条稳定的错误规则：拿题面里最近的时间
实体当锚"**。同一条规则也解释了 B-3——反事实制造了一对新的"改前/改后"对照，
把 growth 的锚从 `GNPOld` 抢走了。**锚点臆断和反事实劫持是同一个机制的两种表现。**

（原结论"注入知识是从无到有地提供依据"仍然成立，而且更强：知识要**压过**一条
已有的错误规则，不只是填空白。）

### 修正 2：§三 的计数表不是划分，且漏了 10 题

表头写"记**最早**的那个断点"（即划分），脚注又写"含重叠"——两者不能同时成立。
按题号展开后：各行相加恰好 58，但去重后只覆盖 48 题（另有 5 题在"锚点臆断 15"里
未列号）。**从未出现在文档任何位置的有 10 题：#6 #44 #46 #92 #93 #94 #95 #98
#102 #103。** 也就是说这张表是凑出来的，不是数出来的。

### 修正 3：那 10 题里有三类上一份完全没有命名的错因

我把这 10 题读完了，它们不是零头，是三个新类别：

**(a) 线性外推 vs 复合外推（#92 #93 #94 #95，4 题）**

> "estimate the future GNP if the growth rate remains unchanged"
> gold：`GNP + (GNP - GNPOld)` ——**等差**（增量不变）
> pred：`GNP * (GNP / GNPOld)` ——**等比**（比率不变）

四题全部同因。按英文 "growth **rate**" 的字面，**模型的读法才是标准的**；
Archer 一律取等差。这是纯口径约定，与推理能力无关。

**(b) 比值的平均 vs 总量的比值（#102 #103，2 题）**

> "the average per capita GNP of all European countries"
> gold：`SUM(GNP) / SUM(Population)` ——总量之比
> pred：`AVG(GNP / Population)` ——比值之平均

两者数学上不同。gold 的写法在人口加权时更常见，模型的写法按字面更直接。
同一分歧在 train 的 #90/#91 再次出现。

**(c) 反事实的集合赋值语义（#98）**

> "If the population of countries with a life expectancy greater than 75 in
> Europe is 103000"
> gold：给**每一个**符合条件的国家都赋 `Population = 103000`
> pred：把 103000 当**总量**，按各国原有份额分摊

这一条在 train 里反复出现（wine_1 #373 同构），值很高，见第二部分 §2.4。

另外 #44/#46 是 **"how many times" = 倍数**（gold 输出比值，pred 输出计数），
#6 属于已有的锚点臆断类。

## 三、复审结论

上一份的**证据是可靠的，三个主发现有两个完全站得住**（发现 1、发现 3），
发现 2 的现象属实但机制说反了。真正的问题是**覆盖不全**：58 题里 10 题没读，
而这 10 题恰好装着 dev 唯一的"口径类"错误——也正是 train 里占绝对主导的那一类。
如果按上一份的结论去设计知识层，会漏掉 train 上最大的一块。

---

# 第二部分　train 分析（414 题，198 题错）

## 2.0 先看一个决定性的分布差异

| | en_dev（58 错） | en_train（198 错） |
|---|---|---|
| pred 与 gold **形状完全相同**（纯数值差） | 26（45%） | **120（61%）** |
| 仅行数不符 | 23 | 42 |
| 列数不符 | 7 | 32 |
| pred 返回空结果集 | 6 | 11 |
| pred 执行报错 | 2 | 4 |

**train 上六成的错题，SQL 结构是对的——行数列数都对，只是数值不同。**
dev 的错误重心在"计划/语义"，train 的错误重心在"口径/常量/形态"。

这直接推翻了一个可能的推断：不能把 dev 的断点分布外推到 train。
两个 split 考的不是同一件事。

## 2.1 断点 A｜库的实际内容没被核对（最硬、最可程序化）

这一类的共同点：**模型按 schema 的字面命名推断，从不回库看一眼实际值。**

### A-1 列的实际存储格式（formula_1 #158–#161，4 题）

`drivers.dob` 的实际值是 `'07/01/1985'`（DD/MM/YYYY 文本，我已查库确认）。
`strftime('%Y', dob)` 对这种字符串返回 **NULL**。

**但模型知道格式。** #158 的 plan 第 1 步原文：

> retrieving the `dob` column **(format DD/MM/YYYY, e.g., 07/01/1985)**

declarations 的 anchor 也写着 `"date of birth of the driver as stored (DD/MM/YYYY format)"`。
然后 SQL 写的是 `strftime('%Y', dob)`。

**这一条是整份分析里最有价值的单点发现。** 模型不缺这条知识——它查到了、写进了
plan、写进了声明槽位，然后在生成 SQL 时把它丢了。
**知识注入对这一类是无效的；需要的是"声明 ↔ SQL 一致性校验"。**
它与 dev #3（锚写对、算式用另一假设）是同一个断点，但这里更干净：#3 还能辩解成
两个假设并存，#158 是明确写下的事实与 SQL 直接冲突。

### A-2 选了一张空表（formula_1 #179 #184 #185 #186 #187，5 题）

"lap time" → 模型一律 `JOIN lapTimes`。已查库：**`lapTimes` 有 0 行，
`results` 有 23777 行**，gold 用的是 `results.milliseconds`。
五题 pred 全部返回空结果集。

模型的选择在**词法上完全正确**（lapTimes 字面就是"单圈时间"），
它只是从未问过"这张表里有数据吗"。这是一个纯程序可查的检查，成本近乎零。

### A-3 字面值不是库里的值（formula_1 #194 #195 #197 #199 #200 #202，6 题）

模型写 `country = 'United States'` / `'United Kingdom'`，
库里存的是 `'USA'` / `'UK'`。

**M2 的 C3 检查器结构上抓不到这一类**，我验证了原因：

- `_c3_literal_neighbors` 用 `difflib.get_close_matches(cutoff=0.6)` 找近邻；
- 实测 `'United States'` 对 `circuits.country` 全部取值的近邻列表是 **空**
  （全称与缩写的编辑距离恰好很低），`'United Kingdom'` 同样为空；
- 找不到近邻就静默放行（这是当初"宁缺毋滥"的设计选择）。

`country` 列在 formula_1 里唯一属于 `circuits`，所以"列名唯一"那道门是过的——
**卡住的就是 difflib 这一步**。这是一个具体、已验证、可改的实现缺口。

### A-4 不可解的一类：库里两个字面值都存在（bike_1 #34–#37，4 题）

"November 12th, 2014" → gold 写 `"12/11/2014"`（D/M），
但同一个库同一批题里 gold 又写 `"8/30/2013"` 表示 8 月 30 日（M/D）。
已查库：`12/11/2014` 和 `11/12/2014` **各有 5 行，都存在**。

所以这一类**值画像也救不了**——两个候选都命中，无从判别。
计入 benchmark 噪声。区分 A-3（可查，0 行）和 A-4（不可查，都非 0）很重要：
只有前者值得投入。

### A-5 实体名用库内拼写，数值用题面给定值

两条方向相反的约定，模型两条都没遵守：

- driving_school #108/#109：题面写 "Damon Sanford"，**库里是 `Dameon`**，
  gold 用库内拼写。模型信了题面。
- formula_1 #183/#197、bike_1 #15、customers #206/#207：题面给出
  "the two racing circuits in Japan" / "666 which is the average" / "10 races"，
  **gold 直接用题面的字面数字**，模型回库重算。

一句话：**专名以库为准，数值以题面为准。**

### A-6 同一个值分布在两列（wine_1 #398–#401，4 题）

已查库：`wine.Grape` 里是 `'Cabernet Sauvingnon'`（库里就拼错了），
`wine.Name` 里是 `'Cabernet Sauvignon'`（拼对）。
模型选了 `Grape` 列并**正确使用了库内的错拼值**（值链接做对了），
gold 选的是 `Name` 列。这不是拼写幻觉，是**列选择**——两列都能匹配时无从判别。

## 2.2 断点 B｜计算口径的约定（train 的主体）

### B-1 年龄公式（driving_school 为主，26 题相关）

gold 在 train 全域用同一个整数公式：

```sql
strftime("%Y",B) - strftime("%Y",A) - (strftime("%m-%d",B) < strftime("%m-%d",A))
```

模型用 `julianday(...)/365.25`（浮点）或省掉月日修正。

**测得**：gold 用该公式的错题 26 题，其中 17 题 pred 用了不同公式。
**但对照组说明不能把话说满**：gold 用该公式而判**对**的题有 12 道，其中 9 道
pred 也用的不同公式却仍然判对。
所以准确的说法是：**公式不一致是这 17 题的直接分歧点，但不一致本身不必然致错——
只有当两式在该数据上取值不同（跨生日、需要取整）时才致错。**

### B-2 单位换算常数的精度（跨三个库，≥12 题）

| 概念 | gold | pred | 题号 |
|---|---|---|---|
| 磅→千克（BMI） | `0.45` | `0.453592` / `1/2.20462` / 省略 | soccer #314–#317 #351 #358–#361 |
| 英里→公里 | `1.609344` | `1.60934` | bike #30–#33 |
| 英寸→毫米 | `25` | `25.4` | bike #34–#37 |

**模型每一次都比 gold 更精确，每一次都因此判错。**
这不是知识缺失，是"该用哪个约定值"的规约缺失。

### B-3 领域术语 → 列的映射（soccer_1，≥6 题）

| 题面说法 | gold 的列 | pred 的列 |
|---|---|---|
| "passing without conceding the ball" | `dribbling` | `short_passing`(+`ball_control`) |
| "catching the ball clean and positioning for saves" | `positioning + gk_handling` | `gk_handling + gk_positioning` |
| "accuracy when shooting from inside the penalty area" | `penalties` | `finishing` |
| "awareness of the position of teammates" | `vision` | `positioning`（#341） |

第二行尤其值得记：gold 用的是场上球员的 `positioning`，不是 `gk_positioning`——
**模型的选择才是合理的**。这些映射无法从英文推出，只能查表。

### B-4 多版本快照表的取值口径（soccer_1，测得 20 题）

`Player_Attributes` 每个球员有多条带日期的快照。

- gold 的固定写法：`MAX(<表达式>) ... GROUP BY player_name` ——取**全历史最优**
- pred 的固定写法：`ROW_NUMBER() OVER(PARTITION BY ... ORDER BY date DESC)`
  或 `JOIN (SELECT MAX(date) ...)` ——取**最新一条快照**

**测得**：soccer_1 的 31 道错题里 20 道 pred 走了"最新快照"路线；
而 21 道判对的题里只有 3 道走这条路线。
走这条路线的题 20 错 3 对（≈87% 错），soccer_1 整体错误率 60%。信号很强。

这与 dev 的 Age 锚是**同一个问题的行级版本**：哪一行代表"当前值"。
模型的选择（最新）更符合直觉，Archer 的选择（全历史聚合）是约定。

### B-5 比较基准的作用域（跨库，≥6 题，方向不定）

- bike #13：`WHERE ... start_station = X` 只作用于**求平均的子查询**，主查询不加
- bike #47：占比的分母是 `WHERE city='San Francisco'`，不是全表
- driving_school #136：分母是 `COUNT(*) FROM Customers`（全体），不是有课记录的
- dev #60–#63：分子取子集最大，分母取**全库**最小

四例里 gold 两次取窄、两次取宽。**这不是可学的 gold 规则，是模型的系统性盲区**：
模型从不显式判定限定语的作用域，默认延续上文，方向对了是运气。

### B-6 严格 vs 非严格、绝对值、取整

- `>` vs `>=`：formula_1 #181 #183 #188 #189 #191（gold 用 `>`）——
  但 #204–#207 gold 又用 `>=`。**gold 自身不一致**，不可学。
- `ABS()`：gold 的 "difference" **一律取绝对值**（bike #34–#37、soccer #318–#323
  #340 #341 #352、dev #170）。模型经常给带符号的差。这条是一致的，可学。
- `CAST(... AS INT)`：hospital #224–#227、dev #100/#101。可学。

## 2.3 断点 C｜输出形态（train 32 题列数不符）

三种反复出现的形态，都与推理无关：

**(a) 宽表 vs 长表** —— 三个库同构：
dev #24–#27（`highest_name, n_highest, lowest_name, n_lowest` 一行四列）、
soccer #330/#331（`best_team, lowest_team`）、wine #394–#397（`tons_red, tons_white`）。
模型一律输出长表（每个实体一行）。

**(b)「A 占 B 多少」= 一个比值，不是两个计数**
hospital #236 #244、riding_club #263、wine #363：
题面 "How many treatments with a cost higher than 1000 account for the total
number of treatments?"（中文"占…的多少"的直译），gold 输出**一列比值**，
模型输出 2–3 列（计数 + 总数 + 百分比）。
反过来 bike #4–#7 问"共多少 + 少多少"，gold 又**只输出差值一列**。
**gold 的输出列数无法从英文题面推出。**

**(c) 列顺序** —— bike #20/#21：形状都是 70×4，sim 0.77，
差别只是 gold 是 `MAX, MIN, diff` 而模型按题面顺序写 `MIN, MAX, diff`。
题面说的是 "minimum duration, maximum duration"——**模型跟着题面走反而错**。

## 2.4 断点 D｜反事实的赋值语义（跨库，高价值）

Archer 的反事实 gold 有一个**统一模板**：

```sql
SELECT ... FROM (
  SELECT <字段>, <假设值> AS X FROM T WHERE <条件>
  UNION ALL
  SELECT <字段>, X FROM T WHERE NOT <条件>
)
```

即：**对满足条件的每一行逐行赋同一个值，其余行原样保留。**
在 world_1、driving_school、wine_1、customers、soccer_1 全部出现。

模型的偏离有两种：

- **总量分摊**：dev #98（"总人口是 103000" → 按份额分摊）、
  wine #373（"每类产量各 +100 箱" → 把 100 摊到各行）
- **改成过滤**：bike #11（`WHERE dock_count = 2*...+5`）——
  这正是 M2 的 C2 检查器要抓的，检查器在别的题上确实报了
  "疑似被写成了过滤条件"，说明规则存在但覆盖不全

## 2.5 无法赢的题（gold 本身错或信息已丢失）

读到的确凿例子（**下界**，只统计我逐条看过并能指出错在哪的）：

| 题号 | 问题 |
|---|---|
| formula_1 #192 #193 | gold 的 `num_matches` 统计的是 **Christijan Albers**，题问 Lewis Hamilton |
| riding_club #300 #301 | "before the 21st Century" → gold 写 `Start_year < 2006` |
| wine_1 #407 #409 | 题问"哪些酒庄"，gold 返回一个**百分比** |
| formula_1 #159 | "how much older … five years later" → gold 与 #158 逐字相同（答的是年龄不是差值） |
| formula_1 #177 | 题问 "the sum, and difference"，gold 输出的是两个分量和差，没有和 |
| bike_1 #38 #39 | 题面没提单位，gold 静默把英里换成米 |
| soccer_1 #321 | 题面 "rating **of** 70"，gold 用 `< 70`（沿用 #320 的"below 70"） |
| soccer_1 #351 | 题面没说 top-1，gold 有 `LIMIT 1` |
| soccer_1 #355 | "surpassing **by two**" → gold 用 `> 2.0 *`（两倍） |
| bike_1 #34–#37 | 日期格式两解且库里都存在（见 A-4） |

**≥15 题**。198 题里这个量级不能忽略：它给 EX 设了天花板，
也意味着任何"逐题追分"的努力有 7%+ 是打在空气上。

## 2.6 train 断点分布（人工判读，取最早断点，不重叠）

只对我逐条读过的题计数；把 8 个库全部错题按最早断点归一次。

| 断点 | 题数 | 占比 |
|---|---|---|
| A 库内容未核对（格式/空表/字面值/列选择） | 23 | 12% |
| B 计算口径（年龄公式/常数/术语映射/快照/作用域/取整） | 78 | 39% |
| C 输出形态（宽长表/列数/列序） | 47 | 24% |
| D 反事实赋值语义 | 18 | 9% |
| E 真正的推理错误（读题、计划自相矛盾、SQL 写错） | 17 | 9% |
| F gold 错误 / 信息已丢失 | 15 | 8% |

> 计数为人工判读，一题只记最早断点，与 §2.0 的形状统计口径不同（那是机器测的）。

**读法：真正意义上的"思维链推理错了"只有 17 题（9%）。**
其余 91% 是"想对了但没按 Archer 的约定写"，或者根本没得写。
这与 dev 恰好相反——dev 的 B 段（计划推理）占 36/58（62%）。

---

# 第三部分　这对后续设计意味着什么

## 3.1 dev 和 train 必须分开谈，不能合并结论

| | dev | train |
|---|---|---|
| 主瓶颈 | 时间锚点臆断（推理层） | 口径与输出形态（约定层） |
| 需要的东西 | 库画像（列语义锚） | 规约表 + 一致性校验 |
| 真推理错误占比 | 62% | 9% |

上一份文档给出的"知识层第一优先级是列语义锚"，**在 dev 上成立，在 train 上不成立**。
train 上锚类问题只有 soccer 的快照选取（20 题）勉强同族。

## 3.2 三条按性价比排序的判断

**第一，最高杠杆的不是知识，是"声明 ↔ SQL 一致性校验"。**
#158 是决定性证据：模型把 `dob` 是 DD/MM/YYYY 写进了 plan **和** anchor，
SQL 仍写 `strftime('%Y', dob)`。dev #3 同构。
知识注入对这一类零收益——事实已经在上下文里了，断的是执行。
现有 C4 只查"每个时间语义列有没有 anchor 键"，不查"anchor 的内容与 expr 是否相容"。

**第二，程序可查的库画像（表行数、列实际格式、字面值存在性）成本极低。**
A-2（空表，5 题）、A-3（字面值，6 题）、A-1（格式，4 题）合计 15 题，
全部可由一段只读查询判定。**C3 的 difflib 近邻是已验证的缺口**：
全称↔缩写的字符相似度天然低于 0.6，改成"值不存在就直接告警（不依赖找到近邻）"
即可覆盖，代价是可能多报（空结果有时正是题意）。需要权衡，但方向明确。

**第三，输出形态（47 题，24%）零知识需求，但也零可推导性。**
宽表 vs 长表、"占比"给一列还是三列、列顺序——这些**无法从英文题面推出**，
只能从 train 蒸馏成规约。这是 train 相对 dev 独有的、最大的一块，
而且它不污染知识层的消融变量（可以作为独立的一档来做）。

## 3.3 一条必须先定的方法论问题

B-2（单位常数）、B-6（`>` vs `>=`）、2.5（gold 错误）说明：
**一部分分数只能靠"猜 Archer 的约定"拿到，而不是靠把题做对。**
BMI 用 0.45 而不是 0.453592、英寸乘 25 而不是 25.4——这些是刷分，不是能力。

需要先决定这些算不算在 M3 的范围内。如果算，得在文档里明确标注哪些提升来自
约定对齐、哪些来自能力提升，否则 M2/M3 的消融对比会被这部分噪声污染，
"DSL 中间层的价值"这个中心论据会站不住。**我的建议是把约定对齐单列一档、
单独计分**，让它不进入 DSL 消融的对比轴。

---

# 局限

1. **train 198 题我逐条读了 plan/SQL 的约 130 题**（formula_1、soccer_1、bike_1、
   driving_school、customers 全读，riding_club、wine_1、hospital_1 读了 2/3）。
   §2.6 的分布对未逐条读的部分是按同库同型外推的，误差主要落在 B 与 C 之间。
2. **§2.5 的"无法赢"是下界**，只统计我能明确指出 gold 错在哪的。真实数量更高。
3. **本文档的分类是单人判读，无第二人复核。** 争议最大的是 B-5（作用域，
   题面英语确实两可）和 F（判定 gold 错误，带主观性）。
4. §2.0 与 §2.6 的数字口径不同，**不可相加**：前者是机器测的形状统计（覆盖全部
   198 题），后者是人工的最早断点归类。
5. 未做的：train 上的 zh split、非 thinking 骨干的对照。
