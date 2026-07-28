# 消融实验结果（NL2DSL2SQL @ Archer）

> 消融结果的**干净出口**：命名约定、结果表、待补清单。开发时间线与决策论证在
> `docs/PROGRESS.md`（叙述视图），本文件是**结果视图**。
>
> 数字口径：EX/VA 直接取自 `results/**/*.json`，可用 `archer_eval` 复算；
> 翻转数与 McNemar p 由各 results 的逐题 `match` 字段两两对比算出（见 §8 复算方式）。
> 主指标 EX = 执行结果与 gold 一致的比例；VA = SQL 可执行比例。
>
> **本文件只管 Archer。** BIRD 侧的数据版本、提示词、偏离清单与分数在
> `docs/BIRD.md` —— 那边报的是 BIRD 官方 EX（`set(rows)` 相等，无 VA），
> 与本文件的 VA/EX/SIM 是两套独立口径，**不进同一张表**。

---

## 1. 命名与文件约定

模型名 = **`<骨干>[-t]-<配置>`**，让"缺哪个实验"从名字自明。

| 段 | 取值 | 含义 |
|---|---|---|
| 骨干 | `flash` / `pro` | DeepSeek-v4 两档；换厂商时加新 token |
| `-t` | 有/无 | 有 = 开 thinking；无 = 关（贪心可复现） |
| 配置·骨架 | `direct` → `plan` → `plandsl` → `dsl` | 直出 / +规划 / 规划+DSL声明 / 声明（去规划） |
| 配置·附加 | `prof` `force` `conv` `chk` `cchk` | 库画像 / C5a强制表态 / 约定表 / C5b锚一致+C6比率检查 / C7约定检查 |

**文件路径**：`predictions/<骨架>/<模型名>_<数据集>.json`（多阶段模型另附 `.trace.json`）；
`results/<骨架>/<数据集>_<模型名>.json`。骨架目录 = `direct/ plan/ plandsl/ dsl/ smoke/`。
数据集：`en_dev`(104) `en_train`(414) `zh_dev`(104) `zh_train`(414)。

**变体后缀**：`-v1`(旧提示词模板) `-bare`(plan 无反事实原则) `-n3`(n=3 投票) `-know`/`-type`(提示词消融) `-5q`(冒烟前5题) `-r0`(修复循环 0 轮＝去重试)。

---

## 2. 注册模型一览（旧代号 → 新名）

| 新注册名 | 旧注册名 | 类 | 组件签名 | 位置 |
|---|---|---|---|---|
| `pro-t-dsl-conv-chk` ★ | `m3dx-noplan-pro-thinking` | `ProTDslConvChk` | dsl+conv+chk | 主线·最终 |
| `pro-t-dsl-conv` | `m3dp-noplan-pro-thinking` | `ProTDslConv` | dsl+conv | 主线 |
| `pro-t-dsl` | `noplan-pro-thinking` | `ProTDsl` | dsl（去 plan） | 主线 |
| `pro-t-plandsl` | `dslsql-pro-thinking` | `ProTPlanDsl` | plan+dsl | 主线 |
| `pro-t-plan` | `plansql-pro` | `ProTPlan` | plan | 主线 |
| `pro-t-direct` | `deepseek-v4-pro-thinking` | `DeepSeekProThinking` | direct | 直出基线 |
| `pro-t-dsl-chk` | —（2026-07-24 新增） | `ProTDslChk` | dsl+chk | 主线·LOO（−conv） |
| `pro-t-dsl-conv-chk-r0` | —（2026-07-24 新增） | `ProTDslConvChkR0` | dsl+conv+chk, 修复 0 轮 | 主线·LOO（−重试） |
| `pro-t-direct-conv` | —（2026-07-24 新增） | `DeepSeekProThinkingConv` | direct+conv | 主线·LOO（−声明层） |
| `pro-direct` | `deepseek-v4-pro` | `DeepSeekPro` | direct | 直出基线 |
| `flash-direct` | `deepseek-v4-flash` | `DeepSeekFlash` | direct | 直出基线 |
| `flash-t-direct` | `deepseek-v4-flash-thinking` | `DeepSeekFlashThinking` | direct | 直出基线（未跑分） |
| `pro-t-plandsl-prof` | `m3a-pro-thinking` | `ProTPlanDslProf` | plandsl+prof | 存档 |
| `pro-t-plandsl-prof-force` | `m3b-pro-thinking` | `ProTPlanDslProfForce` | plandsl+prof+force | 存档 |
| `pro-t-plandsl-prof-force-chk` | `m3c-pro-thinking` | `ProTPlanDslProfForceChk` | plandsl+prof+force+chk | 存档 |
| `pro-t-plandsl-conv` | `m3dp-pro-thinking` | `ProTPlanDslConv` | plandsl+conv | 存档 |
| `pro-t-plandsl-conv-cchk` | `m3dc-pro-thinking` | `ProTPlanDslConvCchk` | plandsl+conv+cchk | 存档 |
| `first_table` | `first_table` | `FirstTableBaseline` | 哑基线（无 LLM） | 自检 |

