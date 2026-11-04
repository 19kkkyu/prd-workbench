"""Explicit, idempotent result-only migration. Never reads original files or parsed data."""
import json
import sqlite3
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from workbench.config import ROOT,setting
from workbench.storage import open_store,CloudStore
from workbench.storage.schema import Overview,SavedRequirement


def legacy_rows(store):
    if isinstance(store,CloudStore):
        return store.all_rows('prd_documents',{'select':'id,name,project,created,provider,model,report','report':'not.is.null','order':'created.asc,id.asc'})
    directory=Path(setting('DATA_DIR','data'))
    if not directory.is_absolute():directory=ROOT/directory
    path=directory/'history.sqlite3'
    if not path.exists():return []
    with sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT id,name,project,created,provider,model,report FROM documents WHERE report IS NOT NULL')]
    for row in rows:row['report']=json.loads(row['report'])
    return rows


def migrate(store,rows):
    projects={p['name']:p for p in store.projects()}
    known={r['id'] for r in store.runs()}
    count=0
    fields=Overview.model_fields
    allowed=SavedRequirement.model_fields
    for row in rows:
        run_id=str(uuid.UUID(row['id']))
        if run_id in known:continue
        name=(row.get('project') or '未分类')[:85]+'（旧版导入）'
        if name not in projects:projects[name]=store.create_project(name)
        project=projects[name]
        report=row['report']
        overview={field:str(report.get(field) or '未说明') for field in fields}
        reqs=[]
        for i,req in enumerate(report.get('requirements',[]),1):
            values={field:req.get(field,[] if field=='sources' else '未说明') for field in allowed}
            values['id']=f'REQ-{i:03d}'
            reqs.append(values)
        store.save({'id':run_id,'project_id':project['id'],'project_name':project['name'],'created':row['created'],
            'provider':row.get('provider') or 'legacy','model':row.get('model') or 'legacy','schema_version':3,
            'report':{'overview':overview,'products':[{'name':Path(row['name']).stem,'document_names':[row['name']],
            'report':{**overview,'requirements':reqs},'reading_notes':['由旧版单文档结果导入，未重新读取原文或调用 AI。']}]}})
        known.add(run_id)
        count+=1
    return count


if __name__=='__main__':
    store=open_store()
    print('已导入 Summary 数量：',migrate(store,legacy_rows(store)))
