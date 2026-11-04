import streamlit as st
from workbench.exports.reports import OVERVIEW,FIELDS,value,word,pdf,excel
from workbench.intelligence.client import AI,error_message
from workbench.intelligence.pipeline import ask_summary


def overview(report):
    for key,label in OVERVIEW:
        st.markdown('#### '+label)
        st.write(report.get(key,'未说明'))


def show_result(result,store,key='',provider='',model=''):
    st.subheader(result['project_name'])
    st.caption('生成日期：'+result['created'][:19].replace('T',' '))
    tabs=st.tabs(['项目总 Summary','各产品 Summary','需求清单','导出结果'])
    with tabs[0]:overview(result['report']['overview'])
    with tabs[1]:
        for product in result['report']['products']:
            with st.expander(product['name'],expanded=True):
                st.caption('文档：'+'、'.join(product['document_names']))
                overview(product['report'])
                for note in product['reading_notes']:st.warning('图片识别说明：'+note)
    with tabs[2]:
        selected=st.selectbox('产品筛选',['全部',*[p['name'] for p in result['report']['products']]],key='req_filter_'+result['id'])
        rows=[]
        for product in result['report']['products']:
            if selected!='全部' and product['name']!=selected:continue
            rows.extend({'产品':product['name'],**{label:value(r.get(field)) for field,label in FIELDS if field!='product'}} for r in product['report']['requirements'])
        if rows:
            st.dataframe(rows,hide_index=True,width='stretch')
            detail=st.selectbox('查看需求详情',range(len(rows)),format_func=lambda i:rows[i]['产品']+' · '+rows[i]['需求编号']+' · '+rows[i]['需求名称'],key='req_detail_'+result['id'])
            with st.container(border=True):
                for label,text in rows[detail].items():
                    st.markdown('**'+label+'**')
                    st.write(text)
        else:st.info('当前产品没有提炼出独立需求条目。')
    with tabs[3]:
        cache_key='export_'+result['id']
        if st.button('生成 Word / PDF / Excel',key='make_'+result['id']):
            with st.spinner('正在生成导出文件…'):st.session_state[cache_key]=(word(result),pdf(result),excel(result))
        if cache_key in st.session_state:
            files=st.session_state[cache_key]
            a,b,c=st.columns(3)
            stem=result['project_name']+'_Summary'
            a.download_button('↓ Word 报告',files[0],stem+'.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document',key='word_'+result['id'])
            b.download_button('↓ PDF 报告',files[1],stem+'.pdf','application/pdf',key='pdf_'+result['id'])
            c.download_button('↓ Excel 清单',files[2],stem+'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='excel_'+result['id'])
    if key:
        with st.expander('💬 基于提炼结果追问（可选）'):
            chat=st.session_state.setdefault('chat_'+result['id'],[])
            st.caption('仅依据上述 Summary 回答，不回查或保存原文。')
            for item in chat:
                with st.chat_message('user'):st.write(item['question'])
                with st.chat_message('assistant'):st.write(item['answer'])
            with st.form('question_'+result['id']):
                question=st.text_area('你的问题',max_chars=2000)
                submit=st.form_submit_button('提交问题')
            if submit and question.strip():
                try:
                    with st.spinner('正在阅读提炼结果…'):answer=ask_summary(result,AI(store,provider,model,key),question,chat)
                    chat.append({'question':question,'answer':answer})
                    st.rerun()
                except Exception as exc:st.error(error_message(exc))
