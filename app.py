from settings import setting, cloud_runtime
import json
import os
import base64
from html import escape
from pathlib import Path

import streamlit as st

from core import AI, ROOT, Store, analyze, ask, error_message, parse_document, recognize_images
from parsing import display_units, pending_images
from cloud_store import CloudStorageError, SupabaseStore
from exports import FIELDS, OVERVIEW, excel, pdf, value, word

st.set_page_config(page_title="PRD 文档提炼工作台", page_icon="📑", layout="wide")
st.markdown("""<style>
.block-container {max-width:1280px;padding-top:4rem;padding-bottom:3rem}
h1 {letter-spacing:-.035em;font-size:2.35rem!important}
h2 {font-size:1.45rem!important} h3 {font-size:1.1rem!important}
[data-testid="stMetric"] {background:white;border:1px solid #e0e9e7;border-radius:12px;padding:16px}
[data-testid="stSidebar"] {border-right:1px solid #e0e9e7}
.intro {font-size:1rem;color:#657880;line-height:1.8;margin-bottom:1.8rem}
.eyebrow {font-size:.76rem;letter-spacing:.16em;color:#16786a;font-weight:700}
div.stButton > button {border-radius:8px}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def store_instance():
    backend = setting("STORAGE_BACKEND", "local").lower()
    if backend == "supabase":
        cloud = SupabaseStore()
        cloud.verify()
        return cloud
    if backend != "local":
        raise ValueError("STORAGE_BACKEND 仅支持 local 或 supabase。")
    if cloud_runtime():
        raise ValueError("云端部署请设置 STORAGE_BACKEND=supabase，避免历史写入临时磁盘。")
    return Store()


try:
    store = store_instance()
except (CloudStorageError,ValueError) as exc:
    st.error(str(exc))
    st.info("请管理员按照 CLOUD_DEPLOY.md 完成后台配置，然后重启应用。")
    st.stop()
provider = setting("AI_PROVIDER", "openai").lower()
model = setting("OPENAI_MODEL", "gpt-4.1-mini") if provider == "openai" else setting("GEMINI_MODEL", "gemini-2.5-flash")
key = setting("OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY", "")
with st.sidebar:
    st.markdown("### 📑 文档提炼工作台")
    st.caption("每份文档，都有清晰的需求脉络")
    page = st.radio("工作空间", ["上传与提炼", "历史记录", "使用说明"], label_visibility="collapsed")
    st.divider()
    st.caption(("云端运行 · 历史保存至 Supabase" if isinstance(store,SupabaseStore) else "本机试用 · 历史持久保存") + "\n\n团队版无登录，共享历史记录。")


def history_records():
    try:
        return store.list()
    except CloudStorageError as exc:
        st.error(str(exc))
        st.stop()


def run_analysis(doc_id):
    if not key:
        st.warning("AI 服务尚未启用，请由管理员完成后台配置。文档已保存，可以稍后提炼。")
        return
    bar = st.progress(0, text="准备处理文档")
    try:
        ai = AI(store, provider, model, key)
        analyze(store, doc_id, ai, lambda done, total, text: bar.progress(min(done / total, 1.0), text=text))
        st.success("提炼完成，已保存到历史记录。")
    except Exception as exc:
        st.error(error_message(exc))
    finally:
        bar.empty()


def show_document(doc_id):
    try:
        doc = store.get(doc_id)
    except (CloudStorageError,ValueError) as exc:
        st.warning(str(exc))
        return
    st.subheader(doc["name"])
    st.caption(f"{doc['project']} · {doc['created'][:16].replace('T',' ')} · {len(display_units(doc['parsed']))} 个原文章节")
    if doc["notes"]:
        with st.expander(f"文件读取说明（{len(doc['notes'])}）", expanded=True):
            for note in doc["notes"]:
                st.warning(note)
    if doc["status"] == "processing":
        st.info("正在处理此文档，请稍后刷新。如果服务已中断，可在 15 分钟后恢复任务。")
        if st.button("刷新 / 恢复中断任务", key=f"recover_{doc_id}"):
            store.recover(doc_id)
            st.rerun()
        return
    if doc["status"] == "deleting":
        st.warning("上次删除尚未完成。请重试，以清理云端文件。")
        if st.button("完成删除", key=f"finish_delete_{doc_id}"):
            try:
                store.delete(doc_id)
                st.rerun()
            except (CloudStorageError,ValueError) as exc:
                st.error(str(exc))
        return
    if doc["error"]:
        st.error(doc["error"])
    if not doc["report"]:
        st.info("文档已解析并保存。配置模型后，点击提炼即可生成报告。")
    label = "重新提炼（调用 AI）" if doc["report"] else "开始提炼"
    if st.button(label, type="primary", disabled=not key, key=f"analyze_{doc_id}"):
        run_analysis(doc_id)
        doc = store.get(doc_id)
    if doc["report"]:
        report = doc["report"]
        a, b, c = st.columns(3)
        a.metric("需求条目", len(report["requirements"]))
        b.metric("文档类型", report["document_type"])
        c.metric("已处理文字", f"{report.get('coverage',{}).get('characters',0):,}")
        tabs = st.tabs(["文档总结", "需求清单", "导出结果", "原文与来源"])
        with tabs[0]:
            st.markdown(f"### {report['title']}")
            for field, title in OVERVIEW:
                st.markdown(f"#### {title}")
                st.markdown(report.get(field, "未说明"))
        with tabs[1]:
            modules = sorted({r["module"] for r in report["requirements"]})
            x, y = st.columns([1, 2])
            module = x.selectbox("模块筛选", ["全部模块", *modules], key=f"filter_{doc_id}")
            search = y.text_input("搜索需求", placeholder="输入需求名称、规则或角色", key=f"search_{doc_id}")
            filtered = [r for r in report["requirements"] if (module == "全部模块" or r["module"] == module) and (not search or search.lower() in json.dumps(r, ensure_ascii=False).lower())]
            rows = [{label: value(r.get(field)) for field, label in FIELDS if field in ("id", "module", "title", "description", "priority", "sources")} for r in filtered]
            if rows:
                st.dataframe(rows, hide_index=True, width="stretch")
                selected = st.selectbox("展开需求详情", filtered, format_func=lambda r: f"{r['id']} · {r['title']}", key=f"detail_{doc_id}")
                with st.container(border=True):
                    for field, label in FIELDS:
                        if field not in ("id", "title"):
                            st.markdown(f"**{label}**")
                            st.write(value(selected.get(field)))
            else:
                st.info("没有符合筛选条件的需求。")
        with tabs[2]:
            st.write("报告包含文档总结、完整需求详情和来源。Excel 提供便于筛选的需求清单。")
            # Explicit generation avoids rebuilding three exports on every UI rerun.
            export_key = f"exports_{doc_id}"
            fingerprint = json.dumps(report, ensure_ascii=False)
            if st.button("生成 Word / PDF / Excel", key=f"make_{doc_id}"):
                try:
                    with st.spinner("正在生成导出文件…"):
                        st.session_state[export_key] = (fingerprint, word(doc), pdf(doc), excel(doc))
                except Exception:
                    st.error("导出失败，请检查运行环境中的文档组件。")
            saved = st.session_state.get(export_key)
            if saved and saved[0] == fingerprint:
                stem = Path(doc["name"]).stem + "_提炼"
                a, b, c = st.columns(3)
                a.download_button("↓ Word 报告", saved[1], stem + ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"word_{doc_id}")
                b.download_button("↓ PDF 报告", saved[2], stem + ".pdf", "application/pdf", key=f"pdf_{doc_id}")
                c.download_button("↓ Excel 清单", saved[3], stem + ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"excel_{doc_id}")
        with tabs[3]:
            source_view(doc)
        with st.expander("💬 基于本文追问（可选）", expanded=False):
            st.caption("仅使用当前文档；展开不会调用 AI，提交问题时才调用。长文档会逐段读取，可能需要更多时间。")
            for msg in store.messages(doc_id):
                with st.chat_message("user"):
                    st.write(msg["question"])
                with st.chat_message("assistant"):
                    response = json.loads(msg["answer"])
                    st.write(response["answer"])
                    st.caption("来源：" + "、".join(response["sources"]) if response["sources"] else "当前回答未提供原文位置")
            with st.form(f"ask_{doc_id}"):
                question = st.text_area("你的问题", max_chars=2000, placeholder="例如：整理本文关于订单取消的全部业务规则")
                submitted = st.form_submit_button("提交问题", disabled=not key)
            if submitted and question.strip():
                try:
                    with st.spinner("正在查阅原文…"):
                        ask(store, doc, AI(store, provider, model, key), question)
                    st.rerun()
                except Exception as exc:
                    st.error(error_message(exc))
    else:
        with st.expander("查看已读取原文"):
            source_view(doc)
    with st.expander("原始文件与记录管理"):
        if st.button("准备下载原始文件", key=f"prepare_original_{doc_id}"):
            try:
                raw = store.original_bytes(doc_id)
                st.download_button("下载原始文件", raw, doc["name"], key=f"original_{doc_id}")
            except (CloudStorageError,ValueError,OSError):
                st.error("原始文件暂时无法下载，请检查存储连接或项目是否暂停。")
        confirmed = st.checkbox("删除这份原文、提炼结果和追问记录", key=f"confirm_{doc_id}")
        if st.button("删除记录", disabled=not confirmed, key=f"delete_{doc_id}"):
            try:
                store.delete(doc_id)
                st.session_state.pop(f"exports_{doc_id}", None)
                st.session_state.pop("current_id", None)
                st.rerun()
            except (CloudStorageError,ValueError) as exc:
                st.error(str(exc))


def source_view(doc):
    units = display_units(doc["parsed"])
    pending = pending_images(doc["parsed"])
    if pending:
        st.info(f"本文有 {len(pending)} 处图片 / 扫描页待识别。图片已保存，识别后会纳入提炼。" + ("请由管理员完成后台 AI 配置。" if not key else ""))
        if st.button("识别图片内容", disabled=not key, key=f"vision_{doc['id']}"):
            bar = st.progress(0, text="准备识别图片")
            try:
                recognize_images(store, doc["id"], AI(store, provider, model, key),
                    lambda done,total,text: bar.progress(done/total,text=text))
                st.rerun()
            except Exception as exc:
                st.error(error_message(exc))
            finally:
                bar.empty()
    if not units:
        st.info("暂无可展示的原文内容。")
        return
    source = st.selectbox("定位原文", range(len(units)), format_func=lambda i: units[i]["source"], key=f"source_{doc['id']}")
    selected = units[source]
    st.caption("按章节完整展示；短章节保留整章，包含多个编号子章节的长结构按二级标题展示。")
    for block in selected.get("blocks", []):
        if block["kind"] == "table":
            rows = block["rows"]
            html_rows = "".join("<tr>" + "".join(f'<td style="border:1px solid #dce5e4;padding:9px;vertical-align:top;white-space:pre-wrap">{escape(cell)}</td>' for cell in row) + "</tr>" for row in rows)
            st.markdown(f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;margin:12px 0">{html_rows}</table></div>', unsafe_allow_html=True)
        elif block["kind"] == "image":
            if block.get("data"):
                st.image(base64.b64decode(block["data"]), caption=block["label"])
            if block.get("recognized"):
                st.write(block["text"])
                if block.get("limitations") and block["limitations"] != "无":
                    st.warning("图片识别说明：" + block["limitations"])
            elif block.get("error"):
                st.warning(block["error"])
            else:
                st.caption("待识别：尚未将图片内容转成文字。")
        elif block.get("level"):
            st.markdown("#### " + escape(block["text"]))
        else:
            st.write(block["text"])


if page == "上传与提炼":
    st.markdown('<div class="eyebrow">DOCUMENT WORKSPACE</div>', unsafe_allow_html=True)
    st.title("把文档，整理成清晰的需求")
    st.markdown('<div class="intro">批量上传 BRD / PRD，逐份梳理业务流程、功能与规则。原文与结果自动保存，随时查看、导出。</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.subheader("01  上传文档")
        project = st.text_input("项目分类（可选）", placeholder="例如：会员、即时零售；留空保存为未分类")
        files = st.file_uploader("拖入文件，或点击选择", type=["pdf", "docx", "txt", "md"], accept_multiple_files=True,
                                 help="每份独立处理。旧版 DOC 请先转为 DOCX。支持保存图片，后台启用视觉模型后识别图片与扫描页。")
        st.caption(f"单文件上限由后台配置决定（默认 200 MB）；不会静默截断文档内容。")
        if not key:
            st.info("AI 服务尚未启用，当前可上传、查看原文并保存历史。提炼和图片识别在后台配置完成后可用。")
        save_col, analyze_col = st.columns(2)
        save = save_col.button("解析并保存原文", width="stretch", disabled=not files)
        process = analyze_col.button("保存并开始提炼", type="primary", width="stretch", disabled=not files or not key)
        if save or process:
            added = []
            for file in files:
                try:
                    with st.spinner(f"正在读取 {file.name}…"):
                        raw = file.getvalue()
                        parsed, notes = parse_document(file.name, raw)
                        doc_id = store.add(file.name, project, raw, parsed, notes)
                        added.append(doc_id)
                    st.success(f"已保存：{file.name}")
                    if process:
                        run_analysis(doc_id)
                except Exception as exc:
                    st.error(f"{file.name}：文件解析或保存失败。{str(exc) if isinstance(exc, ValueError) else '请确认文件未损坏，且属于支持的格式。'}")
            if added:
                st.session_state.current_id = added[-1]
    st.markdown("### 02  查看提炼结果")
    records = history_records()
    if records:
        ids = [r["id"] for r in records]
        current = st.session_state.get("current_id", ids[0])
        selected = st.selectbox("选择文档", ids, index=ids.index(current) if current in ids else 0,
            format_func=lambda x: next(f"{r['name']} · {r['project']} · {r['created'][:16]}" for r in records if r["id"] == x))
        show_document(selected)
    else:
        st.info("上传第一份文档后，这里将展示摘要、需求表和导出入口。无需密钥也可以先测试解析和历史保存。")
elif page == "历史记录":
    st.title("历史记录")
    st.caption("原始文档、提炼结果和追问记录持久保存。团队部署时，此处为共享历史。")
    records = history_records()
    x, y = st.columns(2)
    search = x.text_input("搜索文件名")
    project = y.selectbox("项目分类", ["全部", *sorted({r["project"] for r in records})])
    records = [r for r in records if search.lower() in r["name"].lower() and (project == "全部" or r["project"] == project)]
    labels = {"ready": "已解析", "done": "已完成", "failed": "可重试", "processing": "处理中", "deleting":"删除待完成"}
    if records:
        st.dataframe([{"文件":r["name"], "项目":r["project"], "上传时间":r["created"][:16], "状态":labels[r["status"]]} for r in records], hide_index=True, width="stretch")
        selected = st.selectbox("打开历史文档", [r["id"] for r in records], format_func=lambda x: next(f"{r['name']} · {r['created'][:16]}" for r in records if r["id"] == x))
        show_document(selected)
    else:
        st.info("暂无符合条件的记录。")
else:
    st.title("使用说明")
    st.markdown("""
1. 上传 PDF 或 DOCX 文档，可批量选择；默认单文件上限 200 MB。旧版 DOC 请先另存为 DOCX。
2. 每份独立保存和提炼，分类只用于归档。AI 服务由管理员在后台统一配置，使用者无需填写密钥。
3. 在文档总结中阅读业务内容，在需求清单中筛选并展开详细规则及来源。
4. 点击“生成 Word / PDF / Excel”，然后下载所需格式。刷新后可重新生成，不需要再次调用模型。
5. 历史记录保存在应用数据目录，服务重启后仍可读取。追问默认收起，提交时才调用 AI。

**原文阅读**：按章节展示，正文与表格保持在同一章节。短章节整章展示；包含三个及以上编号子章节时按二级标题（如 4.1、4.2）展示，更深层内容跟随二级标题。超长章节才考虑按明确的小标题拆分。无可靠标题的 PDF 按页展示，不按单段切碎。

**内容边界**：只提炼原文已写的信息，缺失字段显示“未说明”。不生成待确认问题，不分析跨项目关系。AI 处理时的容量分段与原文章节展示相互独立。

**图片与扫描件**：保留并展示 Word 内嵌图片；PDF 的扫描页、图片及矢量图会生成页面图像。后台视觉模型负责文字转写、表格读取和流程图理解，结果保存后纳入提炼。可在原文区域先点击“识别图片内容”，也可直接提炼时自动识别。未配置 API 时会标记待识别，不会把未识别图片当成已解析内容。模糊图像和复杂图形仍需人工核对；Word 外链图片需先嵌入，SmartArt 等对象建议转为 PDF。

**小团队使用**：支持多个浏览器会话，历史共享；没有账号和文档隔离。模型费用由配置的密钥承担。免费云端版使用 Supabase 保存历史和原文，不依赖网页临时磁盘；低频闲置后可能需管理员恢复暂停的 Supabase 项目。后台配置和交接步骤见 CLOUD_DEPLOY.md。本机版继续保存在本地。
""")
