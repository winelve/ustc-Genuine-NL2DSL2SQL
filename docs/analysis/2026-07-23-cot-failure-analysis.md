# 思维链失效分析：错在哪一步、错的那个推断是什么

> 分析对象：`dslsql-pro-thinking`，en_dev 58 道错题逐条通读
> 材料：`predictions/m2-dslsql/dslsql-pro-thinking_en_dev.trace.json` 的
> `plans` + `candidates[].checks.declarations`，对照 gold SQL
> 方法：**人工通读**。本文档的每条结论都附原文引用，可逐条复核。
> 日期：2026-07-23
>
> ⚠️ **已被复审，有三处修正**：见 `2026-07-23-train-cot-failure-analysis.md` 第一部分。
> 摘要：引文全部核对属实；但 (1) §一·发现 2 的"每题现编"说法有误，实际是
> "锚被题面里最近的时间实体吸走"这条稳定规则；(2) §三 的计数表不是划分且从未覆盖
> #6 #44 #46 #92–#95 #98 #102 #103 共 10 题；(3) 这 10 题含三个本文档未命名的错因
> （线性 vs 复合外推、比值的平均 vs 总量的比值、反事实集合赋值语义）。

## 本文档与 `2026-07-23-error-taxonomy.md` 的关系

那份是**统计性的**：用检测器量化 gold 与 pred 的可观测差异，回答"有多少题、差在哪里"。
本份是**因果性的**：读模型自己写的推理过程，回答"它当时在想什么、哪一步想错了"。
两份互补，结论不冲突；有分歧处以本份为准（本份基于模型原话，检测器只看结果差异）。

---

## 一、三个贯穿全局的发现

### 发现 1：模型自己知道它在猜，并把猜的内容写进了 plan

这是最重要的一条。模型**反复、显式地**在 plan 里写出它的不确定性：

**#2**（plan 第 2 步原文）：
> compute the age the singer would have had in 2001 using the formula
> `age_in_2001 = Age + (2001 - CAST(Song_release_year AS INTEGER))`
> **(This assumes `Age` represents the singer's age at the original `Song_release_year`,
> so birth year = `Song_release_year` - `Age`)**

**#5**（plan 第 3 步原文）：
> retrieve each singer's `Name` and `Age`
> **(using the age as stored in the table, because there is no birth year to compute
> an age at concert time; the stored age is the only available value)**

**#12**（plan 第 3 步原文）：
> **(Assume `Age` reflects the singer's age in the concert year *or* at the time
> the data was recorded.)**

三条都是模型主动标注的假设。**#12 甚至用了 "or"——它识别出了两种可能，写了出来，
然后随手挑了一个。** #5 更严重：模型的结论是"**数据不足所以算不了**"，于是放弃换算——
但它没想到 `Age` 本身就编码了出生年（`birth = now - Age`）。

**含义**：模型不是"没想到"，是"想到了、卡住了、然后蒙一个继续走"。
它缺的是**那一条能定夺的信息**，不是推理能力，也不是提示它"想全面点"。

### 发现 2：同一个列的锚点，模型在六道题上给出了四个互相矛盾的答案

`concert_singer.singer.Age` 的 `anchors` 声明原文：

| 题号 | 模型声明的锚 |
|---|---|
| #3 | "current age of the singer as stored in the database" |
| #4 | "age of singer at time of song release (year singer.Song_release_year)" |
| #13 | "age at the concert year (2015, the year of 'Home Visits')" |
| #14 | "age of the singer in the year of the song's release" |
| #15 | "age of the singer at the time of the original Home Visits concert" |
| #20 | "the singer's age at the time of the concert" |

**同一个库、同一个列、四种锚。** 这不是"系统性地理解错了"（那会是稳定偏差），
而是**每道题现编一个**。#13 甚至编出了一个具体年份 `2015` 并当成事实。

