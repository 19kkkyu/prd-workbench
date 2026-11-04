# 从文档历史升级到项目 Summary

新版入口仍是根目录 `app.py`。Streamlit 仓库、分支、启动路径与 Python 3.12 不变。

先在 Supabase SQL Editor 执行 `deploy/supabase/setup.sql`，再重启应用。无需重新配置密钥，也无需新建存储桶。

新版只管理项目与 Summary，不读取旧版原文或图片。原有 `prd_documents`、`prd_messages`、`prd-files` 存储桶，以及本机 `data/history.sqlite3` 和 `data/originals` 都不会自动删除，避免升级造成数据丢失。

如果旧版已有成功的提炼结果，可以在已配置后台环境的机器运行：

```text
python scripts/migrate_legacy.py
```

迁移只读取旧版报告、文件名、项目名与日期，不读取原文、解析正文或图片，不调用 AI。导入结果放在带“旧版导入”后缀的项目下，同一结果重复迁移不会新增副本。没有生成过报告的旧文档不会导入。

如果只是移动了代码，现有旧数据仍在原处。确认 Summary 导入和备份后，如需彻底删除旧原文，应单独在对应数据库/存储中清理；迁移脚本不会代替你执行这项不可逆操作。

新数据使用本机 `data/summaries.sqlite3` 或云端 `prd_projects` / `prd_summaries`。备份云端只需导出这些 Summary 表及项目元数据，不再需要保存文件存储对象。
