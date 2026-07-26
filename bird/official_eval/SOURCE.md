# `evaluation.py` 的来源

| | |
|---|---|
| 文件 | `evaluation.py` |
| 来源 | https://github.com/AlibabaResearch/DAMO-ConvAI —— `bird/llm/src/evaluation.py` |
| 取得方式 | `curl https://raw.githubusercontent.com/AlibabaResearch/DAMO-ConvAI/main/bird/llm/src/evaluation.py` |
| 取得日期 | 2026-07-26 |
| 我们改了什么 | **一个字节都没有。** 任何改动都会让"官方数"这个说法失效 |

## 为什么用这一份，不用 `bird-bench/mini_dev` 那一份

`mini_dev/evaluation/evaluation_ex.py` 是给 500 题 mini-dev 的，而且它 import 的
`evaluation_utils.py` 在文件顶部 `import psycopg2` / `import pymysql`——SQLite 路径
根本用不到，却会让整个脚本在没装这两个驱动的机器上直接 import 失败。

这一份是给全量 dev（1534 题）的，**只 import `sqlite3`**，唯一的第三方依赖是
`func_timeout`。两份的判分逻辑完全相同：

```python
res = 0
if set(predicted_res) == set(ground_truth_res):
    res = 1
```

没有 ORDER BY / LIMIT 的并列处理，没有并列 gold 复判。官方包里的
`dev_tied_append.json` **两份脚本都没有读过**。

## 怎么调用它

不 import，**以子进程方式跑**（`adapter.py` 负责）：脚本的 `mp.Pool` 在
`if __name__ == '__main__'` 里，只有作为顶层脚本运行时 Windows 的 spawn 才正常。

三个输入文件由 `adapter.py` 生成：

| 官方参数 | 实际文件 | 格式 |
|---|---|---|
| `--predicted_sql_path <dir>/` | `predict_dev.json` | `{"0": "SQL\t----- bird -----\tdb_id", ...}` |
| `--ground_truth_path <dir>/` | `dev_gold.sql` | 每行 `SQL\tdb_id`，**SQL 必须压成一行** |
| `--diff_json_path` | 数据集 json | 数组，每项含 `difficulty` |
