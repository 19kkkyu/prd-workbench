import json
import os
import unittest
from unittest.mock import patch
import httpx
from workbench.storage.cloud import CloudStore,StorageError


class CloudTests(unittest.TestCase):
    def make(self,handler):
        with patch.dict(os.environ,{'SUPABASE_URL':'https://fixture.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'sb_secret_fixture'}):
            return CloudStore(transport=httpx.MockTransport(handler))

    def test_database_only_no_file_storage_access(self):
        requests=[]
        def handler(request):
            requests.append(request)
            if request.method=='GET':return httpx.Response(200,json=[])
            return httpx.Response(201)
        store=self.make(handler)
        store.verify()
        project=store.create_project('会员项目')
        self.assertEqual(project['name'],'会员项目')
        self.assertEqual(store.projects(),[])
        self.assertEqual(store.runs(project['id']),[])
        self.assertTrue(all(r.url.path.startswith('/rest/v1/') for r in requests))
        self.assertFalse(any('/storage/' in r.url.path for r in requests))

    def test_failure_messages_do_not_include_server_response(self):
        store=self.make(lambda request:httpx.Response(403,text='sb_secret_sensitive'))
        with self.assertRaises(StorageError) as caught:store.verify()
        self.assertNotIn('sb_secret_sensitive',str(caught.exception))

    def test_cloud_error_points_to_new_schema(self):
        store=self.make(lambda request:httpx.Response(404))
        with self.assertRaises(StorageError) as caught:store.verify()
        self.assertIn('deploy/supabase/setup.sql',str(caught.exception))
