# 免费云端部署与交接

目标：Fork 代码后，接手者使用自己的 Streamlit、Supabase 和 AI 账号部署。无需安装 Docker、Python 或 SQLite。云端运行费用在免费额度内为零；模型是否免费取决于账号、模型和用量。

## 1 注册两个免费平台

- Streamlit Community Cloud：https://share.streamlit.io/ ，使用 GitHub 登录并允许访问自己的代码仓库。
- Supabase：https://supabase.com/dashboard ，创建 Free 项目。数据库密码自行保存，不发到聊天、不放入代码。

本项目没有自动注册账号、接受平台条款或启用付费服务。平台的账号创建和授权需要你本人完成。不要为此启用付费升级。

## 2 初始化云端存储

在 Supabase 项目的 SQL Editor 创建查询，把仓库 `supabase/setup.sql` 的全部内容粘贴执行。

SQL 会创建三张表、四个原子操作函数和名为 `prd-files` 的 Private 存储桶，并禁止匿名及普通用户直接读取数据。不需要手工建立每张表，也不需要安装数据库。

在 Supabase 项目的 Connect / Settings / API 页面找到：

- Project URL，例如 `https://xxxx.supabase.co`。
- 仅供服务端使用的 Secret key，或 Legacy API Keys 中的 `service_role` key。**不要使用 anon / publishable key**。本程序支持新 `sb_secret_` 和旧 JWT service_role 格式。

这些信息只填入下一步的 Streamlit Secrets，不提交到公开仓库。Supabase 的私有存储由网页服务端访问；网页访客无需 Supabase 账号。

## 3 在 Streamlit 创建应用

点击 Create app / Deploy an app，选择：

- Repository：`19kkkyu/prd-workbench`；Fork 的接手者选择自己的仓库。
- Branch：`main`。
- Main file path：`app.py`。
- Python version：3.12。

展开 Advanced settings，将 `.streamlit/secrets.example.toml` 的内容复制到 Secrets，填写实际值：

```toml
STORAGE_BACKEND = "supabase"
SUPABASE_URL = "https://你的项目.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "你的服务端密钥"
SUPABASE_BUCKET = "prd-files"
AI_PROVIDER = "gemini"
GEMINI_API_KEY = "你的Gemini密钥"
GEMINI_MODEL = "gemini-2.5-flash"
DAILY_CALL_LIMIT = "150"
```

模型名需在自己的账号中可用，并支持图片输入和结构化输出。使用 OpenAI 时改为 `AI_PROVIDER = "openai"`，填写 `OPENAI_API_KEY` 与 `OPENAI_MODEL`。如果暂时没有 AI 密钥，可以先留空部署，测试上传和云端历史，之后补填并重启。

点击 Deploy，等待成功后得到 `https://你的应用.streamlit.app` 网址。部署成功前不要把 `localhost` 当作正式网址。

Streamlit Secrets 与 GitHub Actions Secrets 是不同配置。此免费方案使用 Streamlit 的后台 Secrets，不会自动读取 GitHub Actions Secrets。GitHub 继续管理全部代码与模板，密钥保存在运行平台的后台。

## 4 验收

1. 打开正式网址，上传一份非敏感测试文档并保存。
2. 重启 Streamlit 应用，重新打开，确认历史和原文仍在。
3. 配置好 AI 后完成提炼、图片识别及三种导出。
4. 下载原始文件，比对大小和内容；再用测试记录验证删除。
5. 删除浏览器会话后重新访问，确认云端历史仍可读取。

如果出现云端连接错误，先检查 Supabase 项目是否暂停、SQL 是否执行成功、服务端密钥是否正确、`prd-files` 是否 Private；不要改成公开桶来绕过权限问题。

## 免费额度与历史保存

- Streamlit 应用闲置后会休眠，下次访问需等待唤醒。
- Supabase Free 项目低活跃约一周后可能暂停，需要管理员在后台恢复。按平台邮件和控制台提示及时恢复；这不是永久免费的存储保证。
- Supabase 当前免费额度为 500 MB 数据库、1 GB 文件存储，另有流量等限制，以官网和账号控制台为准。
- 本程序将原文与压缩后的解析数据按 8 MiB 分块保存，支持页面 200 MB 上传上限，不需要放宽免费存储的单个对象限制。原文、图片和解析副本都会占用存储，低频不代表无限容量。
- 数据库只保存元数据、报告和问答；图片及解析正文放在私有文件存储里，不把大量 Base64 图片塞入数据库。
- 失败重试和图片读取也占用 API 次数。每日次数限制不是精确金额限制；使用免费 API 时不要主动开启自动付费。
- 免费 Gemini 的数据使用条款与付费层不同，内部文档需按公司允许的范围上传。

应用无登录，所有能访问正式网址的人都能查看共享历史和下载文档，这是当前产品设定。存储桶 Private 只阻止绕过应用直接访问文件，不会为应用增加用户权限隔离。

## 更新与交接

接手者 Fork 后需要新建自己的 Supabase 项目、执行 SQL、部署自己的 Streamlit 应用并填写自己的 Secrets。Fork 不会复制你的密钥、历史文档或云服务账号。之后推送代码可以由 Streamlit 拉取更新。

本机原有历史不会自动上传到云端，也不会被删除。需要迁移时应单独执行明确的迁移流程。

备份需要同时导出数据库和私有存储对象；只有数据库备份无法恢复原始文档。暂停恢复、备份及免费额度规则以平台当时政策为准。

## 后台配置读取顺序

进程环境变量优先，其次 Streamlit Secrets，最后本机 `.env`。不要在云端同时设置互相矛盾的环境变量与 Secrets。修改配置后重启应用；前台始终不显示密钥和模型配置框。

离线测试不代表真实云端验收。没有实际 Supabase 项目和 API 配置时，只能完成代码、模拟接口测试和部署材料，不能宣称公网部署成功。

官方参考：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management 与 https://supabase.com/pricing