**含义**：这是"知识缺失"最硬的证据。如果模型有稳定的错误信念，注入知识是"纠正"；
它这样飘忽，说明**根本没有依据可循**，注入知识是"从无到有地提供依据"。
这也解释了为什么换笼统提示词无效——飘忽的来源不是表述方式，是缺锚。

### 发现 3：#24/#25 vs #26/#27 是一组天然对照实验，直接证明"触发"假说

四道题问的是同一件事：**哪个体育场的 average attendance rate 最高/最低**。

| 题号 | 题面是否提到 capacity | 模型的做法 | 对错 |
|---|---|---|---|
| #24 | 否 | plan 第 1 步："Find the minimum value of the **`Average`** column" | ❌ |
| #25 | 否 | 同上，直接用 `Average` 排序 | ❌ |
| #26 | **是**（"a tenth of the capacity of Hampden Park"） | plan 第 3 步："`rate = Average / capacity`" | ❌（错在别处） |
| #27 | **是**（"one-tenth the capacity of Hampden Park"） | plan 第 3 步："`Average / effective_capacity`" | ❌（错在别处） |

**同一个模型、同一个库、同一个概念**：题面不提 capacity 就用 `Average`，
题面提了 capacity 就正确算 `Average / Capacity`。

**模型知道 attendance rate = 出勤/容量。它只是需要有人把 `Capacity` 拉进视野。**
#26/#27 最终仍然答错，但错在输出形态（gold 输出宽表四列），**比率算对了**。

这是本次分析中对知识层设计最有价值的一条证据：
**知识层的作用是"把候选摆到眼前"，不是"教它公式"。**

**加剧因素——列名的字面吸引力**：库里恰好有个列叫 `Average`，题面问
"average attendance rate"，模型直接字面匹配。#33 同样中招
（plan 第 1 步 "sort by `Average` descending"）。

---

## 二、按思维链断点分类

链条：**读题 → plan → declarations → SQL**。定位每道题**最早**断的那一环。

### 断点 A｜读题阶段：题意解析错误（plan 之前就偏了）

#### A-1 时间状语被当成定语

**#0 / #1**——问 "List the name and age of each singer **at the time of the release of
the song "Gentleman"**"

模型 plan：
> 1. Filter the singer table to rows where `Song_Name` is 'Gentleman'.
> 2. Output the `Name` and `Age` columns.

gold：`SELECT Name, Age + (release_year) - now FROM singer`（**没有 WHERE**）

**模型把 "at the time of the release of Gentleman" 读成了"Gentleman 这首歌的歌手"
（定语），gold 读成"在 Gentleman 发行的那个时点"（时间状语，作用于所有歌手）。**

⚠️ **此处 gold 的读法本身可争议**：英文原句两种读法都成立。但 Archer 一致采用
"时间状语"读法（#4/#5/#48/#49 同构），**这是可以从 train 蒸馏的题式约定**。

#### A-2 实体类型误判 + 未做值链接核对

**#68 / #69 / #70 / #71**——"a population at least twice that of **Kang-won**"

模型 plan 第 1 步：
> Find the population of **the city named 'Kang-won'** in the `city` table

**`Kang-won` 是 `city.District` 的值，不是 `city.Name` 的值。** 该查询返回空集。
gold：`SELECT SUM(Population) FROM city WHERE District = "Kang-won"`
——District 含多个城市，因此还必须 `SUM`。

**断点**：模型看到一个专名就默认它是"名字"，没有回库核对这个值出现在哪一列。
**连带错误**：列选错 → 基数从"多城市"变成"单城市" → `SUM` 也丢了。

#### A-3 题面词汇的口径约定

**#60 / #62**——"the country where **the majority of people speak English**"

模型 plan：`WHERE Language = 'English' AND Percentage > 50`（字面理解：过半）
gold：`MAX(Percentage)` 分组取最大（**plurality，说的人最多**）

**Archer 把 "majority speak X" 一律解释成 "X 是该国第一语言"，不是 >50%。**
这是标注约定，字面英语支持模型的读法。

