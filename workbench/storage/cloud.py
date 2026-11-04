import uuid
import httpx

from workbench.config import setting
from workbench.storage.schema import validate_run
from workbench.intelligence.pipeline import timestamp


class StorageError(Exception):pass


class CloudStore:
    def __init__(self,transport=None):
        url=setting('SUPABASE_URL').strip().rstrip('/')
        key=setting('SUPABASE_SERVICE_ROLE_KEY').strip()
        if not url.startswith('https://') or not key:raise StorageError('云端配置不完整，请检查 Supabase URL 和服务端密钥。')
        headers={'apikey':key}
        if key.startswith('eyJ'):headers['Authorization']='Bearer '+key
        self.client=httpx.Client(base_url=url,headers=headers,timeout=httpx.Timeout(30,connect=8),transport=transport)

    def request(self,method,path,**kwargs):
        try:r=self.client.request(method,'/rest/v1/'+path,**kwargs)
        except httpx.HTTPError:raise StorageError('云端存储连接超时或不可用，请检查网络和 Supabase 项目是否暂停。') from None
        if r.is_error:
            if r.status_code in (401,403):msg='云端认证失败，请检查服务端密钥。'
            elif r.status_code in (400,404):msg='云端结构未就绪，请在 Supabase 执行新版 deploy/supabase/setup.sql。'
            else:msg='云端存储暂不可用，请检查项目状态和额度。'
            raise StorageError(msg)
        return r.json() if r.content else None

    def verify(self):
        self.request('GET','prd_projects',params={'select':'id','limit':1},timeout=10)
        self.request('GET','prd_summaries',params={'select':'id','limit':1},timeout=10)

    def create_project(self,name):
        name=name.strip()
        if not name or len(name)>100:raise ValueError('项目名需为 1—100 个字符。')
        project={'id':str(uuid.uuid4()),'name':name,'created':timestamp()}
        self.request('POST','prd_projects',json=project)
        return project

    def all_rows(self,table,params):
        result=[]
        while True:
            page=self.request('GET',table,params={**params,'offset':len(result),'limit':100})
            result.extend(page)
            if len(page)<100:return result

    def projects(self):
        return self.all_rows('prd_projects',{'select':'*','order':'created.desc,id.desc'})

    def save(self,run):
        run=validate_run(run)
        self.request('POST','prd_summaries',json={'id':run['id'],'project_id':run['project_id'],'created':run['created'],'payload':run},
            headers={'Prefer':'resolution=ignore-duplicates','Content-Type':'application/json'})

    def runs(self,project_id=None):
        params={'select':'payload','order':'created.desc,id.desc'}
        if project_id:params['project_id']='eq.'+str(uuid.UUID(project_id))
        return [r['payload'] for r in self.all_rows('prd_summaries',params)]

    def delete_run(self,run_id):self.request('DELETE','prd_summaries',params={'id':'eq.'+str(uuid.UUID(run_id))})

    def rename_project(self,project_id,name):
        name=name.strip()
        if not name or len(name)>100:raise ValueError('项目名需为 1—100 个字符。')
        self.request('PATCH','prd_projects',params={'id':'eq.'+str(uuid.UUID(project_id))},json={'name':name})

    def delete_project(self,project_id):self.request('DELETE','prd_projects',params={'id':'eq.'+str(uuid.UUID(project_id))})

    def reserve_call(self):
        if not self.request('POST','rpc/prd_reserve_call',json={'p_limit':int(setting('DAILY_CALL_LIMIT','150'))}):
            raise ValueError('已达到今日调用上限。')
