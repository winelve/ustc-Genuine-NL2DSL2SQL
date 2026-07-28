# 冻结实验产物

此目录只保存论文主线和必要历史对照的不可变快照。正常运行仍写入
`predictions/` 与 `results/`；两者是可再生目录，默认不进入 Git。

## 目录

- `final/archer/en_dev/`：Archer 的 Direct / Direct+FS / DSL / DSL+FS 四格。
- `final/bird/dev_20251106/`：当前 BIRD dev 的同一四格。
- `archive/bird/dev_20240627/`：旧版 BIRD dev 的历史 DSL+FS 结果，不与新版横比。
- `manifest.json`：selection、预测文件、题数、分数与 SHA-256。

主线只包含两个已确认 idea：DSL 与 fixed semantic few-shot。其他探索方案的
本地输出仍保留在被忽略的运行目录中，其结论见 `docs/PROGRESS.md`。

更新快照时必须同时更新 `manifest.json`，并重新运行 selection audit、题数检查
和完整测试。