---

### 断点 B｜plan 阶段：推理本身错了

#### B-1 锚点臆断（最高频，19 题）

模型知道要做时间换算，但**锚点是编的**。见 §一·发现 2 的六条声明原文。

具体形态：

- **#2**：显式假设 `Age` = 发行当年年龄 → `Age + (2001 - release_year)`
  gold：`Age + 2001 - now`
- **#20 / #21**：`birth_year = concert.Year - Age`（锚在演唱会年）
  gold：`birth_year = now - Age`（锚在当前）
- **#13**：锚编成 "2015, the year of 'Home Visits'" → `Age + 20`
  gold：`Year - now + Age + 20`
- **#10**："how many years has it been **since** the earliest concert"
  模型算 `MAX(year) - MIN(year)`（库内跨度），gold 算 `now - MIN(year)`（至今）
  ——plan 第 5 步自己引入了题面没有的 "latest year"

**共同结构**：题目要求"某时点的年龄/年数"，模型必须知道 `Age` 锚在哪才能换算。
它不知道，于是从题面上下文里就近抓一个年份当锚。

#### B-2 推理放弃：判定"数据不足"

**#5**（plan 原文，见 §一·发现 1）：模型判断"没有出生年 → 算不了 → 用存储值"。

**这一步的推理是错的**：`Age` 是当前年龄，`now - Age` 就是出生年。
模型缺的一环恰恰是"`Age` 锚在当前"这条信息——**没有它，放弃是合理的**。

#### B-3 派生指标的定义被反事实覆盖

**#74 / #75 / #90 / #91**——"GNP growth rate"

全 104 题中**只有这 4 题的 SQL 完全没引用 `GNPOld`，且 4 题全错**。

- 无反事实时（#80）或假设不改 GNP 时（#58/#82/#86），模型都正确用了
  `(GNP - GNPOld)/GNPOld`
- 一旦假设修改的目标就是 GNP 本身，模型把 growth 重新解释成
  "假设造成的变化"：`SUM(调整后GNP)/SUM(原GNP) - 1`，**绕开 `GNPOld`**

**#58 的 plan 是反例，证明模型本来会做对**：
> 3. compute the growth rate as (adjusted GNP – `GNPOld`) / `GNPOld`

**断点**：不是不知道公式，是**反事实语境劫持了已有的正确定义**。
→ 知识条目必须带锚：`growth ≜ (GNP-GNPOld)/GNPOld，锚列 GNPOld，
反事实修改 GNP 时锚不变`。

#### B-4 具名比率退化成单列（列名字面吸引）

**#24 / #25 / #33 / #40 / #41**——"average attendance rate" → 直接用 `Average` 列。
见 §一·发现 3 的对照实验。

#### B-5 比较基准的范围

**#60 / #61 / #62 / #63**——"ratio between the highest and lowest population density"

模型：`MAX(density) / MIN(density)`，两者都取自**筛选后的英语国家子集**
gold：分子是子集最大值，**分母是全库最小密度**（`FROM country` 无语言过滤）

**断点**：题面的 "lowest" 作用域不明，模型默认延续上文的筛选条件，gold 不延续。

#### B-6 集合否定的作用域

**#65 / #67**——"countries with **non-Arabic** official languages"

模型：`JOIN countrylanguage WHERE IsOfficial='T' AND Language != 'Arabic'`
（有**至少一个**非阿拉伯语官方语言 → 保留）
gold：`Code NOT IN (SELECT ... WHERE Language='Arabic' AND IsOfficial='T')`
（有阿拉伯语官方语言 → **排除**）

对于同时有阿拉伯语和英语官方语言的国家，两者结论**相反**。
**断点**：否定作用在"存在一个非X"还是"不存在X"上，题面英语两可。

#### B-7 自加防御性过滤，改变了聚合基数

