"""pipeline：多阶段 SQL 生成（plan / DSL 声明 / 校验修复 / 投票的组合）。

主线模型在 models.py，判负存档支在 archive.py，命名见 docs/ABLATION.md。
设计文档：docs/design/2026-07-22-M1-plansql.md、2026-07-22-M2-dslsql.md
提示词：model/pipeline/prompts/*.md（直接编辑文本文件，不碰代码）
"""
