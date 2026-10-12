import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v6_storage.config import Settings,StorageError
from v6_storage.records import Shape,split,assemble,digest,now,row_key,shape_for
from v6_storage.migration import Migrator,metadata,checksum
from v6_storage.r2 import R2Archive
from veri_yollari import DataPaths


class RemoteError(Exception):
    def __init__(self,status):self.response={'ResponseMetadata':{'HTTPStatusCode':status}}


class FakeS3:
    def __init__(self):self.objects={};self.parts={};self.uploads=0;self.fail_upload=False;self.aborted=0
    def head_object(self,Bucket,Key):
        if Key not in self.objects:raise RemoteError(404)
        return {'ContentLength':len(self.objects[Key])}
    def get_object(self,Bucket,Key):
        if Key not in self.objects:raise RemoteError(404)
        return {'Body':io.BytesIO(self.objects[Key])}
    def create_multipart_upload(self,**kw):self.uploads+=1;self.parts={};return {'UploadId':'owned'}
    def upload_part(self,PartNumber,Body,**kw):
        if self.fail_upload:raise RemoteError(503)
        self.parts[PartNumber]=Body;return {'ETag':str(PartNumber)}
    def complete_multipart_upload(self,Key,**kw):self.objects[Key]=b''.join(self.parts[n] for n in sorted(self.parts));return {}
    def put_object(self,Key,Body,**kw):self.objects[Key]=Body;return {}
    def abort_multipart_upload(self,**kw):self.aborted+=1;return {}
    def list_objects_v2(self,**kw):return {'Contents':[{'Size':len(data)} for data in self.objects.values()]}


class V6Configuration(unittest.TestCase):
    def test_default(self):self.assertEqual(Settings.from_env({}).mode,'legacy')
    def test_modes(self):
        for mode in ('legacy','shadow','postgres'):self.assertEqual(Settings.from_env({'STORAGE_BACKEND':mode}).mode,mode)
    def test_bad_mode(self):
        with self.assertRaises(StorageError):Settings.from_env({'STORAGE_BACKEND':'unsafe'})
    def test_tls(self):
        self.assertEqual(Settings(dsn='postgresql://name:secret@remote/db').connection_dsn(),'postgresql://name:secret@remote/db?sslmode=require')
    def test_tls_valid(self):Settings(dsn='postgresql://remote/db?sslmode=verify-full').require_database()
    def test_secret_repr(self):self.assertNotIn('secret',repr(Settings(dsn='postgresql://name:secret@remote/db')))
    def test_no_db(self):
        with self.assertRaises(StorageError):Settings().require_database()
    def test_invalid_batch(self):
        with self.assertRaises(StorageError):Settings.from_env({'STORAGE_BATCH_SIZE':'100000'})
    def test_legacy_does_not_connect(self):
        from v6_storage.backend import before_write
        with patch.dict(os.environ,{'STORAGE_BACKEND':'legacy'}),patch('v6_storage.backend.store',side_effect=AssertionError('connection')):
            self.assertFalse(before_write('/tmp/unmanaged.json',{}))
    def test_postgres_ack_required(self):
        from v6_storage.backend import guard
        with self.assertRaises(StorageError):guard(Settings(mode='postgres'),Shape('x',{'rows':'list'}))


class V6Records(unittest.TestCase):
    def test_horizons_roundtrip(self):
        row={'kayit_id':'x','price':10,**{f'sonuc_{n}g':{'completed':True,'return':n} for n in (1,3,5,10,20,60)}}
        original=copy.deepcopy(row);f,s,o=split(row,'ai_ogrenme_gecmisi.json')
        self.assertEqual(len(o),6);self.assertNotIn('sonuc_1g',f);self.assertEqual(assemble(f,{},s,o),row);self.assertEqual(row,original)
    def test_pending(self):
        row={'kayit_id':'x','sonuc_1g':None};f,s,o=split(row,'x');self.assertFalse(o);self.assertEqual(assemble(f,{},s,o),row)
    def test_nested_outcome(self):
        row={'source_hash':'abc','outcomes':{'5m':{'completed':True,'return':2}},'retry_at':None};f,s,o=split(row,'runtime/intraday_signal_results/a.json#events');self.assertEqual(assemble(f,{},s,o),row)
    def test_mapping_key_no_invented_field(self):
        row={'source_hash':'x'};self.assertEqual(row_key(Shape('x',{}),'events',row,'original-id'),'original-id');self.assertEqual(row,{'source_hash':'x'})
    def test_snapshot_identity(self):self.assertEqual(row_key(Shape('archives/2026-01-01.json',{},'tomorrow_snapshot'),'top10',{'sembol':'THYAO'}),'2026-01-01.json:THYAO')
    def test_opaque_learning_key(self):self.assertTrue(row_key(Shape('x',{}),'ogrenme_gecmisi',{'event':'a'}).startswith('content:'))
    def test_clock(self):
        from v6_storage.records import row_time
        self.assertTrue(now().endswith('+03:00'));self.assertEqual(row_time({'tahmin':{'tahmin_zamani':'2026-10-08T18:05:00+03:00'}}).hour,18)
    def test_hash_order(self):self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))