**#56 / #58 / #65 / #67 / #73 / #88 / #89**——模型习惯性加
`WHERE GNPOld IS NOT NULL AND GNPOld > 0`（plan 里明写"to avoid division by zero"）。

gold 不加，靠 SQL 的 NULL 传播语义自然处理。当分母涉及 `SUM(Population)` 一类
跨列聚合时，**预过滤改变了行集**，结果不同。

**断点**：良好的工程习惯（防除零）与评测口径冲突。

---

### 断点 C｜plan → declarations：声明写对了，算式没跟上

**#3** 是最干净的样例：

```
plan  : 计算 `Age - (original_year - 2001)`
DECL  : anchors = {"Age": "current age of the singer as stored in the database"}  ← 对的
expr  : Age - (CAST(Song_release_year AS INTEGER) - 2001)                          ← 用的另一个假设
```

**如果 `Age` 真是当前年龄，2001 年的年龄应该是 `Age - (now - 2001)`，
而不是 `Age - (release_year - 2001)`。声明与算式互相矛盾。**

模型在声明槽位里写对了锚，但没有回头用这个锚去修正 plan 里已经定好的算式。

**这正是 M2 声明层的价值与局限的交点**：声明层把假设**挖了出来**（这是 M2 的贡献），
但没有任何机制去**核对声明与算式是否自洽**（这是 M3 该补的）。
C4 只查"每个时间语义列有没有 anchor 键"，不查"anchor 的内容与 expr 是否一致"。

**反向样例 #4**：plan 完全没提年龄换算，declarations 阶段**自己补了**一个
`singer.Age + (concert.Year - singer.Song_release_year)`。
说明声明阶段比 plan 阶段"更警觉"，但锚仍然选错。

---

### 断点 D｜declarations → SQL：SQL 没执行声明的语义

**#31**——"if the "Week 2" concert was held there"

plan 第 3 步（**语义正确**）：
> add that concert to the set from step 2, **ignoring its actual Stadium_ID**.
> The final set is the **union** of concerts from step 2 and the 'Week 2' concert.

declarations（**漂移成改值**）：
```json
{"target": "concert.Stadium_ID", "where": "concert_Name = 'Week 2'",
 "value": "(SELECT Stadium_ID FROM stadium WHERE Name = 'Somerset Park')"}
```

SQL：`CASE WHEN concert_Name='Week 2' THEN (Somerset的ID) ELSE Stadium_ID END`

gold：`WHERE (D.Name = "Somerset Park" OR A.concert_Name = "Week 2")`——**并集**

**断点**：plan 说"并集"，声明和 SQL 做成了"改值"。
两者在本题上不等价（还涉及空组补零）。

---

### 断点 E｜全链路语义正确，输出形态不合口径

这一类**没有任何思维链错误**，模型从头到尾想对了。

