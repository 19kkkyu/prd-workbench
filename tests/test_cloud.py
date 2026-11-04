import copy
import gzip
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx

from cloud_store import CloudStorageError, SupabaseStore
from core import analyze
from test_workbench import FakeAI


class CloudFixture:
    """Offline HTTP contract fixture, not a substitute for live Postgres/RLS tests."""
    def __init__(self):
        self.rows, self.objects, self.chat = {}, {}, []
        self.calls = 0
        self.fail_delete = False
        self.public = False
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path, method = request.url.path, request.method
        data = json.loads(request.content) if request.content and request.headers.get("content-type", "").startswith("application/json") else None
        params = request.url.params
        def response(value=None, status=200):
            return httpx.Response(status,json=value)
        if path.startswith("/storage/v1/bucket/"):
            return response({"public":self.public})
        if path.startswith("/storage/v1/object/"):
            obj = path.removeprefix("/storage/v1/object/prd-files/")
            if method == "POST":
                self.objects[obj] = request.content
                return response({"Key":obj})
            if method == "GET":
                return httpx.Response(200,content=self.objects[obj]) if obj in self.objects else response(status=404)
            if method == "DELETE":
                if self.fail_delete:
                    self.fail_delete = False
                    return response(status=503)
                for key in data["prefixes"]:
                    self.objects.pop(key,None)
                return response([])
        if path.startswith("/rest/v1/rpc/"):
            function = path.rsplit("/",1)[-1]
            row = self.rows.get(data.get("p_id"))
            if function == "prd_claim":
                if not row or row["status"] in ("processing","deleting"):
                    return response(False)
                row.update(status="processing",lease=data["p_token"],provider=data["p_provider"],model=data["p_model"])
                return response(True)
            if function == "prd_begin_delete":
                if not row or row["status"] == "processing":
                    return response(None)
                row.update(status="deleting",lease=None)
                return response(row)
            if function == "prd_reserve_call":
                if self.calls >= data["p_limit"]:
                    return response(False)
                self.calls += 1
                return response(True)
            if function == "prd_recover":
                return response(False)
        if path == "/rest/v1/prd_documents":
            if method == "POST":
                self.rows[data["id"]] = dict(data,report=None,error=None,provider=None,model=None,lease=None)
                return response(status=201)
            rows = [row for row in self.rows.values() if all(
                key not in params or params[key] == "eq."+str(row.get(key)) for key in ("id","lease","status"))]
            if method == "GET":
                return response(rows)
            if method == "PATCH":
                for row in rows:
                    row.update(data)
                return response(rows)
            if method == "DELETE":
                for row in rows:
                    self.rows.pop(row["id"])
                    self.chat = [c for c in self.chat if c["document_id"] != row["id"]]
                return response(status=204)
        if path == "/rest/v1/prd_messages":
            if method == "POST":
                self.chat.append(dict(data,id=len(self.chat)+1))
                return response(status=201)
            return response(self.chat)
        return response(status=404)


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.server = CloudFixture()
        self.store = self.client()
        self.units = [{"source":"第1页","text":"订单完成后七天内可以申请退款。退款由消费者本人发起。"}]

    def client(self):
        return SupabaseStore(url="https://fixture.supabase.co",key="sb_secret_fixture",bucket="prd-files",
            transport=httpx.MockTransport(self.server))

    def add(self):
        return self.store.add("退款.pdf","售后",b"original"*1000,self.units,[])

    def test_roundtrip_reconnect_analysis_and_original(self):
        with patch("cloud_store.PART_SIZE",1024):
            doc_id = self.add()
        self.assertGreater(len(self.server.rows[doc_id]["raw_manifest"]),1)
        reconnected = self.client()
        self.assertEqual(reconnected.get(doc_id)["parsed"],self.units)
        self.assertEqual(reconnected.original_bytes(doc_id),b"original"*1000)
        analyze(reconnected,doc_id,FakeAI())
        self.assertEqual(self.client().get(doc_id)["status"],"done")
        self.assertEqual(self.client().get(doc_id)["report"]["requirements"][0]["id"],"REQ-001")

    def test_lost_lease_cannot_overwrite_parsed_and_no_uploaded_orphans(self):
        doc_id = self.add()
        token = self.store.claim(doc_id,"test","model")
        before = set(self.server.objects)
        with self.assertRaises(CloudStorageError):
            self.store.save_parsed(doc_id,"wrong-lease",[{"source":"x","text":"wrong"}])
        self.assertEqual(set(self.server.objects),before)
        self.store.save_parsed(doc_id,token,[{"source":"x","text":"updated"}])
        self.assertEqual(self.store.get(doc_id)["parsed"][0]["text"],"updated")

    def test_failed_storage_delete_can_retry(self):
        doc_id = self.add()
        self.server.fail_delete = True
        with self.assertRaises(CloudStorageError):
            self.store.delete(doc_id)
        self.assertEqual(self.store.list()[0]["status"],"deleting")
        self.store.delete(doc_id)
        self.assertEqual(self.store.list(),[])
        self.assertEqual(self.server.objects,{})

    def test_corrupt_object_is_rejected(self):
        doc_id = self.add()
        key = self.server.rows[doc_id]["raw_manifest"][0]["path"]
        self.server.objects[key] = b"corrupt"
        with self.assertRaises(CloudStorageError):
            self.store.original_bytes(doc_id)

    def test_private_bucket_required_and_no_public_download_url(self):
        self.store.verify()
        self.server.public = True
        with self.assertRaises(CloudStorageError):
            self.store.verify()
        self.assertFalse(any("/public/" in r.url.path for r in self.server.requests))

    def test_quota_rpc_and_new_key_auth_header(self):
        with patch.dict(os.environ,{"DAILY_CALL_LIMIT":"1"}):
            self.store.reserve_call()
            with self.assertRaises(ValueError):
                self.store.reserve_call()
        request = self.server.requests[0]
        self.assertEqual(request.headers["apikey"],"sb_secret_fixture")
        self.assertNotIn("authorization",request.headers)

    def test_error_does_not_expose_response_or_credentials(self):
        bad = SupabaseStore(url="https://fixture.supabase.co",key="sb_secret_sensitive",transport=httpx.MockTransport(
            lambda req:httpx.Response(403,text="sensitive response sb_secret_sensitive")))
        with self.assertRaises(CloudStorageError) as caught:
            bad.verify()
        self.assertNotIn("sb_secret_sensitive",str(caught.exception))

    def test_settings_secrets_without_mutating_process_env(self):
        from settings import setting
        import streamlit
        with patch.object(streamlit,"secrets",{"MODEL_TEST":"secret-model"}),patch.dict(os.environ,{},clear=True):
            self.assertEqual(setting("MODEL_TEST"),"secret-model")
            self.assertNotIn("MODEL_TEST",os.environ)
            with patch.dict(os.environ,{"MODEL_TEST":"env-model"}):
                self.assertEqual(setting("MODEL_TEST"),"env-model")