"存档" = 带 plan 注知识的探索支，已被 no-plan 主线取代（多判负，保留以可复现）。

---

## 3. 主线消融阶梯（骨干 `pro` + thinking，en_dev n=104）

每步只动一个组件；EX/VA 取自 JSON，翻转/p 由逐题 `match` 复算。

| 配置 | 相对上一步 | EX | VA | 步进 Δ | 翻转 (+/−) | McNemar p |
|---|---|---:|---:|---:|:--:|---:|
| `pro-t-direct` | 基线（直出） | 40.38 | 100.0 | — | — | — |
| `pro-t-plan` | + plan 规划 | 40.38 | 100.0 | +0.00 | +8/−8 | 1.00 |
| `pro-t-plandsl` | + DSL 声明层 | 45.19 | 99.0 | +4.81 | +8/−3 | 0.23 |
| `pro-t-dsl` | **− plan（去规划）** | 52.88 | 99.0 | **+7.69** | +17/−9 | 0.17 |
| `pro-t-dsl-conv` | + 约定表 | 57.69 | 99.0 | +4.81 | +13/−8 | 0.38 |
| `pro-t-dsl-conv-chk` ★ | + C5b/C6 检查 | **63.46** | 100.0 | +5.77 | +11/−5 | 0.21 |

**累计（vs `pro-t-plandsl` 基线 45.19）**：→ `pro-t-dsl` +17/−9 (p=0.17)；
→ `pro-t-dsl-conv` +20/−7 (**p=0.019**)；→ `pro-t-dsl-conv-chk` **+22/−3，net +19，p=0.00016**。

机制要点（详析见 PROGRESS）：
- **去 plan 是最大单步（+7.69）**：plan 前站在 thinking 骨干上是负资产，下游越结构化越明显；
  +17 里 12 题是时间锚簇自愈。
- **约定 prose 的价值全在时机**：同一份约定在 plan 后面 ±0（见 §4 `plandsl-conv`=45.19），
  去 plan 后 +4.81——知识要抵达"尚未被约束的决策点"。
- **检查器 +5.77 主要来自 C6**（比率线索，靶子 #24/#25/#41 顶动转对，0 有害）；抖动约占净 +3。

---

## 3b. 满配 leave-one-out 消融（2026-07-24 立项，同日实测完毕）

对照 = 满配 `pro-t-dsl-conv-chk` 63.46。§3 是加法阶梯（从零逐步加），本节是减法
（从满配各减一个组件）；7 格里 4 格复用 §3 已有数，新跑 3 臂（2026-07-24）。
翻转/p 均为"满配 → 该臂"方向（+ = 该臂反超的题，− = 该臂丢掉的题）。

| 臂 | 注册名 | EX | VA | Δ vs 满配 | 翻转 (+/−) | McNemar p |
|---|---|---:|---:|---:|:--:|---:|
| 满配 | `pro-t-dsl-conv-chk` | 63.46 | 100.0 | — | — | — |
| 满配 − chk | `pro-t-dsl-conv` | 57.69 | 99.0 | −5.77 | +5/−11 | 0.21 |
| 满配 − conv | `pro-t-dsl-chk` | 56.73 | 99.0 | −6.73 | +7/−14 | 0.19 |
| 满配 − conv − chk | `pro-t-dsl` | 52.88 | 99.0 | −10.58 | +6/−17 | **0.035 ✅** |
| 满配 − 重试 | `pro-t-dsl-conv-chk-r0` | 52.88 | 99.0 | −10.58 | +5/−16 | **0.027 ✅** |
| 满配 − 声明层 | `pro-t-direct-conv` | 49.04 | 95.2 | −14.42 | +3/−18 | **0.0015 ✅** |
| 全裸 | `pro-t-direct` | 40.38 | 100.0 | −23.08 | +2/−26 | **0.00003 ✅** |

