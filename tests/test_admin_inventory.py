import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit
from unittest.mock import patch
from veri_yollari import DataPaths
from v6_storage import admin_inventory as admin
from v6_storage.readonly_inventory import report
from web_server import create_server

TOKEN = 'test-only-admin-token-not-a-secret-123456789'


class AdminInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.location = DataPaths({'BIST_DATA_DIR': str(self.root)}, repo_root=self.root/'repo')
        for name in ('runtime/tahmin.json', 'runtime/ai_ogrenme_gecmisi.json', 'runtime/.user-unique.tmp', 'runtime/recovery.wal'):
            p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('PRIVATE CONTENT')
        self.env = patch.dict(os.environ, {'BIST_STORAGE_ADMIN_TOKEN': TOKEN}); self.env.start(); self.addCleanup(self.env.stop)
        admin._last_scan = float('-inf')
        self.headers = {'Authorization': 'Bearer ' + TOKEN}
        self.url = urlsplit('/api/admin/storage-inventory')

    def test_authenticated_readonly_aggregates(self):
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        with patch('pathlib.Path.open', side_effect=AssertionError('no contents')):
            value, status = admin.handle(self.headers, self.url, self.location)
        self.assertEqual(status, 200)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()})
        output = json.dumps(value)
        for secret in ('PRIVATE CONTENT', str(self.root), 'file_token', 'largest', TOKEN): self.assertNotIn(secret, output)
        for category in ('prediction_history','learning_data','temporary_files','recovery_records'):
            self.assertEqual(value['categories'][category]['logical_bytes'],15)
        self.assertFalse(value['source_deleted']); self.assertFalse(value['source_content_read'])
        self.assertEqual(admin.handle(self.headers, self.url, self.location)[1],429)

    def test_disabled_and_unauthorized_never_scan(self):
        with patch.object(admin,'report',side_effect=AssertionError('no scan')):
            for token in ('', 'short'):
                with patch.dict(os.environ, {'BIST_STORAGE_ADMIN_TOKEN':token}):
                    self.assertEqual(admin.handle(self.headers,self.url,self.location)[1],503)
            for headers in ({}, {'Authorization':'Bearer wrong'}, {'Authorization':'İ'}):
                self.assertEqual(admin.handle(headers,self.url,self.location)[1],401)

    def test_fixed_root_and_no_parameters(self):
        with patch.object(admin,'report',side_effect=AssertionError('no scan')):
            self.assertEqual(admin.handle(self.headers,urlsplit('/api/admin/storage-inventory?root=/data'),self.location)[1],400)
            for extra in ({'Origin':'https://evil.test'}, {'Content-Length':'1'}, {'Transfer-Encoding':'chunked'}):
                self.assertEqual(admin.handle(dict(self.headers,**extra),self.url,self.location)[1],400)
            self.location.root=None
            self.assertEqual(admin.handle(self.headers,self.url,self.location)[1],503)

    def test_error_and_partial_are_not_success(self):
        with patch.object(admin,'report',side_effect=OSError('private path secret')):
            value,status=admin.handle(self.headers,self.url,self.location)
        self.assertEqual(status,503);self.assertNotIn('secret',str(value))
        admin._last_scan=float('-inf')
        limited=report(self.root,max_entries=1)
        self.assertFalse(limited['complete']);self.assertTrue(limited['budget_exhausted'])
        with patch.object(admin,'report',return_value=limited):
            self.assertEqual(admin.handle(self.headers,self.url,self.location)[1],206)

    def test_concurrent_scan_rejected(self):
        admin._lock.acquire()
        try:self.assertEqual(admin.handle(self.headers,self.url,self.location)[1],429)
        finally:admin._lock.release()

    def test_http_route_no_session_or_new_files(self):
        server=create_server('127.0.0.1',0,records=object(),data_paths=self.location)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        url='http://127.0.0.1:%s/api/admin/storage-inventory'%server.server_port
        before=set(self.root.rglob('*'))
        with urlopen(Request(url,method='POST',headers=self.headers),timeout=5) as response:
            self.assertEqual(response.status,200);self.assertIsNone(response.headers.get('Set-Cookie'))
            self.assertFalse(json.load(response)['source_content_read'])
        with self.assertRaises(HTTPError) as error:urlopen(Request(url,method='POST'),timeout=5)
        self.assertEqual(error.exception.code,401)
        self.assertEqual(before,set(self.root.rglob('*')))
