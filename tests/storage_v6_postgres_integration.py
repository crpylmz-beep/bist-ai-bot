"""Explicit LOCAL disposable PostgreSQL integration; not skipped in discovery.
Run with BIST_V6_TEST_DSN pointing to the owned localhost test container.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from urllib.parse import urlparse
from unittest.mock import patch
from v6_storage.config import Settings,StorageError
from v6_storage.postgres import PostgresStore
from v6_storage.records import Shape,digest
from v6_storage.migration import Migrator,checksum

DSN=os.environ.get('BIST_V6_TEST_DSN','')
if urlparse(DSN).hostname!='127.0.0.1':raise RuntimeError('Explicit owned localhost database required')


class PostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        name='v6_test_'+uuid.uuid4().hex
        with psycopg.connect(DSN,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        test_dsn=DSN.rsplit('/',1)[0]+'/'+name
        cls.store=PostgresStore(Settings(dsn=test_dsn,batch_size=10));cls.store.migrate()
    @classmethod
    def tearDownClass(cls):cls.store.close()
    def setUp(self):self.dataset=uuid.uuid4().hex+'/ai_ogrenme_gecmisi.json#kayitlar'
    def test_insert_repeat(self):
        row={'kayit_id':'a','price':10};self.assertEqual(self.store.put_rows(self.dataset,[row]).inserted,1);self.assertEqual(self.store.put_rows(self.dataset,[row]).duplicates,1);self.assertEqual(self.store.read_rows(self.dataset),[row])
    def test_completed_outcomes_frozen(self):
        row={'kayit_id':'a','price':10};self.store.put_rows(self.dataset,[row]);row['sonuc_1g']={'completed':True,'return':2};self.store.put_rows(self.dataset,[row]);row['sonuc_1g']['return']=3;self.assertEqual(self.store.put_rows(self.dataset,[row]).conflicts,1);self.assertEqual(self.store.read_rows(self.dataset)[0]['sonuc_1g']['return'],2)
    def test_prediction_frozen(self):
        self.store.put_rows(self.dataset,[{'kayit_id':'a','price':10}]);self.assertEqual(self.store.put_rows(self.dataset,[{'kayit_id':'a','price':11}]).conflicts,1);self.assertEqual(self.store.put_rows(self.dataset,[{'kayit_id':'a','price':10,'future_confidence':99}]).conflicts,1)
    def test_horizons(self):
        row={'kayit_id':'a','price':10};self.store.put_rows(self.dataset,[row]);row.update({f'sonuc_{n}g':{'completed':True,'return':n} for n in (1,3,5,10,20,60)});self.store.put_rows(self.dataset,[row]);self.assertEqual(self.store.read_rows(self.dataset),[row])
    def test_omission_no_delete(self):
        self.store.put_rows(self.dataset,[{'kayit_id':'a'},{'kayit_id':'b'}]);self.store.put_rows(self.dataset,[{'kayit_id':'a'}]);self.assertEqual(len(self.store.read_rows(self.dataset)),2)
    def test_sql_immutability(self):
        self.store.put_rows(self.dataset,[{'kayit_id':'a','price':10}])
        with self.assertRaises(StorageError):
            with self.store.transaction() as db:db.execute('UPDATE bist_v6.records SET frozen=\'{"price":20}\' WHERE dataset=%s',(self.dataset,))
        self.assertEqual(self.store.read_rows(self.dataset)[0]['price'],10)
    def test_sql_outcome_delete(self):
        self.store.put_rows(self.dataset,[{'kayit_id':'a','sonuc_1g':{'return':2}}])
        with self.assertRaises(StorageError):
            with self.store.transaction() as db:db.execute('DELETE FROM bist_v6.outcomes WHERE dataset=%s',(self.dataset,))
    def test_migration_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'history.json';doc={'version':1,'kayitlar':[{'kayit_id':str(i),'price':i} for i in range(25)]};path.write_text(json.dumps(doc));before=checksum(path);shape=Shape(self.dataset.split('#')[0],{'kayitlar':'list'});m=Migrator(self.store,10)
            self.assertEqual(m.run(path,shape,True,budget_records=10)['status'],'BUDGET_EXHAUSTED');self.assertEqual(m.run(path,shape,True)['status'],'VERIFIED');self.assertEqual(self.store.document(shape),doc);self.assertEqual(checksum(path),before);self.assertEqual(m.run(path,shape,True)['status'],'VERIFIED');self.assertEqual(len(self.store.read_rows(self.dataset)),25)
    def test_migration_conflict_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.json';shape=Shape(self.dataset.split('#')[0],{'kayitlar':'list'});m=Migrator(self.store,10);path.write_text(json.dumps({'kayitlar':[{'kayit_id':'a','price':1}]}));self.assertEqual(m.run(path,shape,True)['status'],'VERIFIED');path.write_text(json.dumps({'kayitlar':[{'kayit_id':'a','price':2}]}));before=checksum(path);self.assertEqual(m.run(path,shape,True)['status'],'UNRESOLVED');self.assertEqual(checksum(path),before);self.assertEqual(self.store.read_rows(self.dataset)[0]['price'],1)
    def test_broken_source_not_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'broken.json';path.write_text('{"kayitlar":[');shape=Shape(self.dataset.split('#')[0],{'kayitlar':'list'});self.assertEqual(Migrator(self.store).run(path,shape,True)['status'],'UNRESOLVED');self.assertFalse(self.store.verified_source(shape))
    def test_pool_failure_safe(self):
        class Broken:
            def connection(self,**kw):raise ConnectionError('secret must not escape')
        broken=PostgresStore(Settings(dsn=DSN),pool=Broken())
        with self.assertRaises(StorageError) as caught:broken.size()
        self.assertNotIn('secret',str(caught.exception))
    def test_timezone(self):
        with self.store.transaction() as db:self.assertEqual(db.execute('SHOW TIMEZONE').fetchone()['TimeZone'],'Europe/Istanbul')
    def test_order_preserved(self):
        rows=[{'kayit_id':x} for x in ('z','a','m')];self.store.put_rows(self.dataset,rows);self.assertEqual(self.store.read_rows(self.dataset),rows)
    def test_mapping_original_key(self):
        row={'source_hash':'abc'};self.store.put_rows(self.dataset,[('original',row)],kind='signal_outcome');self.assertEqual(list(self.store.read_pairs(self.dataset)),[('original',row)])
    def test_outbox_atomic_idempotence(self):
        row={'kayit_id':'a'};receipt=(self.dataset,1,digest(row));self.assertEqual(self.store.put_rows(self.dataset,[row],outbox_receipt=receipt).inserted,1);self.assertEqual(self.store.put_rows(self.dataset,[row],outbox_receipt=receipt).duplicates,1)
        with self.assertRaises(StorageError):self.store.put_rows(self.dataset,[row],outbox_receipt=(self.dataset,1,'different'))
    def test_usage(self):self.store.record_usage('2026-10-08','integration',{'bytes':1});self.assertGreater(self.store.size(),0)
    def test_job_state(self):self.store.record_job(self.dataset,{'status':'RUNNING'})
    def test_schema_repeat(self):self.assertEqual(self.store.migrate(),[])
    def test_runtime_postgres_no_full_rewrite(self):
        from veri_yollari import DataPaths
        from v6_storage.records import shape_for
        from v6_storage import backend
        from atomik_depolama import atomic_write_json
        from recovery_journal import read_document
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BIST_DATA_DIR':temp,'STORAGE_BACKEND':'postgres','STORAGE_POSTGRES_CUTOVER_ACK':'true'}),patch.object(backend,'store',return_value=self.store):
            location=DataPaths();location.ensure();path=location.runtime/'ai_ogrenme_gecmisi.json';doc={'kayitlar':[{'kayit_id':'route-a','price':10}]};path.write_text(json.dumps(doc));shape=shape_for(path,location);self.assertEqual(Migrator(self.store,10).run(path,shape,True)['status'],'VERIFIED');before=checksum(path)
            self.assertEqual(read_document(path),doc);doc['kayitlar'][0]['sonuc_1g']={'completed':True,'return':3};atomic_write_json(path,doc);self.assertEqual(checksum(path),before);self.assertEqual(read_document(path),doc);self.assertFalse(list(path.parent.glob('.user-*')))
            with patch.dict(os.environ,{'STORAGE_BACKEND':'legacy'}),self.assertRaises(StorageError):read_document(path)
            # Adopt export only into this test-owned source, then explicit rollback certification.
            path.write_text(json.dumps(doc));backend.certify_rollback(path,self.store)
            with patch.dict(os.environ,{'STORAGE_BACKEND':'legacy'}):self.assertEqual(read_document(path),doc)

    def test_native_daily_signal_first_day(self):
        from v6_storage import backend
        from veri_yollari import DataPaths
        from atomik_depolama import atomic_write_json
        from recovery_journal import read_document
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BIST_DATA_DIR':temp,'STORAGE_BACKEND':'postgres','STORAGE_POSTGRES_CUTOVER_ACK':'true'}),patch.object(backend,'store',return_value=self.store):
            location=DataPaths();location.ensure();path=location.runtime/'gunluk_al_sat_gecmisi'/'2030-01-01.json';doc={'model':'GUNLUK_AL_SAT_V1','events':{'native-a':{'event_id':'native-a','price':10}}}
            self.assertEqual(read_document(path,{'events':{}}),{'events':{}});atomic_write_json(path,doc);self.assertEqual(read_document(path),doc);self.assertEqual(json.loads(path.read_text())['events'],{})
    def test_shadow_compare(self):
        from v6_storage import backend
        from atomik_depolama import atomic_write_json
        from veri_yollari import DataPaths
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BIST_DATA_DIR':temp,'STORAGE_BACKEND':'shadow'}),patch.object(backend,'store',return_value=self.store):
            location=DataPaths();location.ensure();path=location.runtime/'tahmin_gecmisi.json';doc={'surum':1,'tahminler':[{'kayit_id':'shadow-a','price':10}],'ogrenme_gecmisi':[]};atomic_write_json(path,doc);self.assertEqual(json.loads(path.read_text()),doc)
    def test_recovery_conflicts_preserved(self):
        from recovery_journal import RecoveryJournal
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BIST_DATA_DIR':temp}):
            path=Path(temp)/'ai_ogrenme_gecmisi.json';shape=Shape(self.dataset.split('#')[0],{'kayitlar':'list'});row={'kayit_id':'recovery-a','price':10};journal=RecoveryJournal(path);journal.stage(row,'TEMP_ONLY');before=checksum(journal.path)
            result=Migrator(self.store,10).recovery(path,shape,True);self.assertEqual(result['status'],'VERIFIED');self.assertEqual(checksum(journal.path),before);changed=dict(row,price=20);self.store.put_rows(self.dataset,[(row['kayit_id'],changed)])
            self.assertEqual(self.store.read_rows(self.dataset),[row])
            other=Path(temp)/'other';other.mkdir();other_target=other/'ai_ogrenme_gecmisi.json';other_journal=RecoveryJournal(other_target);other_journal.stage(changed,'TEMP_ONLY');conflict_before=checksum(other_journal.path)
            result=Migrator(self.store,10).recovery(other_target,shape,True);self.assertEqual(result['status'],'UNRESOLVED');self.assertEqual(checksum(other_journal.path),conflict_before)
    def test_pending_wal_replay_twice(self):
        from history_journal import HistoryJournal
        from v6_storage.backend import replay
        with tempfile.TemporaryDirectory() as temp:
            journal=HistoryJournal(Path(temp)/'target');journal.path=Path(temp)/'.v6-test.wal';journal.lock=Path(temp)/'.v6-test.lock';journal.append([{'dataset':self.dataset,'id':'pending-a','record':{'kayit_id':'pending-a','price':5},'kind':'prediction'}]);before=checksum(journal.path);self.assertEqual(replay(journal,self.store),1);self.assertEqual(replay(journal,self.store),0);self.assertEqual(checksum(journal.path),before)

    def test_error_quality_source_records(self):
        self.store.put_rows(self.dataset,[{'kayit_id':'a'}]);self.store.record_quality(self.dataset,'a',{'coverage':0.5,'stale':True});self.store.register_source('test-source',{'provider':'fake','timeframe':'1d'});self.store.record_error(self.dataset,ConnectionError('not logged secret'));self.store.record_error(self.dataset,ConnectionError('different secret'))
        with self.store.transaction() as db:
            row=db.execute('SELECT * FROM bist_v6.task_errors WHERE job_id=%s',(self.dataset,)).fetchone();self.assertEqual(row['occurrences'],2);self.assertNotIn('secret',str(row['safe_payload']))
    def test_pending_on_disconnect(self):
        from v6_storage import backend
        from veri_yollari import DataPaths
        from v6_storage.records import shape_for
        from history_journal import HistoryJournal
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BIST_DATA_DIR':temp,'STORAGE_BACKEND':'postgres','STORAGE_POSTGRES_CUTOVER_ACK':'true'}):
            location=DataPaths();location.ensure();path=location.runtime/'gun_ici_sonuclar.json';doc={'kayitlar':[{'id':'pending-signal','sembol':'THYAO','sinyal_zamani':'2026-01-01T12:00:00+03:00','giris_fiyati':10,'sonuclar':{}}],'listeler':[]};selected=shape_for(path,location)
            backend._known[selected.dataset+'#kayitlar']={'pending-signal':digest(doc['kayitlar'][0])};backend._known[selected.dataset+'#listeler']={};doc['kayitlar'][0]['sonuclar']['5']={'tamamlandi':True,'getiri':1}
            with patch.object(backend,'guard',side_effect=StorageError('POSTGRES_OPERATION_FAILED')),self.assertRaises(StorageError):backend.before_write(path,doc)
            with patch.object(backend,'guard',side_effect=StorageError('POSTGRES_OPERATION_FAILED')),self.assertRaises(StorageError):backend.before_write(path,doc)
            files=list(location.runtime.glob('.v6-pending-*.wal'));self.assertEqual(len(files),1);journal=HistoryJournal(path);journal.path=files[0];transactions=list(journal.transactions());self.assertEqual(len(transactions),1);self.assertEqual(len(transactions[0]['rows']),1);self.assertFalse(path.exists())

    def test_revision_tracks_results_without_json_mtime(self):
        dataset=self.dataset.split('#')[0];self.assertEqual(self.store.revision(dataset),0);row={'kayit_id':'a','price':10};self.store.put_rows(self.dataset,[row]);first=self.store.revision(dataset);self.store.put_rows(self.dataset,[row]);self.assertEqual(self.store.revision(dataset),first);row['sonuc_3g']={'completed':True,'return':3};self.store.put_rows(self.dataset,[row]);self.assertGreater(self.store.revision(dataset),first)

    def test_active_window_matches_legacy_without_history_deletion(self):
        from v6_storage.backend import write_document
        shape=Shape(self.dataset.split('#')[0],{'kayitlar':'list'});first={'kayitlar':[{'kayit_id':'a','price':10},{'kayit_id':'b','price':20}]};write_document(self.store,shape,first)
        smaller={'kayitlar':[{'kayit_id':'b','price':20}]};write_document(self.store,shape,smaller)
        self.assertEqual(self.store.document(shape),smaller);self.assertEqual(len(self.store.read_rows(self.dataset)),2)

    def test_pending_projection_replay_preserves_active_window(self):
        from v6_storage import backend
        from veri_yollari import DataPaths
        from recovery_journal import read_document
        from history_journal import HistoryJournal
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BIST_DATA_DIR':temp,'STORAGE_BACKEND':'postgres','STORAGE_POSTGRES_CUTOVER_ACK':'true'}),patch.object(backend,'store',return_value=self.store):
            location=DataPaths();location.ensure();path=location.runtime/'ai_ogrenme_gecmisi.json';shape=Shape(self.dataset.split('#')[0],{'kayitlar':'list'});doc={'kayitlar':[{'kayit_id':'a','price':10}]};path.write_text(json.dumps(doc));self.assertEqual(Migrator(self.store,10).run(path,shape,True)['status'],'VERIFIED')
            with patch.object(backend,'shape',return_value=shape):
                self.assertEqual(read_document(path),doc);doc['kayitlar'].append({'kayit_id':'b','price':20})
                with patch.object(backend,'guard',side_effect=StorageError('POSTGRES_OPERATION_FAILED')),self.assertRaises(StorageError):backend.before_write(path,doc)
            journal=HistoryJournal(path);journal.path=next(location.runtime.glob('.v6-pending-*.wal'));self.assertEqual(backend.replay(journal,self.store),1);self.assertEqual(self.store.document(shape),doc);self.assertEqual(backend.replay(journal,self.store),0);self.assertTrue(journal.path.exists())


if __name__=='__main__':unittest.main()