class V6Migration(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'source.json';self.shape=Shape('runtime/ai_ogrenme_gecmisi.json',{'kayitlar':'list'})
    def write(self,doc):self.path.write_text(json.dumps(doc))
    def test_dry_run_preserves(self):
        self.write({'surum':1,'kayitlar':[{'kayit_id':'a','price':5},{'kayit_id':'b','price':7}]});before=checksum(self.path);report=Migrator().run(self.path,self.shape);self.assertEqual(report['status'],'VERIFIED');self.assertEqual(report['records'],2);self.assertEqual(checksum(self.path),before);self.assertEqual(len(list(self.path.parent.iterdir())),1)
    def test_absent_source(self):
        self.assertEqual(Migrator().run(self.path,self.shape)['error'],'SOURCE_NOT_FOUND')
    def test_rerun(self):
        self.write({'kayitlar':[{'kayit_id':'a'}]});self.assertEqual(Migrator().run(self.path,self.shape),Migrator().run(self.path,self.shape))
    def test_broken(self):
        self.path.write_text('{"kayitlar":[');self.assertEqual(Migrator().run(self.path,self.shape)['status'],'UNRESOLVED')
    def test_missing(self):
        self.write({'other':1});self.assertEqual(Migrator().run(self.path,self.shape)['status'],'UNRESOLVED')
    def test_duplicate(self):
        self.write({'kayitlar':[{'kayit_id':'a'},{'kayit_id':'a'}]});self.assertEqual(Migrator().run(self.path,self.shape)['status'],'UNRESOLVED')
    def test_mapping(self):
        self.write({'version':1,'events':{'original':{'source_hash':'z'}}});report=Migrator().run(self.path,Shape('x',{'events':'mapping'}));self.assertEqual(report['records'],1);self.assertEqual(report['status'],'VERIFIED')
    def test_all_candidates_no_cap(self):
        self.write({'top10':[{'sembol':'A'}],'pozitif_havuz':{'version':1,'adaylar':[{'sembol':f'A{i}'} for i in range(120)]}})
        shape=Shape('archives/2026-01-01.json',{'top10':'list','pozitif_havuz.adaylar':'list'},'tomorrow_snapshot');report=Migrator().run(self.path,shape);self.assertEqual(report['records'],121)
    def test_private_paths(self):
        location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.assertFalse(location.users.is_relative_to(location.public));self.assertFalse(location.runtime.is_relative_to(location.public));local=DataPaths({},repo_root=self.temp.name);self.assertIsNotNone(shape_for(local.runtime_file('ai_ogrenme_gecmisi.json'),local))
    def test_budget(self):
        self.write({'kayitlar':[{'kayit_id':str(i)} for i in range(300)]});self.assertEqual(Migrator(batch_size=10).run(self.path,self.shape,budget_records=10)['status'],'BUDGET_EXHAUSTED')
    def test_source_symlink(self):
        self.write({'kayitlar':[]});link=self.path.parent/'link';link.symlink_to(self.path)
        with self.assertRaises(StorageError):checksum(link)


class V6Archives(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.source=Path(self.temp.name)/'history.json';self.source.write_bytes(b'{"history":'+b'"'+b'a'*2000000+b'"}');self.fake=FakeS3();self.archive=R2Archive(self.fake,'private-test',sleep=lambda _:None)
    def test_roundtrip(self):
        manifest=self.archive.archive(self.source);target=self.source.parent/'restore.json';self.archive.restore(manifest,target);self.assertEqual(target.read_bytes(),self.source.read_bytes())
    def test_duplicate(self):
        self.archive.archive(self.source);result=self.archive.archive(self.source);self.assertTrue(result['duplicate']);self.assertEqual(self.fake.uploads,1)
    def test_checksum_mismatch(self):
        manifest=self.archive.archive(self.source);self.fake.objects[manifest['object_key']]=b'broken'
        with self.assertRaises(StorageError):self.archive.verify(manifest['object_key'],manifest)
    def test_upload_error_preserves(self):
        before=checksum(self.source);self.fake.fail_upload=True
        with self.assertRaises(StorageError):self.archive.archive(self.source)
        self.assertEqual(checksum(self.source),before);self.assertEqual(self.fake.aborted,1)
    def test_restore_does_not_overwrite(self):
        manifest=self.archive.archive(self.source)
        with self.assertRaises(StorageError):self.archive.restore(manifest,self.source)
    def test_low_disk(self):
        manifest=self.archive.archive(self.source)
        with patch('v6_storage.r2.shutil.disk_usage',return_value=type('Usage',(),{'free':1})()),self.assertRaises(StorageError):self.archive.restore(manifest,self.source.parent/'new.json')
        self.assertFalse(list(self.source.parent.glob('.v6-restore-*')))
    def test_failed_restore_removes_only_owned_temp(self):
        manifest=self.archive.archive(self.source);self.fake.objects[manifest['object_key']]=b'bad';other=self.source.parent/'.user-unique.tmp';other.write_text('unique')
        with self.assertRaises(StorageError):self.archive.restore(manifest,self.source.parent/'new.json')
        self.assertEqual(other.read_text(),'unique');self.assertFalse(list(self.source.parent.glob('.v6-restore-*')))
    def test_no_large_temp_on_archive(self):
        self.archive.archive(self.source);self.assertEqual(list(self.source.parent.iterdir()),[self.source])
    def test_usage(self):
        self.archive.archive(self.source);result=self.archive.usage();self.assertTrue(result['complete']);self.assertGreater(result['bytes'],0)
    def test_malformed_manifest(self):
        with self.assertRaises(StorageError):self.archive.restore({'raw_size':-1},self.source.parent/'new.json')
    def test_private_confirmation(self):
        with self.assertRaises(StorageError):R2Archive(env={'R2_BUCKET':'x','R2_ENDPOINT_URL':'https://test.r2.cloudflarestorage.com'})


class V6ExtraSafety(unittest.TestCase):
    def test_duplicate_json_field(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source';path.write_text('{"kayitlar":[{"kayit_id":"a","price":1,"price":2}]}')
            self.assertEqual(Migrator().run(path,Shape('x',{'kayitlar':'list'}))['error'],'SOURCE_DUPLICATE_FIELD')
    def test_growth_alert(self):
        from v6_storage.usage import growth
        self.assertTrue(growth({'tree_bytes':200},{'tree_bytes':10},threshold=100)['alert'])
        self.assertFalse(growth({'tree_bytes':200},None)['alert'])
    def test_disk_report_private(self):
        from v6_storage.usage import disk_report
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)/'private';private.mkdir();(private/'secret-user.json').write_text('unique');report=disk_report(temp)
            self.assertEqual(report['tree_bytes'],6);self.assertNotIn('secret-user',json.dumps(report))
    def test_restart_manifest_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source';path.write_bytes(b'abc'*100000);fake=FakeS3();archive=R2Archive(fake,'private',sleep=lambda _:None);manifest=archive.archive(path);del fake.objects[manifest['object_key']+'.manifest.json'];result=archive.archive(path);self.assertTrue(result['duplicate']);self.assertEqual(fake.uploads,1)
    def test_corrupt_object_no_manifest_not_repaired(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source';path.write_bytes(b'abc'*1000);fake=FakeS3();archive=R2Archive(fake,'private',sleep=lambda _:None);manifest=archive.archive(path);del fake.objects[manifest['object_key']+'.manifest.json'];fake.objects[manifest['object_key']]=b'bad'
            with self.assertRaises(StorageError):archive.archive(path)
            self.assertFalse(manifest['object_key']+'.manifest.json' in fake.objects)
    def test_failure_classification(self):
        from gorev_hatalari import describe
        for error,expected in [('POSTGRES_OPERATION_FAILED','POSTGRES_UNAVAILABLE'),('SHADOW_MISMATCH','STORAGE_SHADOW_MISMATCH'),('IMMUTABLE_RECORD_CONFLICT','STORAGE_IMMUTABLE_CONFLICT')]:self.assertEqual(describe(StorageError(error))['code'],expected)
    def test_native_archive_stream_part_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source';path.write_bytes(os.urandom(12*1024*1024));fake=FakeS3();archive=R2Archive(fake,'private',sleep=lambda _:None);manifest=archive.archive(path)
            self.assertEqual(len(fake.parts),3);self.assertLessEqual(max(map(len,fake.parts.values())),5*1024*1024);self.assertTrue(archive.verify(manifest['object_key'],manifest))


class V6Protocols(unittest.TestCase):
    def test_boto3_s3_request(self):
        import boto3
        from botocore.stub import Stubber
        client=R2Archive(env={'R2_ENDPOINT_URL':'https://test.r2.cloudflarestorage.com','R2_BUCKET':'private','R2_ACCESS_KEY_ID':'fake','R2_SECRET_ACCESS_KEY':'fake','R2_PRIVATE_BUCKET_CONFIRMED':'true'}).client
        with Stubber(client) as stub:
            stub.add_response('head_object',{'ContentLength':5},{'Bucket':'private','Key':'x'})
            self.assertEqual(R2Archive(client,'private').call('head_object',Key='x')['ContentLength'],5)
    def test_v5_default_mapping_identity_unchanged(self):
        import time
        from atomik_temp_temizligi import HistoryStream
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'mapping';path.write_text('{"sonuclar":{"key":{"other":"key"}}}');fd=os.open(path,os.O_RDONLY)
            parser=HistoryStream(fd,time.monotonic()+10,'sonuclar',mapping=True)
            try:
                with self.assertRaises(ValueError):list(parser.entries())
            finally:parser.close();os.close(fd)
    def test_v6_optional_mapping_identity(self):
        import time
        from atomik_temp_temizligi import HistoryStream
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'mapping';path.write_text('{"events":{"key":{"source_hash":"abc"}}}');fd=os.open(path,os.O_RDONLY);parser=HistoryStream(fd,time.monotonic()+10,'events',mapping=True,mapping_identity=None)
            try:self.assertEqual(list(parser.entries()),[(None,{'source_hash':'abc'})]);self.assertEqual(parser.last_mapping_key,'key')
            finally:parser.close();os.close(fd)
    def test_unresolved_temp_never_deleted_by_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'.user-unique.tmp';path.write_text('{broken unique');before=path.read_bytes()
            from v6_storage.inventory import classify
            self.assertEqual(classify(path.name),'UNKNOWN_PRESERVE');self.assertEqual(path.read_bytes(),before)
    def test_usage_metadata_retention_only(self):
        from v6_storage.usage import measure
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BIST_DATA_DIR':temp,'STORAGE_BACKEND':'legacy'}):
            root=Path(temp);history=root/'unique-history';history.write_text('unique');state=root/'usage.json';state.write_text(json.dumps({'days':{f'2000-01-{i:02d}':{'disk':{'tree_bytes':i}} for i in range(1,31)}}));measure(root,state);self.assertLessEqual(len(json.loads(state.read_text())['days']),32);self.assertEqual(history.read_text(),'unique')


class V6Maintenance(unittest.TestCase):
    def test_postgres_preserves_v5_wal_and_sources(self):
        from disk_bakimi import DiskMaintenance
        from ana_motor import worker_lock
        import threading
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BIST_DATA_DIR':temp,'STORAGE_BACKEND':'postgres'}):
            location=DataPaths();location.ensure();target=location.runtime/'ai_ogrenme_gecmisi.json';target.write_text('{"kayitlar":[]}');wal=location.runtime/'.ai-history-pending-v4.wal';wal.write_text('unique deferred');calls=[]
            def inspector(*args,**kwargs):calls.append(kwargs);return {'scanned':0,'findings':[]}
            with worker_lock(location.runtime),patch('history_journal.HistoryJournal.flush',side_effect=AssertionError('legacy rewrite')):DiskMaintenance(location,threading.Event(),inspector=inspector).round()
            self.assertFalse(calls[0]['cleanup']);self.assertEqual(wal.read_text(),'unique deferred')


if __name__=='__main__':unittest.main()
