"""Recovery V5: source retention, real journals and isolated worker volumes."""
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import atomik_temp_temizligi as proof
from ana_motor import worker_lock
from atomik_depolama import atomic_write_json
from disk_forensik import inspect_atomic_temps
from disk_resumable import ResumableProof,MAX_BYTES
from recovery_journal import RecoveryJournal,read_document
from history_journal import HistoryJournal,JournalError
from proof_workspace import MemoryIndex,sqlite_issue
from storage_recovery import RECOVERED,deletion_enabled
from storage_schemas import relation,stream
from veri_yollari import DataPaths


class StorageV5Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':tmp.name,'BIST_RUNTIME_DIR':'','BIST_USER_DATA_DIR':'','STORAGE_RECOVERY_DELETE_ENABLED':'false'}))
        self.enterContext(patch('atomik_temp_temizligi.foreign_open',return_value=False))
        import storage_izleme
        self.enterContext(patch.object(storage_izleme,'_shutdown',threading.Event()))
        self.location=DataPaths();self.location.ensure()
        self.path=self.location.runtime/'ai_ogrenme_gecmisi.json'
        self.old=self.ai([self.row()]);self.path.write_text(json.dumps(self.old))

    def row(self,key='A',**kwargs):return {'kayit_id':key,'score':70,'price':100,'model':'TEST','stop':95,'target':110,**kwargs}
    def ai(self,rows):return {'kayitlar':rows,'guncelleme':'2026-10-08T11:00:00+03:00','toplam_kayit':len(rows)}
    def orphan(self,document,name='.user-legacy.tmp'):
        path=self.location.runtime/name;path.write_bytes(document if isinstance(document,bytes) else json.dumps(document).encode());os.utime(path,(0,0));return path
    def scan(self,**kwargs):
        with worker_lock(self.location.runtime):return inspect_atomic_temps(self.location,cleanup=True,resumable=True,**kwargs)
    def recover_unique(self):
        temp=self.orphan(self.ai([self.row(),self.row('NEW')]));result=self.scan();return temp,result,RecoveryJournal(self.path)

    def test_temp_only_payload_recovered_without_deleting_source(self):
        before=self.path.read_bytes();temp,result,journal=self.recover_unique();self.assertTrue(temp.exists());self.assertEqual(before,self.path.read_bytes());self.assertEqual(result['classifications'][RECOVERED],1);self.assertEqual(result['removed'],0);self.assertEqual(len(journal.operations()),1);self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_actual_frozen_prediction_payload_roundtrip(self):
        record=self.row('NEW',alim_bolgesi=[98,100],model_version='V1',zaman='2026-10-08T11:00:00+03:00',sonuc_60g=None);self.orphan(self.ai([self.row(),record]));self.scan();self.assertEqual(read_document(self.path)['kayitlar'][-1],record)
    def test_duplicate_journal_not_appended_on_second_run(self):
        temp,_,journal=self.recover_unique();size=journal.path.stat().st_size;result=self.scan();self.assertEqual(journal.path.stat().st_size,size);self.assertEqual(result['recovery_summary']['records_recovered'],0);self.assertEqual(result['recovery_summary']['duplicates_skipped'],1);self.assertTrue(temp.exists())
    def test_identical_and_final_only(self):
        self.path.write_text(json.dumps(self.ai([self.row(),self.row('FINAL_ONLY')])));self.orphan(self.ai([self.row()]));result=self.scan();self.assertEqual(result['removed'],1);self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_final_newer_completed_outcome(self):
        self.path.write_text(json.dumps(self.ai([self.row(sonuc_1g={'getiri':2})])));self.orphan(self.ai([self.row(sonuc_1g=None)]));result=self.scan();self.assertEqual(result['removed'],1);self.assertEqual(result['recovery_summary']['records_recovered'],0)
    def test_temp_newer_completed_outcome_overlay(self):
        self.path.write_text(json.dumps(self.ai([self.row(sonuc_1g=None)])));temp=self.orphan(self.ai([self.row(sonuc_1g={'getiri':2})]));result=self.scan();self.assertTrue(temp.exists());self.assertEqual(read_document(self.path)['kayitlar'][0]['sonuc_1g'],{'getiri':2});self.assertEqual(result['classifications'][RECOVERED],1)
    def test_frozen_field_conflict_preserved(self):
        temp=self.orphan(self.ai([self.row(score=80)]));before=temp.read_bytes();result=self.scan();self.assertEqual(temp.read_bytes(),before);self.assertEqual(result['removed'],0);self.assertEqual(result['recovery_summary']['conflicts'],1);self.assertFalse(RecoveryJournal(self.path).path.exists())
        self.assertEqual(result['findings'][0]['recovery']['final_only'],0)
    def test_two_completed_outcomes_conflict_preserved(self):
        self.path.write_text(json.dumps(self.ai([self.row(sonuc_1g={'getiri':2})])));temp=self.orphan(self.ai([self.row(sonuc_1g={'getiri':3})]));self.scan();self.assertTrue(temp.exists());self.assertEqual(read_document(self.path)['kayitlar'][0]['sonuc_1g']['getiri'],2)
    def test_immutable_target_conflict(self):
        temp=self.orphan(self.ai([self.row(target=120)]));result=self.scan();self.assertEqual(result['recovery_summary']['conflicts'],1);self.assertTrue(temp.exists())
    def test_missing_frozen_field_is_unresolved(self):
        self.old['kayitlar'][0].pop('target');self.path.write_text(json.dumps(self.old));temp=self.orphan(self.ai([self.row()]));result=self.scan();self.assertTrue(temp.exists());self.assertEqual(result['recovery_summary']['unresolved'],1)
    def test_conflict_and_unique_same_file_only_safe_row_recovered(self):
        temp=self.orphan(self.ai([self.row(score=99),self.row('NEW')]));result=self.scan();self.assertTrue(temp.exists());self.assertEqual(result['removed'],0);self.assertEqual(result['recovery_summary']['conflicts'],1);self.assertEqual(result['recovery_summary']['records_recovered'],1);self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_unknown_unrelated_schema_kept(self):
        temp=self.orphan({'UNIQUE':'KEEP'});before=temp.read_bytes();self.scan();self.assertEqual(temp.read_bytes(),before)
    def test_root_unique_metadata_preserved(self):
        value=self.ai([self.row(),self.row('NEW')]);value['private_metadata']='UNIQUE';temp=self.orphan(value);result=self.scan();self.assertTrue(temp.exists());self.assertEqual(result['removed'],0);self.assertEqual(result['recovery_summary']['records_recovered'],1)
    def test_future_root_timestamp_keeps_file(self):
        value=self.ai([self.row(),self.row('NEW')]);value['guncelleme']='2026-10-09T11:00:00+03:00';temp=self.orphan(value);self.scan();self.assertTrue(temp.exists())

    def test_journal_capacity_full_keeps_source_and_prior_payload(self):
        temp,_,journal=self.recover_unique();before=journal.path.read_bytes();self.orphan(self.ai([self.row(),self.row('OTHER')]),'.user-other.tmp')
        with patch('history_journal.MAX_WAL',len(before)):result=self.scan()
        self.assertEqual(journal.path.read_bytes(),before);self.assertTrue(temp.exists());self.assertEqual(result['removed'],0)
    def test_journal_checksum_corruption_never_authorizes_delete(self):
        temp,_,journal=self.recover_unique();value=json.loads(journal.path.read_text());value['checksum']='BAD';journal.path.write_text(json.dumps(value)+'\n');before=journal.path.read_bytes();result=self.scan();self.assertTrue(temp.exists());self.assertEqual(before,journal.path.read_bytes());self.assertEqual(result['removed'],0);self.assertRaises(JournalError,read_document,self.path)
    def test_journal_torn_transaction_preserved(self):
        journal=RecoveryJournal(self.path);journal.path.write_bytes(b'{"sequence":');temp=self.orphan(self.ai([self.row('NEW')]));self.scan();self.assertTrue(temp.exists());self.assertEqual(journal.path.read_bytes(),b'{"sequence":')
    def test_journal_sequence_corruption_preserved(self):
        temp,_,journal=self.recover_unique();entry=json.loads(journal.path.read_text());entry['sequence']=2;journal.path.write_text(json.dumps(entry)+'\n');self.scan();self.assertTrue(temp.exists());self.assertRaises(JournalError,journal.operations)
    def test_journal_fsync_failure_no_delete(self):
        temp=self.orphan(self.ai([self.row(),self.row('NEW')]))
        with patch('history_journal.os.fsync',side_effect=OSError(errno.EIO,'test fsync')):result=self.scan()
        self.assertTrue(temp.exists());self.assertEqual(result['removed'],0)
    def test_ambiguous_fsync_is_resynced_before_duplicate_ack(self):
        journal=RecoveryJournal(self.path)
        with patch('history_journal.os.fsync',side_effect=OSError(errno.EIO,'test fsync')):self.assertRaises(OSError,journal.stage,self.row('NEW'),'TEMP_ONLY')
        with patch('history_journal.os.fsync',wraps=os.fsync) as sync:self.assertFalse(journal.stage(self.row('NEW'),'TEMP_ONLY'))
        self.assertGreaterEqual(sync.call_count,2)
    def test_transient_fsync_failure_does_not_poison_resumed_proof(self):
        temp=self.orphan(self.ai([self.row(),self.row('NEW')]))
        with patch('history_journal.os.fsync',side_effect=OSError(errno.EIO,'test fsync')):self.scan()
        self.assertTrue(temp.exists())
        result=self.scan()
        self.assertEqual(result['classifications'][RECOVERED],1)
        self.assertEqual(result['recovery_summary']['unresolved'],0)
        self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_journal_private_permissions_and_location(self):
        _,_,journal=self.recover_unique();self.assertTrue(journal.path.is_relative_to(self.location.runtime));self.assertEqual(journal.path.stat().st_mode&0o777,0o600);self.assertFalse(list(self.location.public.glob('*.wal')))
    def test_public_recovery_journal_forbidden(self):self.assertRaises(ValueError,RecoveryJournal,self.location.public/'ai_ogrenme_gecmisi.json')
    def test_unsupported_dataset_journal_forbidden(self):self.assertRaises(ValueError,RecoveryJournal,self.location.runtime/'unknown.json')
    def test_overlay_replay_idempotency(self):
        self.recover_unique();first=read_document(self.path);second=RecoveryJournal(self.path).overlay(first);self.assertEqual(first,second);self.assertEqual(len(first['kayitlar']),2)
    def test_overlay_after_canonical_merge_no_duplicate(self):
        self.recover_unique();document=read_document(self.path);self.path.write_text(json.dumps(document));self.assertEqual(read_document(self.path),document)
    def test_normal_producer_commit_cannot_drop_recovered_record(self):
        self.recover_unique();atomic_write_json(self.path,self.old);self.assertEqual(len(json.loads(self.path.read_text())['kayitlar']),2)
    def test_canonical_conflict_after_recovery_keeps_both(self):
        self.recover_unique();document=self.ai([self.row(),self.row('NEW',score=90)]);self.path.write_text(json.dumps(document));self.assertEqual(read_document(self.path)['kayitlar'][1]['score'],90);self.assertEqual(len(RecoveryJournal(self.path).operations()),1)
    def test_ai_and_performance_load_see_overlay(self):
        self.recover_unique();from ai_karar_motoru import load;from performans_motoru import load as performance_load
        self.assertEqual(len(load(self.path,{})['kayitlar']),2);self.assertEqual(len(performance_load(self.path,{})['kayitlar']),2)
    def test_v4_pending_wal_can_coexist_and_merge(self):
        self.recover_unique();value=read_document(self.path);value['kayitlar'][0]['sonuc_1g']={'getiri':2};journal=HistoryJournal(self.path);journal.queue_state(value);self.assertEqual(journal.flush(),1);self.assertEqual(len(read_document(self.path)['kayitlar']),2)

    def test_new_delete_flag_default_off(self):
        with patch.dict(os.environ,{},clear=True):self.assertFalse(deletion_enabled())
    def test_new_delete_flag_false(self):self.assertFalse(deletion_enabled())
    def test_new_delete_flag_true_only(self):
        with patch.dict(os.environ,{'STORAGE_RECOVERY_DELETE_ENABLED':'true'}):self.assertTrue(deletion_enabled())
    def test_opt_in_recovery_delete_requires_fresh_replay(self):
        temp,_,journal=self.recover_unique()
        with patch.dict(os.environ,{'STORAGE_RECOVERY_DELETE_ENABLED':'true'}):result=self.scan()
        self.assertFalse(temp.exists());self.assertEqual(result['recovery_summary']['files_deleted'],1);self.assertTrue(journal.path.exists());self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_conflict_not_deleted_even_if_flag_true(self):
        temp=self.orphan(self.ai([self.row(score=99)]))
        with patch.dict(os.environ,{'STORAGE_RECOVERY_DELETE_ENABLED':'true'}):result=self.scan()
        self.assertTrue(temp.exists());self.assertEqual(result['removed'],0)
    def test_source_recent_no_recovery(self):
        temp=self.orphan(self.ai([self.row('NEW')]));os.utime(temp,None);self.scan();self.assertFalse(RecoveryJournal(self.path).path.exists());self.assertTrue(temp.exists())
    def test_source_active_lease_no_recovery(self):
        import fcntl
        temp=self.orphan(self.ai([self.row('NEW')]));fd=os.open(temp,os.O_RDWR)
        try:fcntl.flock(fd,fcntl.LOCK_EX);self.scan();self.assertFalse(RecoveryJournal(self.path).path.exists())
        finally:os.close(fd)
    def test_worker_scope_required(self):
        temp=self.orphan(self.ai([self.row('NEW')]));result=inspect_atomic_temps(self.location,cleanup=True,resumable=True);self.assertTrue(temp.exists());self.assertEqual(result['removed'],0);self.assertFalse(RecoveryJournal(self.path).path.exists())
    def test_readonly_does_not_recover(self):
        self.orphan(self.ai([self.row('NEW')]));inspect_atomic_temps(self.location,cleanup=False,resumable=True);self.assertFalse(RecoveryJournal(self.path).path.exists())
    def test_truncated_tail_recovers_complete_unique_record_but_keeps_file(self):
        value=json.dumps(self.ai([self.row(),self.row('NEW')])).encode();temp=self.orphan(value[:value.index(b'],')]+b', {"kayit_id":"unfinished');before=temp.read_bytes();result=self.scan();self.assertEqual(temp.read_bytes(),before);self.assertEqual(result['removed'],0);self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_invalid_record_not_recovered(self):
        temp=self.orphan(self.ai([{'score':70}]));self.scan();self.assertTrue(temp.exists());self.assertFalse(RecoveryJournal(self.path).path.exists())
    def test_duplicate_source_id_keeps_file(self):
        temp=self.orphan(self.ai([self.row('NEW'),self.row('NEW')]));result=self.scan();self.assertTrue(temp.exists());self.assertEqual(result['removed'],0);self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_partial_last_record_is_not_fabricated(self):
        temp=self.orphan(b'{"kayitlar":[{"kayit_id":"HALF","score":');self.scan();self.assertTrue(temp.exists());self.assertFalse(RecoveryJournal(self.path).path.exists())

    def test_sqlite_full_real_error_code_and_errno_none(self):
        database=self.location.runtime/'test-index.sqlite';db=sqlite3.connect(database);self.addCleanup(db.close);db.execute('PRAGMA max_page_count=4');db.execute('CREATE TABLE rows(payload BLOB)')
        try:
            for _ in range(100):db.execute('INSERT INTO rows VALUES(?)',(b'x'*4096,))
        except sqlite3.OperationalError as error:
            self.assertIsNone(getattr(error,'errno',None));self.assertEqual(error.sqlite_errorcode&255,sqlite3.SQLITE_FULL);self.assertEqual(sqlite_issue(error,'TEST_INSERT'),'PROOF_DEFERRED_LOW_WORKSPACE')
        else:self.fail('SQLite FULL not reproduced')
    def test_sqlite_locked_actual_code_distinguished(self):
        file=self.location.runtime/'locks.sqlite';one=sqlite3.connect(file);two=sqlite3.connect(file,timeout=0);self.addCleanup(one.close);self.addCleanup(two.close);one.execute('CREATE TABLE rows(v INTEGER)');one.commit();one.execute('INSERT INTO rows VALUES(1)')
        try:two.execute('INSERT INTO rows VALUES(2)')
        except sqlite3.OperationalError as error:self.assertEqual(sqlite_issue(error,'TEST_INSERT'),'PROOF_INDEX_LOCKED')
        else:self.fail('SQLite BUSY not reproduced')
    def test_sqlite_unavailable_safe_ram_fallback(self):
        temp=self.orphan(self.ai([self.row(),self.row('NEW')]))
        with patch.object(ResumableProof,'_final',side_effect=sqlite3.OperationalError('simulated unavailable')):result=self.scan()
        self.assertEqual(result['recovery_summary']['records_recovered'],1);self.assertTrue(temp.exists());self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_low_workspace_fallback_does_not_use_sqlite(self):
        self.orphan(self.ai([self.row(),self.row('NEW')]))
        with patch('proof_workspace.headroom',side_effect=__import__('proof_workspace').WorkspaceDeferred('PROOF_DEFERRED_LOW_WORKSPACE')),patch.object(ResumableProof,'_final',side_effect=AssertionError('SQLite forbidden')):result=self.scan()
        self.assertEqual(result['recovery_summary']['records_recovered'],1)
    def test_index_directory_unavailable_bounded_ram_recovery(self):
        self.orphan(self.ai([self.row(),self.row('NEW')]))
        original=Path.mkdir
        def mkdir(path,*args,**kwargs):
            if path.name.startswith('bist-proof-v4-'):raise OSError(errno.ENOSPC,'test workspace full')
            return original(path,*args,**kwargs)
        with patch.object(Path,'mkdir',mkdir):result=self.scan()
        self.assertEqual(result['recovery_summary']['records_recovered'],1)
        self.assertEqual(len(read_document(self.path)['kayitlar']),2)
    def test_index_filesystem_io_error_uses_bounded_fallback(self):
        self.orphan(self.ai([self.row(),self.row('NEW')]))
        with patch.object(ResumableProof,'_final',side_effect=OSError(errno.EACCES,'test access')):result=self.scan()
        self.assertEqual(result['recovery_summary']['records_recovered'],1)
    def test_seen_resume_sqlite_failure_defers_then_falls_back(self):
        from proof_workspace import SqlIndex
        temp=self.orphan(self.ai([self.row(),self.row('NEW')]))
        with patch.object(SqlIndex,'resume_seen',side_effect=sqlite3.OperationalError('test transaction failure')):result=self.scan()
        self.assertTrue(temp.exists());self.assertEqual(result['removed'],0)
        self.assertIn('PROOF_SQLITE_FALLBACK_PENDING',result['reasons'])
        result=self.scan();self.assertEqual(result['recovery_summary']['records_recovered'],1)
    def test_ram_capacity_deferred_not_delete(self):
        temp=self.orphan(self.ai([self.row(),self.row('NEW')]))
        with patch.object(ResumableProof,'_final',side_effect=sqlite3.OperationalError('unavailable')),patch('proof_workspace.MAX_ENTRIES',0):result=self.scan()
        self.assertTrue(temp.exists());self.assertEqual(result['removed'],0);self.assertIn('PROOF_DEFERRED_LOW_WORKSPACE',result['reasons'])

    def news(self,key):return {'canonical_id':key,'sembol':'THYAO','ana_baslik':'Haber','ilk_gorulme':'2026-10-08T11:00:00+03:00','variants':[{'normalized_title':'haber','content_hash':key}],'effects':{},'analiz':{'etki_puani':5}}
    def test_news_stream_recovery(self):
        self.path=self.location.runtime/'haber_dedup.json';self.path.write_text(json.dumps({'surum':1,'haberler':[self.news('A')]}));temp=self.orphan({'surum':1,'haberler':[self.news('A'),self.news('NEW')]});result=self.scan();self.assertEqual(result['recovery_summary']['records_recovered'],1);self.assertEqual(len(read_document(self.path)['haberler']),2);self.assertTrue(temp.exists())
    def test_news_changed_analysis_conflict(self):
        self.path=self.location.runtime/'haber_dedup.json';self.path.write_text(json.dumps({'surum':1,'haberler':[self.news('A')]}));row=self.news('A');row['analiz']['etki_puani']=9;temp=self.orphan({'surum':1,'haberler':[row]});result=self.scan();self.assertEqual(result['recovery_summary']['conflicts'],1);self.assertTrue(temp.exists())
    def test_news_large_stream_adapter_not_full_json(self):
        self.path=self.location.runtime/'haber_dedup.json';rows=[dict(self.news(str(i)),padding='x'*1000) for i in range(8000)];self.path.write_text(json.dumps({'surum':1,'haberler':rows}));old={'surum':1,'haberler':rows[:-1]};temp=self.orphan(old)
        with patch('disk_forensik.small_json',side_effect=AssertionError('full JSON forbidden')):result=self.scan()
        self.assertFalse(temp.exists());self.assertEqual(result['removed'],1)
    def results(self,rows):return {'updated_at':'2026-10-08T11:00:00+03:00','sonuclar':{r['kayit_id']:r for r in rows}}
    def test_results_mapping_stream_recovery(self):
        self.path=self.location.runtime/'yarin_top10_sonuclar.json';self.path.write_text(json.dumps(self.results([self.row()])));temp=self.orphan(self.results([self.row(),self.row('NEW')]));result=self.scan();self.assertEqual(result['recovery_summary']['records_recovered'],1);self.assertEqual(set(read_document(self.path)['sonuclar']),{'A','NEW'});self.assertTrue(temp.exists())
    def test_results_completed_outcome_conflict(self):
        self.path=self.location.runtime/'yarin_top10_sonuclar.json';self.path.write_text(json.dumps(self.results([self.row(sonuc_60g={'getiri':4})])));temp=self.orphan(self.results([self.row(sonuc_60g={'getiri':5})]));self.scan();self.assertTrue(temp.exists());self.assertEqual(read_document(self.path)['sonuclar']['A']['sonuc_60g']['getiri'],4)
    def test_mapping_key_mismatch_unknown(self):
        self.path=self.location.runtime/'yarin_top10_sonuclar.json';self.path.write_text(json.dumps(self.results([self.row()])));temp=self.orphan({'sonuclar':{'WRONG':self.row('NEW')}});result=self.scan();self.assertTrue(temp.exists());self.assertEqual(result['removed'],0)
    def test_mapping_duplicate_key_unknown(self):
        self.path=self.location.runtime/'yarin_top10_sonuclar.json';self.path.write_text(json.dumps(self.results([self.row()])));row=json.dumps(self.row('NEW'));temp=self.orphan(('{"sonuclar":{"NEW":'+row+',"NEW":'+row+'}}').encode());self.scan();self.assertTrue(temp.exists())

    def test_recovery_logs_contain_counts_not_payload(self):
        record=self.row('SECRET_RECORD',note='DO_NOT_LOG');self.orphan(self.ai([record]))
        with self.assertLogs(level='INFO') as logs:self.scan()
        text='\n'.join(logs.output);self.assertIn('STORAGE_RECOVERY_SUMMARY',text);self.assertIn('journal_added',text);self.assertNotIn('DO_NOT_LOG',text);self.assertNotIn('SECRET_RECORD',text)
    def test_checkpoint_contains_no_recovered_payload(self):
        self.orphan(self.ai([self.row('SECRET_RECORD')]));self.scan();raw=(self.location.runtime/'disk_forensic_checkpoint.json').read_bytes();self.assertLess(len(raw),MAX_BYTES);self.assertNotIn(b'SECRET_RECORD',raw);self.assertNotIn(b'"price"',raw)
    def test_critical_recovery_no_large_temp_or_full_rewrite(self):
        temp=self.orphan(self.ai([self.row(),self.row('NEW')]));before=self.path.read_bytes();usage=shutil._ntuple_diskusage(5*1024**3,4700*1024**2,420*1024**2);original=__import__('atomik_depolama').tempfile.mkstemp
        def allocate(**kwargs):
            if kwargs.get('prefix','').startswith('.user-v2-'+hashlib.sha256(self.path.name.encode()).hexdigest()[:24]):raise AssertionError('AI full rewrite forbidden')
            return original(**kwargs)
        with patch('shutil.disk_usage',return_value=usage),patch('atomik_depolama.tempfile.mkstemp',side_effect=allocate):result=self.scan()
        self.assertEqual(self.path.read_bytes(),before);self.assertTrue(temp.exists());self.assertEqual(result['recovery_summary']['records_recovered'],1)

    def test_resumable_recovery_survives_fresh_session_and_memory_loss(self):
        self.path.write_text(json.dumps(self.ai([self.row(str(i)) for i in range(500)])));temp=self.orphan(self.ai([self.row(str(i)) for i in range(500)]+[self.row('NEW')]))
        a=os.open(temp,os.O_RDONLY);b=os.open(self.path,os.O_RDONLY);self.addCleanup(os.close,a);self.addCleanup(os.close,b);answer=None;rounds=0;counts=[]
        while answer is None and rounds<60:
            rounds+=1;session=ResumableProof(self.location,recover=True);calls=0
            def limited(*args):
                nonlocal calls
                calls+=1
                if calls>70:raise TimeoutError('test round budget')
            try:
                with patch.object(proof,'check_deadline',side_effect=limited):
                    try:answer=session.prove(a,b,self.path.name,'masked',float('inf'))
                    except TimeoutError:pass
                counts.append(session.data['files']['masked']['count'])
            finally:session.close()
            # Simulate a fresh worker process: persistent indexes must resume.
            import storage_recovery,proof_workspace
            storage_recovery._seen.clear();proof_workspace._cache.clear()
        self.assertIsNotNone(answer);self.assertEqual(answer[0],RECOVERED);self.assertGreater(rounds,2);self.assertEqual(counts,sorted(counts));self.assertEqual(len(read_document(self.path)['kayitlar']),501)

    def test_checkpoint_source_fingerprint_change_revalidates_recovery(self):
        temp,_,journal=self.recover_unique();document=self.ai([self.row(),self.row('DIFFERENT')]);temp.write_text(json.dumps(document));os.utime(temp,(0,0));self.scan();self.assertEqual(len(journal.operations()),2);self.assertEqual(len(read_document(self.path)['kayitlar']),3);self.assertTrue(temp.exists())

    def test_sqlite_initialization_failure_closes_connection(self):
        session=ResumableProof(self.location);connection=unittest.mock.Mock();connection.execute.side_effect=sqlite3.OperationalError('test initialization failure')
        with patch('disk_resumable.sqlite3.connect',return_value=connection):self.assertRaises(sqlite3.OperationalError,session._db,'a'*40)
        connection.close.assert_called_once();session.close()

    def test_journal_nonobject_json_is_explicit_corruption(self):
        journal=RecoveryJournal(self.path);journal.path.write_bytes(b'[]\n');self.assertRaises(JournalError,journal.operations)

    def test_journal_nonfinite_json_is_explicit_corruption(self):
        journal=RecoveryJournal(self.path);journal.path.write_bytes(b'{"sequence":1,"payload":NaN}\n');self.assertRaises(JournalError,journal.operations)

    def test_no_payload_decoder_leak_when_wal_invalid(self):
        self.orphan(self.ai([self.row('NEW')]));journal=RecoveryJournal(self.path);journal.path.write_bytes(b'[]\n')
        before=len(os.listdir('/proc/self/fd'))
        for _ in range(5):self.scan()
        self.assertLessEqual(len(os.listdir('/proc/self/fd')),before+1)

    def test_every_record_relation_class(self):
        row=self.row();self.assertEqual(relation(row,row,self.path.name),'IDENTICAL');self.assertEqual(relation(row,None,self.path.name),'TEMP_ONLY');self.assertEqual(relation(row,dict(row,sonuc_1g={'getiri':2}),self.path.name),'FINAL_NEWER_SAFE');self.assertEqual(relation(dict(row,sonuc_1g={'getiri':2}),row,self.path.name),'TEMP_NEWER_SAFE');self.assertEqual(relation(row,dict(row,score=99),self.path.name),'CONFLICT');missing=dict(row);missing.pop('target');self.assertEqual(relation(row,missing,self.path.name),'UNRESOLVED')


if __name__=='__main__':unittest.main()
