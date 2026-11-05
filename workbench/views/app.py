import streamlit as st
from workbench.storage import open_store,StorageError
from workbench.views.compose import compose_page
from workbench.views.history import history_page


@st.cache_resource
def store_resource():return open_store()


def run():
    st.set_page_config(page_title='PRD 项目提炼工作台',page_icon='📑',layout='wide')
    st.markdown('''<style>
    .block-container{max-width:1280px;padding-top:4rem;padding-bottom:3rem}
    h1{font-size:2.35rem!important;letter-spacing:-.035em}
    h2{font-size:1.45rem!important}h3{font-size:1.12rem!important}
    [data-testid="stSidebar"]{border-right:1px solid #e0e9e7}
    div.stButton>button{border-radius:8px}
    </style>''',unsafe_allow_html=True)
    with st.sidebar:
        st.markdown('### 📑 项目提炼工作台')
        st.caption('按项目汇总，按产品展开')
        page=st.radio('工作空间',['项目提炼','历史记录','使用说明'],label_visibility='collapsed')
        st.divider()
        st.caption('只保存 Summary，不保存上传原文。\n\n无登录，共享项目与历史。')
    st.title({'项目提炼':'把项目需求，整理成清晰的 Summary','历史记录':'历史记录','使用说明':'使用说明'}[page])
    if page=='使用说明':
        st.markdown('''
1. 在“项目提炼”选择或新建项目，并为项目命名。不同项目分别提炼，不做跨项目关联分析。
2. 添加产品并命名，每个产品可上传多份 PDF / DOCX；同一产品的文档共同组成产品 Summary。
3. 点击“生成项目 Summary”，先提炼各文档、汇总产品，再生成项目总 Summary。
4. 结果自动保存到历史；首页只展示本次结果。Word / PDF 导出项目报告，Excel 导出产品需求清单。
5. 在“历史记录”筛选项目和日期，查看、导出或删除结果，也可重命名及删除项目。

**文件处理**：单文件最高 200 MB。图片、扫描页、表格仍参与提炼；旧 DOC 请先转成 DOCX。原文、图片和识别转写仅在本次处理内存中使用，不写入本地磁盘或云端存储。处理成功后上传控件自动清空，历史只保存 Summary、项目名、产品名、文档文件名和日期等元数据。

**提炼范围**：保留流程、功能、业务规则、异常和原文已有验收标准。原文未写的内容标记“未说明”，不生成待确认问题。可选追问只依据提炼结果，不回查原文；追问记录仅在当前会话保留。

**运行配置**：模型和密钥由管理员在后台配置。免费云端使用 Supabase 数据库，不再需要文件存储桶。首次升级需执行 deploy/supabase/setup.sql。新版不读取、不自动删除旧版原文及历史库，迁移办法见 docs/UPGRADE.md。
''')
        with st.expander('模型连接诊断（不读取上传文档）'):
            st.caption('发送固定测试文字，先检查基础调用，再检查完整报告格式。最多两次请求，不自动重试、不保存结果；计入模型调用额度。')
            if st.button('运行连接诊断'):
                from workbench.config import setting
                from workbench.intelligence.diagnostics import probe_gemini
                if setting('AI_PROVIDER','openai').strip().lower() != 'gemini':
                    st.info('此诊断入口用于 Gemini。')
                else:
                    try:
                        with st.spinner('正在测试模型连接…'):
                            checks = probe_gemini(store_resource(), setting('GEMINI_MODEL','gemini-2.5-flash'), setting('GEMINI_API_KEY'))
                        for check in checks:
                            (st.success if check['ok'] else st.error)(check['step'])
                            st.code(check['detail'], language=None)
                        st.caption('可复制以上诊断文字反馈；这里不显示密钥或业务文档。')
                    except (StorageError, ValueError) as exc:
                        st.error(str(exc))
        return
    try:
        with st.spinner('正在连接项目与 Summary 历史…'):store=store_resource()
        if page=='项目提炼':compose_page(store)
        else:history_page(store)
    except StorageError as exc:
        st.error(str(exc))
        st.caption('配置与初始化步骤见 docs/CLOUD_DEPLOY.md。')
