import uuid
import streamlit as st
from workbench.config import setting
from workbench.intelligence.client import AI,error_message
from workbench.intelligence.pipeline import project_summary
from workbench.storage import StorageError
from workbench.views.results import show_result


def compose_page(store):
    st.caption('一个项目一份总 Summary，分别呈现各产品的 Summary 与详细需求。上传原文只用于本次提炼。')
    projects=store.projects()
    with st.expander('新建项目',expanded=not projects):
        with st.form('new_project'):
            name=st.text_input('项目名称',max_chars=100,placeholder='例如：数字零售体验升级')
            create=st.form_submit_button('创建项目')
        if create:
            try:
                project=store.create_project(name)
                st.session_state['active_project']=project['id']
                st.rerun()
            except (ValueError,StorageError) as exc:st.error(str(exc))
    if not projects:
        st.info('先创建项目，再上传该项目下各产品的 PRD。')
        return
    ids=[p['id'] for p in projects]
    active=st.session_state.get('active_project',ids[0])
    chosen=st.selectbox('本次提炼的项目',ids,index=ids.index(active) if active in ids else 0,
        format_func=lambda x:next(p['name']+' · '+p['created'][:10]+' · '+p['id'][:6] for p in projects if p['id']==x))
    project=next(p for p in projects if p['id']==chosen)
    if st.session_state.get('form_project')!=chosen:
        for key in list(st.session_state):
            if key.startswith(('upload_','product_name_')):del st.session_state[key]
        st.session_state['form_project']=chosen
        st.session_state['products']=[uuid.uuid4().hex]
        st.session_state['upload_epoch']=st.session_state.get('upload_epoch',0)+1
    st.session_state['active_project']=chosen
    if st.button('＋ 添加产品'):
        st.session_state['products'].append(uuid.uuid4().hex)
        st.rerun()
    products=[]
    epoch=st.session_state.get('upload_epoch',0)
    for i,product_id in enumerate(st.session_state['products'],1):
        with st.container(border=True):
            left,right=st.columns([5,1])
            product_name=left.text_input(f'产品 {i} 名称',value=f'产品{i}',max_chars=100,key=f'product_name_{product_id}')
            if right.button('移除',key=f'remove_{product_id}',disabled=len(st.session_state['products'])==1):
                st.session_state['products'].remove(product_id)
                # The widget is not rendered again after rerun; its upload is dropped.
                st.rerun()
            files=st.file_uploader(f'上传产品 {i} 的 PRD（可多份）',type=['pdf','docx','txt','md'],accept_multiple_files=True,
                key=f'upload_{product_id}_{epoch}',help='本次使用后不保存原文。图片与扫描页由后台视觉模型识别。')
            products.append({'name':product_name.strip(),'files':files})
    provider=setting('AI_PROVIDER','openai').lower()
    key=setting('OPENAI_API_KEY' if provider=='openai' else 'GEMINI_API_KEY')
    model=setting('OPENAI_MODEL','gpt-4.1-mini') if provider=='openai' else setting('GEMINI_MODEL','gemini-2.5-flash')
    if not key:st.info('AI 服务尚未启用，请管理员在后台完成配置。')
    ready=all(p['name'] and p['files'] for p in products)
    if st.button('生成项目 Summary',type='primary',disabled=not ready or not key):
        names=[p['name'] for p in products]
        if len(names)!=len(set(names)):
            st.error('同一项目内的产品名称不能重复。')
            return
        try:
            with st.status('正在提炼项目…',expanded=True) as status:
                inputs=[{'name':p['name'],'documents':[{'name':f.name,'raw':f.getvalue()} for f in p['files']]} for p in products]
                result=project_summary(project,inputs,AI(store,provider,model,key),lambda text:status.update(label=text))
                st.session_state['last_result']=result
                st.session_state['result_saved']=False
                try:
                    store.save(result)
                    st.session_state['result_saved']=True
                except StorageError:pass
                status.update(label='提炼完成',state='complete')
            st.session_state['upload_epoch']=epoch+1
            del inputs
            st.rerun()
        except Exception as exc:
            st.error(str(exc) if isinstance(exc,(ValueError,StorageError)) else error_message(exc))
    result=st.session_state.get('last_result')
    if result and result['project_id']==chosen:
        st.divider()
        if st.session_state.get('result_saved'):st.success('项目 Summary 已自动保存到历史记录。')
        else:
            st.warning('提炼结果尚未保存到历史，可先导出，或重试保存。')
            if st.button('重试保存结果'):
                try:
                    store.save(result)
                    st.session_state['result_saved']=True
                    st.rerun()
                except StorageError as exc:st.error(str(exc))
        show_result(result,store,key,provider,model)
