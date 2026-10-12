import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from v6_storage.inventory_log import run_once
from v6_storage.__main__ import main
from veri_yollari import DataPaths
from web_server import create_server


class InventoryLogTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        for name in ('runtime/tahmin.json','runtime/ai_ogrenme_gecmisi.json','runtime/.user-unique.tmp','runtime/recovery.wal'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'UNIQUE SECRET DATA')
        env=patch.dict(os.environ,{'BIST_DATA_DIR':str(self.root),'STORAGE_BACKEND':'postgres','BIST_POSTGRES_DSN':'secret-invalid'})
        env.start();self.addCleanup(env.stop)

    def snapshot(self):
        return {str(p.relative_to(self.root)):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}

    def test_one_scan_no_contents_no_mutation_or_secrets(self):
        before=self.snapshot();output=io.StringIO()
        with contextlib.redirect_stdout(output),patch('pathlib.Path.open',side_effect=AssertionError('no content reads')):
            self.assertEqual(main(['inventory-log']),0)
        self.assertEqual(before,self.snapshot())
        lines=output.getvalue().splitlines();self.assertEqual(len(lines),1)
        value=json.loads(lines[0].split(' ',1)[1])
        for category in ('prediction_history','learning_data','recovery_records','temporary_files'):
            self.assertEqual(value['categories'][category]['logical_bytes'],18)
        for secret in ('UNIQUE SECRET DATA',str(self.root),'secret-invalid','file_token','largest','tahmin.json'):
            self.assertNotIn(secret,output.getvalue())
        self.assertTrue(value['estimates_not_measurements']);self.assertFalse(value['source_changed'])

    def test_log_pipe_exactly_one_bounded_write(self):
        read,write=os.pipe();self.addCleanup(os.close,read)
        real_open=os.open
        def open_fd(path,*args,**kwargs):
            return os.dup(write) if path=='/proc/1/fd/1' else real_open(path,*args,**kwargs)
        before=self.snapshot()
        try:
            with patch('v6_storage.inventory_log.os.open',side_effect=open_fd),patch('v6_storage.inventory_log.os.write',wraps=os.write) as send:
                self.assertEqual(run_once(railway_logs=True),0)
                self.assertEqual(send.call_count,1)
            self.assertIn(b'[V6_INVENTORY]',os.read(read,4096))
            self.assertEqual(before,self.snapshot())
        finally:os.close(write)

    def test_regular_log_file_is_never_written(self):
        target=self.root/'existing-log';target.write_bytes(b'PRESERVE')
        real_open=os.open
        def open_fd(path,*args,**kwargs):
            return real_open(target,os.O_WRONLY) if path=='/proc/1/fd/1' else real_open(path,*args,**kwargs)
        with patch('v6_storage.inventory_log.os.open',side_effect=open_fd),patch('v6_storage.inventory_log.report',side_effect=AssertionError('no scan')):
            self.assertEqual(run_once(railway_logs=True),2)
        self.assertEqual(target.read_bytes(),b'PRESERVE')

    def test_missing_root_does_not_create_or_default(self):
        for root in ('','relative',str(self.root/'missing')):
            output=io.StringIO()
            with patch.dict(os.environ,{'BIST_DATA_DIR':root}),contextlib.redirect_stdout(output):
                self.assertEqual(run_once(),2)
            self.assertNotIn(root if root else 'PRIVATE',output.getvalue())
        self.assertFalse((self.root/'missing').exists())

    def test_error_details_redacted_and_no_retry(self):
        output=io.StringIO()
        with patch('v6_storage.inventory_log.report',side_effect=OSError('secret path token')) as scan,contextlib.redirect_stdout(output):
            self.assertEqual(run_once(),2)
        self.assertEqual(scan.call_count,1);self.assertNotIn('secret',output.getvalue())

    def test_partial_scan_reported_not_ok(self):
        from v6_storage.readonly_inventory import report
        partial=report(self.root,max_entries=1)
        output=io.StringIO()
        with patch('v6_storage.inventory_log.report',return_value=partial),contextlib.redirect_stdout(output):
            self.assertEqual(run_once(),2)
        value=json.loads(output.getvalue().split(' ',1)[1]);self.assertFalse(value['complete'])
        self.assertTrue(value['budget_exhausted'])

    def test_pipe_failure_does_not_fallback_to_disk_or_terminal(self):
        output=io.StringIO()
        with patch('v6_storage.inventory_log.os.open',side_effect=OSError('private error')),contextlib.redirect_stdout(output):
            self.assertEqual(run_once(railway_logs=True),2)
        self.assertEqual(output.getvalue(),'')

    def test_old_endpoint_all_methods_404_without_session_or_scan(self):
        location=DataPaths({'BIST_DATA_DIR':str(self.root)},repo_root=self.root/'repo')
        server=create_server('127.0.0.1',0,records=object(),data_paths=location)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        before=self.snapshot()
        with patch('v6_storage.inventory_log.report',side_effect=AssertionError('no HTTP scan')):
            for method in ('GET','POST','PUT','PATCH','DELETE'):
                with self.assertRaises(HTTPError) as result:
                    urlopen(Request('http://127.0.0.1:%s/api/admin/storage-inventory'%server.server_port,method=method),timeout=5)
                self.assertEqual(result.exception.code,404)
                self.assertIsNone(result.exception.headers.get('Set-Cookie'))
        self.assertEqual(before,self.snapshot())
