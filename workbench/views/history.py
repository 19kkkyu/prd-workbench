import streamlit as st
from workbench.views.results import show_result


def history_page(store):
    st.caption('按项目和日期查看、导出及管理 Summary。历史不包含原文或图片。')
    projects=store.projects()
    if not projects:
        st.info('暂无项目。')
        return
    labels={p['id']:p['name'] for p in projects}
    left,right=st.columns(2)
    project_id=left.selectbox('项目筛选',['全部',*[p['id'] for p in projects]],format_func=lambda x:x if x=='全部' else labels[x])
    search=right.text_input('搜索项目或产品')
    col1,col2=st.columns(2)
    start=col1.date_input('开始日期',value=None)
    end=col2.date_input('结束日期',value=None)
    if start and end and start>end:
        st.warning('开始日期不能晚于结束日期。')
        return
    runs=store.runs(None if project_id=='全部' else project_id)
    runs=[r for r in runs if (not start or r['created'][:10]>=start.isoformat()) and (not end or r['created'][:10]<=end.isoformat())
        and (not search or search.lower() in (labels.get(r['project_id'],r['project_name'])+' '+r['project_name']+' '+' '.join(p['name'] for p in r['report']['products'])).lower())]
    if not runs:st.info('暂无符合条件的 Summary。')
    else:
        st.dataframe([{'项目':labels.get(r['project_id'],r['project_name']),'产品数':len(r['report']['products']),
            '保存日期':r['created'][:19].replace('T',' ')} for r in runs],hide_index=True,width='stretch')
        ids=[r['id'] for r in runs]
        selected=st.selectbox('查看 Summary',ids,format_func=lambda x:next(labels.get(r['project_id'],r['project_name'])+' · '+r['created'][:19].replace('T',' ')+' · '+r['id'][:6] for r in runs if r['id']==x))
        result=next(r for r in runs if r['id']==selected)
        show_result(result,store)
        with st.expander('管理这份 Summary'):
            confirmed=st.checkbox('确认删除这份 Summary',key='confirm_run_'+selected)
            if st.button('删除 Summary',disabled=not confirmed):
                store.delete_run(selected)
                if st.session_state.get('last_result',{}).get('id')==selected:st.session_state.pop('last_result',None)
                st.rerun()
    with st.expander('管理项目'):
        target=st.selectbox('选择项目',[p['id'] for p in projects],format_func=lambda x:labels[x]+' · '+x[:6])
        new_name=st.text_input('新项目名',value=labels[target],key='rename_'+target,max_chars=100)
        if st.button('保存项目名称'):
            try:
                store.rename_project(target,new_name)
                st.rerun()
            except ValueError as exc:st.error(str(exc))
        st.caption('修改项目名称不会改写旧 Summary 内记录的生成时名称。')
        confirmed=st.checkbox('确认删除这个项目及其全部 Summary',key='confirm_project_'+target)
        if st.button('删除项目及全部 Summary',disabled=not confirmed):
            store.delete_project(target)
            if st.session_state.get('last_result',{}).get('project_id')==target:st.session_state.pop('last_result',None)
            st.rerun()
