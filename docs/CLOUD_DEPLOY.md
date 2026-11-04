# 免费云端部署

代码放在 GitHub，网页运行在 Streamlit Community Cloud，Summary 保存在 Supabase Free 数据库。无需购买服务器、安装 Docker 或配置文件存储桶。

## 已部署用户升级

进入 Supabase 项目 SQL Editor，执行仓库 `deploy/supabase/setup.sql` 全部内容。此脚本新增项目和 Summary 表，不会删除旧版原文、表、存储桶或历史数据。执行完成后等待 Streamlit 拉取更新，必要时 Reboot app。已有的 URL、服务端密钥和模型配置继续使用。

## 第一次部署

1. 注册 https://supabase.com/dashboard 并创建 Free 项目，在 SQL Editor 执行 `deploy/supabase/setup.sql`。
2. 复制 Project URL 与服务端 Secret key / legacy service_role key。不要使用 anon 或 publishable 公钥。
3. 在 https://share.streamlit.io/ 创建应用，仓库选择自己的 Fork，分支 `main`，启动文件 `app.py`。
4. Advanced settings 中明确选择 Python **3.12**，将 `.streamlit/secrets.example.toml` 复制到 Secrets 并填入实际值。
5. 点击 Deploy。公开代码不包含实际密钥；密钥只保存在后台 Secrets。

```toml
STORAGE_BACKEND = "supabase"
SUPABASE_URL = "https://你的项目.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "你的服务端密钥"
AI_PROVIDER = "gemini"
GEMINI_API_KEY = "你的模型密钥"
GEMINI_MODEL = "gemini-2.5-flash"
DAILY_CALL_LIMIT = "150"
```

模型名称需在账号中可用，支持图片和结构化输出。也可将服务改为 OpenAI 并配置 `OPENAI_API_KEY` / `OPENAI_MODEL`。不使用存储桶，旧的 `SUPABASE_BUCKET` 配置可删除或保留为无效兼容项。

## 验证

创建一个测试项目，添加两个产品，分别上传 PRD，生成 Summary。首页应出现总 Summary、每个产品的 Summary、需求表和导出。刷新并进入历史，确认结果仍在；云端重启后再确认一次。历史中不应有原文查看、下载或原文缓存记录。

代码只接受 Summary 字段和元数据入库；PDF、Word、图片、识别转写仅在本次处理内存中使用。浏览器上传控件会暂时持有文件，生成成功后自动清空。不向数据库或存储桶写入任何上传文档。

## 免费方案限制

- Streamlit 闲置后会休眠；Supabase Free 低活跃后可能暂停，需管理员恢复。
- Supabase 当前免费数据库容量 500 MB，另有请求和流量额度，以官网为准。新版不占用文件存储额度。
- 模型免费额度取决于账号和模型，图片识别也计入 API 使用。Gemini 免费层数据条款需符合公司的内部文档使用要求。
- 无登录，能访问网址的人可查看共享的 Summary 历史和管理项目。不同 Fork 使用自己的密钥和 Supabase，不继承你的数据。
- 更换 Python 版本需要按 Streamlit 平台规则重新部署；重建前保存 Secrets。依赖文件不决定平台 Python 版本。

官方参考：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management 、 https://supabase.com/pricing
