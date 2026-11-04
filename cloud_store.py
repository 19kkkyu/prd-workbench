"""Supabase backend: private object storage + Postgres metadata and atomic leases.

Originals and compressed parsed data are split into 8 MiB objects. API and storage
credentials remain server-side; no public bucket or browser-side client is used.
"""
import gzip
import hashlib
import json
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

import httpx

from settings import setting

PART_SIZE = 8 * 1024 * 1024


class CloudStorageError(Exception):
    pass


class SupabaseStore:
    def __init__(self, url=None, key=None, bucket=None, transport=None):
        self.url = (url or setting("SUPABASE_URL")).rstrip("/")
        secret = key or setting("SUPABASE_SERVICE_ROLE_KEY")
        self.bucket = bucket or setting("SUPABASE_BUCKET", "prd-files")
        if not self.url.startswith("https://") or not secret or not re.fullmatch(r"[A-Za-z0-9_-]+", self.bucket):
            raise CloudStorageError("云端存储未配置完整，请管理员检查 Supabase URL、服务端密钥与存储桶名称。")
        headers = {"apikey":secret}
        if secret.startswith("eyJ"):
            headers["Authorization"] = "Bearer " + secret
        self.client = httpx.Client(base_url=self.url, headers=headers, timeout=90, transport=transport)

    def _request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise CloudStorageError("无法连接云端存储，请检查网络，或在 Supabase 后台恢复已暂停的项目。") from None
        if response.is_error:
            if response.status_code in (401,403):
                message = "云端存储认证失败，请检查服务端密钥；不能使用 anon / publishable 公钥。"
            elif response.status_code == 404:
                message = "云端数据或存储结构不存在，请先执行部署 SQL，并确认存储桶配置。"
            elif response.status_code in (409,423):
                message = "此文档正在处理、已删除或状态已变化，请刷新后重试。"
            elif response.status_code in (413,507):
                message = "云端存储容量或请求大小超出限制，请清理历史记录并检查平台额度。"
            else:
                message = "云端操作失败，请检查项目是否暂停、存储额度及部署 SQL。"
            raise CloudStorageError(message)
        return response

    def _rpc(self, name, **params):
        return self._request("POST", "/rest/v1/rpc/" + name, json=params).json()

    def verify(self):
        self._request("GET", "/rest/v1/prd_documents", params={"select":"id","limit":1})
        bucket = self._request("GET", "/storage/v1/bucket/" + self.bucket).json()
        if bucket.get("public") is not False:
            raise CloudStorageError("文档存储桶必须为 Private，请执行部署 SQL 或关闭存储桶公开访问。")

    @staticmethod
    def _local_dates(row):
        for field in ("created","updated"):
            if row.get(field):
                row[field] = datetime.fromisoformat(row[field].replace("Z","+00:00")).astimezone(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        return row

    def _patch(self, doc_id, values, token=None, status=None):
        params = {"id":"eq." + doc_id}
        if token:
            params["lease"] = "eq." + token
        if status:
            params["status"] = "eq." + status
        rows = self._request("PATCH", "/rest/v1/prd_documents", params=params,
            json=values, headers={"Prefer":"return=representation"}).json()
        if not rows:
            raise CloudStorageError("文档处理权已变化或记录已删除，请刷新后重试。")
        return rows[0]

    def _object_path(self, path):
        return "/storage/v1/object/" + self.bucket + "/" + quote(path, safe="/")

    def _upload(self, data, prefix):
        parts = []
        try:
            # Even empty files get a manifest entry; callers already reject empty uploads.
            for i, offset in enumerate(range(0, max(len(data),1), PART_SIZE)):
                part = data[offset:offset+PART_SIZE]
                path = f"{prefix}/{i:05d}"
                self._request("POST", self._object_path(path), content=part,
                    headers={"Content-Type":"application/octet-stream", "x-upsert":"false"})
                parts.append({"path":path,"size":len(part),"sha256":hashlib.sha256(part).hexdigest()})
        except Exception:
            self._remove(parts, best_effort=True)
            raise
        return parts

    def _download(self, manifest):
        result = bytearray()
        for part in manifest:
            data = self._request("GET", self._object_path(part["path"])).content
            if len(data) != part["size"] or hashlib.sha256(data).hexdigest() != part["sha256"]:
                raise CloudStorageError("云端文件完整性校验失败，请检查存储或恢复备份。")
            result.extend(data)
        return bytes(result)

    def _remove(self, manifest, best_effort=False):
        paths = [p["path"] for p in manifest]
        try:
            for i in range(0,len(paths),100):
                self._request("DELETE", "/storage/v1/object/" + self.bucket, json={"prefixes":paths[i:i+100]})
        except CloudStorageError:
            if not best_effort:
                raise

    def _parsed_upload(self, doc_id, parsed):
        content = json.dumps(parsed,ensure_ascii=False).encode("utf-8")
        return self._upload(gzip.compress(content), f"{doc_id}/parsed/{uuid.uuid4().hex}")

    def add(self, name, project, raw, parsed, notes):
        from core import now
        from parsing import PARSER_VERSION
        doc_id = str(uuid.uuid4())
        original = self._upload(raw, f"{doc_id}/original")
        payload = []
        try:
            payload = self._parsed_upload(doc_id, parsed)
            self._request("POST", "/rest/v1/prd_documents", json={
                "id":doc_id,"name":re.split(r"[/\\]",name)[-1],"project":project.strip() or "未分类",
                "created":now(),"updated":now(),"sha":hashlib.sha256(raw).hexdigest(),
                "status":"ready","notes":notes,"raw_manifest":original,"parsed_manifest":payload,
                "parser_version":PARSER_VERSION})
        except Exception:
            self._remove(original + payload,best_effort=True)
            raise
        return doc_id

    def list(self):
        rows, offset = [], 0
        while True:
            page = self._request("GET", "/rest/v1/prd_documents", params={
                "select":"id,name,project,created,status,provider,model,error",
                "order":"created.desc,id.desc","offset":offset,"limit":500}).json()
            rows.extend(self._local_dates(row) for row in page)
            if len(page) < 500:
                return rows
            offset += len(page)

    def _row(self, doc_id):
        # Validate identifiers before constructing PostgREST expressions.
        doc_id = str(uuid.UUID(doc_id))
        rows = self._request("GET", "/rest/v1/prd_documents", params={"id":"eq."+doc_id,"select":"*"}).json()
        if not rows:
            raise ValueError("该记录已被删除，请刷新历史记录。")
        return self._local_dates(rows[0])

    def get(self, doc_id):
        row = self._row(doc_id)
        if row["status"] == "deleting":
            row["parsed"] = []
        else:
            row["parsed"] = json.loads(gzip.decompress(self._download(row["parsed_manifest"])))
        return row

    def original_bytes(self, doc_id):
        row = self._row(doc_id)
        return self._download(row["raw_manifest"])

    def claim(self, doc_id, provider, model):
        token = str(uuid.uuid4())
        if not self._rpc("prd_claim", p_id=doc_id,p_token=token,p_provider=provider,p_model=model):
            raise ValueError("该文档正在处理、正在删除或已被删除，请刷新后重试。")
        return token

    def heartbeat(self, doc_id, token):
        from core import now
        self._patch(doc_id,{"updated":now()},token=token)

    def save_parsed(self, doc_id, token, units):
        old = self._row(doc_id)
        new = self._parsed_upload(doc_id,units)
        try:
            self._patch(doc_id,{"parsed_manifest":new},token=token,status="processing")
        except Exception:
            self._remove(new,best_effort=True)
            raise
        self._remove(old["parsed_manifest"],best_effort=True)

    def release_ready(self, doc_id, token):
        from core import now
        row = self._row(doc_id)
        self._patch(doc_id,{"status":"done" if row["report"] else "ready","lease":None,"error":None,"updated":now()},token=token)

    def finish(self, doc_id, token, report=None, error=None):
        from core import now
        values = {"status":"failed" if error else "done","error":error,"lease":None,"updated":now()}
        if report is not None:
            values["report"] = report
        self._patch(doc_id,values,token=token)

    def recover(self, doc_id):
        return bool(self._rpc("prd_recover",p_id=doc_id))

    def delete(self, doc_id):
        row = self._rpc("prd_begin_delete",p_id=doc_id)
        if not row:
            raise ValueError("正在处理的文档暂时不能删除，或该记录已经删除。")
        # A failed storage deletion leaves a retryable deleting record, not an orphaned file.
        self._remove(row["raw_manifest"] + row["parsed_manifest"])
        self._request("DELETE", "/rest/v1/prd_documents",params={"id":"eq."+doc_id,"status":"eq.deleting"})

    def reserve_call(self):
        limit = int(setting("DAILY_CALL_LIMIT","150"))
        if not self._rpc("prd_reserve_call",p_limit=limit):
            raise ValueError("已达到应用今日调用上限，请明日再试或调整管理员配置。")

    def messages(self, doc_id):
        return self._request("GET", "/rest/v1/prd_messages",params={
            "document_id":"eq."+str(uuid.UUID(doc_id)),"select":"*","order":"id.asc","limit":1000}).json()

    def save_message(self, doc_id, question, answer):
        self._request("POST", "/rest/v1/prd_messages",json={"document_id":doc_id,"question":question,
            "answer":json.dumps(answer,ensure_ascii=False)})