- **#100 / #101**：`IndepYear + LifeExpectancy` = `2001.2`，gold `CAST(... AS INT)` = `2001`
- **#80**：正确取到 `Japan`，但多输出了一列 `Reduction`
- **#56 / #58**：正确算出 growth rate，但 gold 只要 `Name` 一列，pred 输出两列
- **#24–#27**：gold 是**宽表**（`highest_name, n_concerts_highest, lowest_name,
  n_concerts_lowest` 四列一行），pred 是**长表**（每个体育场一行）

**断点**：不在推理，在"答案应该长什么样"的约定。**零知识需求。**

---

## 三、断点分布（en_dev 58 题）

一道题可能有多个断点，此处记**最早**的那个。

| 断点 | 子类 | 题数 | 例 |
|---|---|---|---|
| A 读题 | 时间状语误读 | 4 | #0 #1 #48 #49 |
| A 读题 | 实体类型误判 | 4 | #68 #69 #70 #71 |
| A 读题 | 词汇口径（majority=plurality） | 2 | #60 #62 |
| B plan | **锚点臆断** | **15** | #2 #3 #12 #13 #14 #15 #20 #21 #23 #10 … |
| B plan | 推理放弃（判定数据不足） | 3 | #5 #7 #51 |
| B plan | 具名比率退化成单列 | 5 | #24 #25 #33 #40 #41 |
| B plan | 派生指标被反事实劫持 | 4 | #74 #75 #90 #91 |
| B plan | 比较基准范围 | 4 | #60 #61 #62 #63 |
| B plan | 集合否定作用域 | 2 | #65 #67 |
| B plan | 自加防御性过滤 | 3 | #73 #88 #89 |
| C plan→decl | 声明与算式矛盾 | 3 | #3 #4 #14 |
| D decl→SQL | 语义漂移 | 1 | #31 |
| E 输出形态 | **无思维链错误** | **8** | #100 #101 #80 #56 #58 #26 #27 #62 |

> 计数为人工判读，含重叠（如 #62 既是词汇口径又是输出形态）；
> 与 taxonomy 文档的检测器计数**不应直接相加**。

**读法**：

- **B 段（plan 推理）占 36/58**——绝大多数错误发生在计划阶段，SQL 只是忠实执行。
  这与 M1 的结论一致（"sqlgen 忠实执行错误的 plan"）。
- **锚点臆断单项 15 题**，是最大的单一断点。
- **E 段 8 题完全没有思维链错误**，纯输出规约。

---

## 四、对知识层设计的直接输入

按断点反推需要什么。**这一节是设计文档的输入，不是设计本身。**

| 断点 | 需要的东西 | 形态 |
|---|---|---|
| B 锚点臆断（15） | `Age` 锚在当前日期；"since X"锚在当前 | **列语义锚表**（库画像） |
| B 推理放弃（3） | "存量 Age ⇒ birth = now − Age" | 同上（有锚即可推） |
| B 比率退化（5） | `Average`/`Capacity` 是一对比率 | **候选指标表**（schema 派生） |
| B 反事实劫持（4） | growth 锚在 `GNPOld`，假设不改锚 | **带锚的指标定义** |
| A 实体误判（4） | `Kang-won` 出现在 `District` 列 | **值链接**（C3 扩展，程序可做） |
| A 时间状语（4） | Archer 的题式读法约定 | **题式约定**（可从 train 蒸馏） |
| A 词汇口径（2） | majority = plurality | 同上 |
| B 否定作用域（2） | "non-X" = 排除有 X 的 | 同上 |
| B 防御性过滤（3） | 不要预过滤 NULL | **输出/写法规约**（提示词） |
| B 基准范围（4） | 比较基准的默认作用域 | 题式约定 |
| C 声明与算式矛盾（3） | 无需知识——**需要一致性校验** | **C5 校验器** |
| E 输出形态（8） | 无需知识——**需要输出规约** | 提示词 + 校验 |

**三条判断**：

1. **锚是最大的单一缺口（15+3=18 题）**，且模型自己已经把"我在猜锚"写进了 plan。
   知识层的第一优先级是**列语义锚**。
2. **#26/#27 证明"摆出候选"就够，不需要教公式**（发现 3）。候选指标表按 schema
   自动派生即可，不必人工编纂。
3. **11 题（C 段 3 + E 段 8）根本不需要知识**，只需要校验器和输出规约。
   这部分应该先做——成本最低，且不污染知识层的消融变量。

---

## 五、局限

1. **只读了 en_dev 的 58 题。** train 的 198 题未逐条读（数量过大），
   其断点分布可能不同——尤其 train 有 dev 没有的单位换算、世界常识常量类。
2. **断点定位是人工判读**，无第二人复核。争议较大的是 A-1（gold 读法本身可争议）
   和 B-5/B-6（题面英语确实两可）。
3. **计数含重叠**，不可与 taxonomy 文档的检测器计数相加。
4. **未区分 benchmark 噪声**。A-1 一类"gold 读法可争议"的题，
   严格说是标注约定问题而非模型缺陷；本文档按"模型没学到该约定"计入。
