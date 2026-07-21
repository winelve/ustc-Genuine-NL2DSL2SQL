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

命名建议：`<模型/方法>_<数据集>.json`，例如 `gpt35_ct3_en_dev.json`。

还没有模型时，可用 `--gold-as-pred` 代替 `--pred` 自检评测框架（应得满分）。