**判读（按写死的协议）**：

- **每个组件单独拿掉都掉分**，边际价值排序：声明层（−14.42）> 重试环（−10.58）
  > conv（−6.73）> chk（−5.77）。前两名单臂显著；conv/chk 两臂单独不显著
  （p≈0.19/0.21），但合并拿掉即显著（−conv−chk p=0.035），方向一致。
- **重试环是第二重要组件（p=0.027）**：关掉修复循环净丢 11 题。预期的 VA 回落
  没有发生（100→99.0，仅 1 题）——修复环的价值几乎全在**语义修正**
  （检查器顶动模型改口径），不在救非法 SQL。
- **声明层是最重要组件（p=0.0015）**：连同其校验/修复一起拿掉净丢 15 题，
  是 LOO 里最大且最显著的一刀——DSL 声明层的价值主张在减法方向上成立。
- **附加发现（修正既有叙事）**：conv 在裸直出上 +8.65（+16/−7，p=0.093）——
  **约定文本不依赖声明层也有效**。"同一份知识 × 注入位置"三点曲线定格为：
  plan 后 **±0** / 声明层前 **+4.81** / 裸直出 **+8.65**。结论从
  "知识需要声明层才能绑定"修正为"**知识的阻断器是 plan 前站**：只要抵达
  未被锁死的决策点就有效"。声明层的价值独立于知识存在
  （direct-conv 49.04 → dsl-conv 57.69，+8.65）。
- 基础修复环（C1–C4，不含 chk）单独的边际：r0 → dsl-conv +11/−6 净 +5
  （p=0.33），正向但单步不显著。
- **诚实口径**：满配 63.46 含约 3 分重跑抖动（§3），各臂 Δ 按此打折看；
  conv/chk 的单臂读数尤其接近该量级。

新跑三臂命令（复跑用）：

```
.venv\Scripts\python.exe -m model --model pro-t-dsl-chk --data en_dev --eval
.venv\Scripts\python.exe -m model --model pro-t-dsl-conv-chk-r0 --data en_dev --eval
.venv\Scripts\python.exe -m model --model pro-t-direct-conv --data en_dev --eval
```

设计约定（立项时写死，判读遵守）：检查只通过修复循环起作用，"关掉全部 C"≡
"去重试"，`-r0` 一臂同答两问；C 不逐个消融，逐检查器归因从 trace 免费出
（C6 净 +3 / C5b 净 0，见 PROGRESS 牌 1 实测）；声明层拿掉后校验/修复随之
消失，"−声明层" = 裸直出 + 同一份 K1–K11 prose。

---

## 4. 存档探索支（`plandsl` + 知识，en_dev n=104）

带 plan 注知识，已被上面的 no-plan 线取代——保留作对照。

| 配置 | 组件 | EX | VA |
|---|---|---:|---:|
| `pro-t-plandsl-prof` | +画像（只给） | 42.31 | 97.1 |
| `pro-t-plandsl-prof-force` | +C5a 强制表态 | 43.27 | 98.1 |
| `pro-t-plandsl-prof-force-chk` | +C5b/C6 检查 | 49.04 | 99.0 |
| `pro-t-plandsl-conv` | +约定（prose） | 45.19 | 97.1 |
| `pro-t-plandsl-conv-cchk` | +C7 约定检查 | 47.12 | 99.0 |

画像轴（prof/force）相对基线 45.19 判负（−2.9/−1.9，噪声区）：给了知识不强制用＝漏。
`plandsl-conv`=45.19 与基线打平，正是"约定在 plan 后无效"的证据（对照 §3 去 plan 后 +4.81）。

---

## 5. 骨干 × thinking 泛化网格（en_dev，EX%，▢ = 待补）

> 这是"对比多模型 + thinking"的主网格。现只有 `pro-t` 一列填满 + 零星非thinking/flash 点。
> 每个 ▢ = 一次待跑实验（见 §7）。

| 骨干＼配置 | direct | plan | plandsl | dsl | dsl-conv | dsl-conv-chk |
|---|---:|---:|---:|---:|---:|---:|
| `flash` | 33.65 | ▢ | ▢ | ▢ | ▢ | ▢ |
| `flash-t` | ▢ | ▢ | ▢ | ▢ | ▢ | ▢ |
| `pro` | 22.12 | 29.81 | 38.46 | ▢ | ▢ | ▢ |
| `pro-t` | 40.38 | 40.38 | 45.19 | 52.88 | 57.69 | **63.46** |

