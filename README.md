# 实验报告文档(飞书云文档)
```
https://ramz9acvkhf.feishu.cn/wiki/AeYiwGpfviXSXHkBspfcKcmhnot?from=from_copylink
```

# 运行文档

---

## 项目结构

```
.
├── config.py              # 全局配置：路径、数据集简写、超时、精度（唯一配置源）
├── requirements.txt   # openai / pydantic / sqlglot
├── data/              # Archer 数据集（en/zh 的 train/dev）
├── database/          # SQLite 库，只读，不进 git
├── model/             # 阶段一·生成：模型接口 + pipeline（plan/DSL/校验修复）
├── archer_eval/       # 阶段二·评测：VA/EX/SIM（Algorithm 1）
├── predictions/       # 两段间接口：模型生成的 SQL
├── results/           # 评测报告，可再生，不进 git
├── scripts/           # 独立工具（数据库齐全性检查等）
├── docs/              # 开发规范、进度、消融结果
└── tests/             # pytest
```



### 测试分数:

**模型**：`pro-t-dsl-conv-chk`(deepseek-v4-pro-thinking + pipeline), 使用官方指定评分方式进行测评.

| 数据集   | EX        | VA    |
| -------- | --------- | ----- |
| en_dev   | **63.46** | 100.0 |
| zh_dev   | **62.50** | 96.15 |

---

## 1. 环境(建议使用uv创建虚拟环境)

- Python **3.11+**



**全局安装依赖**

```bash
pip install -r requirements.txt
```

**使用uv安装依赖**

```
uv pip install -r requirements.txt
```



## 2. API 密钥

pipeline 调用 DeepSeek。密钥通过**环境变量**读取.

```powershell
# Windows PowerShell
$env:DEEPSEEK_API_KEY = "sk-..."
```
```bash
# Linux/macOS
export DEEPSEEK_API_KEY="sk-..."
```

评测机需要能访问 `api.deepseek.com`。



## 3. 数据库

请在项目目录下, 直接解压文件目录下的`database.zip`

解压后

```
database
├───bike_1
├───concert_singer
├───customers_and_products_contacts
├───driving_school
├───formula_1
├───hospital_1
├───riding_club
├───soccer_1
├───wine_1
│   └───.ipynb_checkpoints
└───world_1
```



## 4. 运行

**测试能否正常运行**

```shell
python -m model --model pro-t-dsl-conv-chk --data en_dev --limit 1 --eval
```

**复现 dev 分数（生成 + 评测）：**

```bash
# 在英文dev数据集上测试
python -m model --model pro-t-dsl-conv-chk --data en_dev --eval

# 在中文dev数据集上测试
python -m model --model pro-t-dsl-conv-chk --data zh_dev --eval  
```



## 5. 输出

```shell
# 在英文dev数据集上测试
python -m model --model pro-t-dsl-conv-chk --data en_dev --eval	

# 会输出三个文件
predictions/
	pro-t-dsl-conv-chk_en_dev.json    # json数组,对应LLM生成的每一个题目的答案
	pro-t-dsl-conv-chk_en_dev.trace.json # 记录了架构运行过程中的一些中间信息, 帮助溯源和分析
results/
	en_dev_pro-t-dsl-conv-chk.json # 经过判题系统, 评测后的反馈结果.
```



## 6. 成本估算

最终模型每题发 **1–3** 次 deepSeek-v4-pro-thinking 请求.
dev 数据集 104 题 , 每次测试,建议准备5元. 
train数据集 400+题, 每次测试,建议准备25元.



## 7. 常用指令

```bash
# 冒烟测试（跑 1 条）
python -m model --model pro-t-dsl-conv-chk --data en_dev --limit 1 --eval

# 生成 + 评测（复现 dev 分数）
python -m model --model pro-t-dsl-conv-chk --data en_dev --eval
python -m model --model pro-t-dsl-conv-chk --data zh_dev --eval

# 只生成，不评测
python -m model --model pro-t-dsl-conv-chk --data en_dev

# 对已有预测文件单独评测
python -m archer_eval --data en_dev --pred predictions/pro-t-dsl-conv-chk_en_dev.json

# 预览/导出 CT-3 prompt（第 0 题）
python -m model.prompts --data en_dev --index 0

# 预览 pipeline 发给各 LLM 的完整消息（第 0 题）
python -m model.pipeline --data en_dev --preview 0
```

