# PRD 项目提炼工作台

按“项目 → 产品 → 文档”组织 PRD。一个项目可包含多个产品，每个产品可上传多份文档，生成项目总 Summary、各产品 Summary 和详细需求清单。

## 功能

- 项目命名与产品分组，支持 PDF、DOCX、TXT、Markdown。
- 支持文档中的表格、图片与扫描页识别，单文件最高 200 MB。
- 首页只负责提炼和展示本次结果；成功后自动保存 Summary。
- 历史页管理结果、项目名称与日期筛选，不展示或保存原始文档。
- Word / PDF 导出完整报告，Excel 导出带产品归属的需求清单。
- 可选追问依据 Summary 回答，不回查原文。
- 后台配置 OpenAI / Gemini，页面不暴露密钥或模型设置。

## 云端部署

免费低频方案使用 Streamlit Community Cloud + Supabase 数据库。见 [部署说明](docs/CLOUD_DEPLOY.md)。旧版升级必须先执行新版 SQL；见 [升级与迁移](docs/UPGRADE.md)。

本项目未承诺模型和云平台永久免费或持续在线。真实云端和模型效果需要部署后验证。

## 本机运行

使用 Python 3.12，安装 `requirements.txt`，复制 `.env.example` 为 `.env` 并在本机填写配置：

```text
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Windows 已准备好 Python 环境时也可运行 `scripts/start.ps1`。本机默认 SQLite，只存 Summary，数据库位于 `data/summaries.sqlite3`。

## 目录

```text
app.py                    Streamlit 稳定入口
workbench/
  config.py               后台配置读取
  views/                  上传、结果与历史页面
  documents/              文档结构及图片提取
  intelligence/           模型、提炼与项目汇总
  storage/                Summary 数据模型及本机/云端保存
  exports/                Word、PDF、Excel 导出
deploy/
  supabase/setup.sql      云端数据库初始化
  docker/                 可选 Docker 部署
scripts/                  本机启动、旧结果迁移
docs/                     部署与升级说明
tests/                    自动验证
.streamlit/               页面配置与无密钥的 Secrets 模板
```

可选 Docker 从仓库根目录运行 `docker compose -f deploy/docker/compose.yaml up --build -d`。持久化卷只保存 Summary。

## 验证

```text
python -m unittest discover -s tests -v
```

离线测试使用模拟模型与 HTTP 接口，不代表真实 API 准确率或公网部署成功。代码升级保留旧数据，不会自动删除旧版文档或报告。