注：`pro` 非thinking 的 plandsl=38.46、plan=29.81；`pro-t` 的 plandsl 现模板 45.19（旧模板 `-v1` 44.23）。
VA 见 §3/§4 或各 JSON。

---

## 6. 其他数据集（同一网格，现极稀疏）

**en_train（n=414，EX%）** — 用于检验 dev 结论是否泛化到干净大样本：

| 骨干＼配置 | plandsl | dsl |
|---|---:|---:|
| `pro-t` | 52.17 | 52.90 |

去 plan 在 train 上 +27/−24 net +3（p≈0.78，纯噪声）——"plan 负资产"只在 plan 型错误占主导的 dev 画像上成立，非全局结论。

**zh_dev（n=104，EX%）**：

| 骨干＼配置 | direct | … | dsl-conv-chk |
|---|---:|:--:|---:|
| `flash` | 27.88 | ▢ | ▢ |
| `pro-t` | ▢ | ▢ | **62.50** |

---

## 7. 待补实验（把 ▢ 变成数）

按价值排序（LOO 三臂已于 2026-07-24 跑完，结果见 §3b）：
1. **终配置泛化复验**：`pro-t-dsl-conv-chk` 已在 zh_dev 62.5；补 en_train，看 +检查在大样本是否再现。
2. **是否 thinking 的补齐**：主线各配置的非thinking 版（`pro-dsl` / `pro-dsl-conv-chk` …），
   看"去 plan / 约定 / 检查"的收益是否依赖 thinking 骨干。
3. **多骨干**：`flash` / `flash-t` 跑主线配置，看结论跨骨干泛化。

**怎么加一个 骨干×thinking 变体**（`endpoint_spec` 决定骨干与 thinking，`_stages`/开关决定配置）：
在 `model/pipeline/models.py` 加一个子类、覆盖 `endpoint_spec`，再在 `model/__init__.py` 注册。例：

```python
class FlashTDslConvChk(ProTDslConvChk):        # 终配置换 flash 骨干
    name = "flash-t-dsl-conv-chk"
    endpoint_spec = dict(base_url="https://api.deepseek.com/v1",
                         model="deepseek-v4-flash", key_env="DEEPSEEK_API_KEY",
                         request_params={"extra_body": {"thinking": {"type": "enabled"}}})
```

跑：`.venv\Scripts\python.exe -m model --model flash-t-dsl-conv-chk --data en_dev --eval`

---

## 8. 复算方式（数字皆可复现）

- **EX/VA**：`.venv\Scripts\python.exe -m archer_eval --data en_dev --pred predictions/dsl/pro-t-dsl-conv-chk_en_dev.json`
- **检查器精度**（C5b/C6/C7 触发·有用·有害）：`.venv\Scripts\python.exe scripts/measure_checks.py --split {dev,train}`
- **翻转数 / McNemar p**：加载两个 results 的 `samples[i].match`（逐题布尔、同序对齐），
  数 `b`=错→对、`c`=对→错，两侧精确二项检验 `p=2·Σ_{k≤min(b,c)} C(b+c,k)·0.5^(b+c)`（封顶 1）。

---

## 9. SQLens 信号离线精度（2026-07-27，scripts/measure_checks.py 复算）

Task 8：SQLens 六支静态信号（`model/pipeline/dsl/checks.py` 的 S1-S6，全部默认关）
的离线闸门测量。判定口径：useful=触发且原判错，harmful=触发但原判对，
`precision = useful / (useful + harmful)`；闸门 = train `trigger ≥ 5` 且
`precision ≥ 0.7`，两条都过才留。**判定只看 train，dev 数字只记录不参与判定**。

复算命令与原始输出：

```
.venv\Scripts\python.exe -m scripts.measure_checks --split train --checks sqlens

S1: 触发 2 | useful 1 [66] | harmful 1 [67] | precision 50%
S2: 触发 0 | useful 0 [] | harmful 0 [] | precision 0%
S3: 触发 21 | useful 14 [20, 21, 191, 287, 310, 312, 314, 317, 318, 320, 327, 330, 351, 409] | harmful 7 [65, 76, 337, 338, 350, 406, 408] | precision 67%
S4: 触发 0 | useful 0 [] | harmful 0 [] | precision 0%
S5: 触发 13 | useful 11 [66, 93, 108, 109, 115, 194, 195, 199, 200, 202, 203] | harmful 2 [67, 369] | precision 85%
S6: 触发 39 | useful 31 [11, 34, 35, 36, 37, 66, 93, 115, 142, 143, 158, 159, 179, 184, 185, 186, 187, 194, 195, 199, 200, 202, 203, 218, 280, 291, 300, 301, 302, 303, 327] | harmful 8 [144, 145, 378, 379, 380, 386, 387, 389] | precision 79%
```

```
.venv\Scripts\python.exe -m scripts.measure_checks --split dev --checks sqlens

S1: 触发 0 | useful 0 [] | harmful 0 [] | precision 0%
S2: 触发 0 | useful 0 [] | harmful 0 [] | precision 0%
S3: 触发 5 | useful 3 [24, 61, 80] | harmful 2 [78, 82] | precision 60%
S4: 触发 0 | useful 0 [] | harmful 0 [] | precision 0%
S5: 触发 0 | useful 0 [] | harmful 0 [] | precision 0%
S6: 触发 13 | useful 9 [27, 61, 63, 68, 69, 70, 71, 90, 91] | harmful 4 [28, 29, 30, 72] | precision 69%
```

| 信号 | train 触发 | train useful/harmful | precision | dev 触发 | 判定 |
|---|---:|---|---:|---:|---|
| S1 值歧义 | 2 | 1/1 | 50% | 0 | 弃（trigger<5） |
| S2 GROUP BY 无聚合 | 0 | 0/0 | 0% | 0 | 弃（trigger<5） |
| S3 join 非外键 | 21 | 14/7 | 67% | 5 | 弃（precision 0.667<0.7，虽 trigger 过） |
| S4 子查询多行用 = | 0 | 0/0 | 0% | 0 | 弃（trigger<5） |
| S5 空谓词 | 13 | 11/2 | 85% | 0 | **留**（13≥5 且 0.846≥0.7） |
| S6 结果异常 | 39 | 31/8 | 79% | 13 | **留**（39≥5 且 0.795≥0.7） |

闸门：train `trigger ≥ 5` 且 `precision ≥ 0.7`。dev 数字只记录，不参与判定。

**逐支判定**：

- **S1 值歧义**：train 触发 2 <5，trigger 门槛不过，直接弃（precision 50% 也不过，双重不过）。
- **S2 GROUP BY 无聚合**：train 触发 0，弃。
- **S3 join 非外键**：train 触发 21（过 trigger 门槛），但 precision = 14/21 ≈ 0.667 <0.7，
  precision 门槛不过，弃。dev 上 precision 60% 与 train 方向一致（仅供参照，未参与判定）。
- **S4 子查询多行用 =**：train 触发 0，弃。
- **S5 空谓词**：train 触发 13≥5，precision = 11/13 ≈ 0.846≥0.7，两条都过，**留**。
  这支带已知争议（空结果不一定是错），但实测数字过闸——按约定不用直觉推翻数字。
  注意 dev 触发 0（该拆分里没有满足 S5 判定前提的题），这是记录，不影响判定。
- **S6 结果异常**：train 触发 39≥5，precision = 31/39 ≈ 0.795≥0.7，两条都过，**留**。
  同样带已知争议，同样按数字裁决。

**最终启用集合**：`ENABLED_SQLENS = ("S5", "S6")`（写在 `model/pipeline/dsl/checks.py`，
`sqlens_issues` 上方）。S1-S4 保留实现但不进默认集合，返回结构不变（对应键恒为空列表）。

---

## 附：孤儿/变体数据文件（有数据、无注册类）

历史跑分，保留在对应骨架目录，供复算：

| 新文件 tag | 旧 tag | EX(en_dev) | 说明 |
|---|---|---:|---|
| `pro-plan` | `plansql-pro` | 29.81 | 非thinking plan |
| `pro-t-plan-bare` | `plansql-pro-thinking-bare` | 30.77 | plan 无反事实原则（`_duplicates/` 里有其逐字节副本） |
| `pro-plan-n3` | `plansql-pro-n3` | 27.88 | 非thinking n=3 投票 |
| `pro-plandsl` | `dslsql-pro` | 38.46 | 非thinking plandsl |
| `pro-t-plandsl-v1` | `dslsql-pro-thinking`(旧模板) | 44.23 | 原始 dslgen 模板；`measure_checks` 精度基准 |
| `pro-direct-know` | `deepseek-v4-pro-knowledge` | 24.04 | 直出+知识提示词消融（已否决） |
| `pro-direct-type` | `deepseek-v4-pro-type` | 20.19 | 直出+题型提示词消融（已否决） |
