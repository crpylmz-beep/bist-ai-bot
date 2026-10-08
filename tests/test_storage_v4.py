"""Storage V4: isolated volumes, real file commits, no production data/providers."""
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import atomik_depolama as atomic
import atomik_temp_temizligi as proof
import storage_izleme as trace
from ana_motor import worker_lock
from disk_bakimi import DiskMaintenance
from disk_forensik import inspect_atomic_temps
from disk_resumable import ResumableProof, MAX_BYTES
from history_journal import HistoryJournal, JournalError, field_patch, identity
from veri_yollari import DataPaths


class StorageV4Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':tmp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':tmp.name,'BIST_RUNTIME_DIR':'','BIST_USER_DATA_DIR':''}))
        self.enterContext(patch.object(trace,'_shutdown',threading.Event()))
        self.enterContext(patch.object(trace,'_bound_worker',None))
        self.enterContext(patch.object(trace,'_stats',trace.OrderedDict()))
        self.enterContext(patch.object(proof,'foreign_open',return_value=False))
        self.target=self.location.runtime/'ai_ogrenme_gecmisi.json'
        self.value=self.history()
        self.target.write_text(json.dumps(self.value,ensure_ascii=False))
        self.journal=HistoryJournal(self.target)

    def history(self,n=3,padding=0):
        return {'kayitlar':[{'kayit_id':str(i),'score':70,'padding':'a'*padding} for i in range(n)],'guncelleme':'2026-10-08T11:00:00+03:00','toplam_kayit':n}

    def operation(self,i=0,value=2):
        row=self.value['kayitlar'][i]
        return {'id':identity(row),'fields':field_patch(row,dict(row,sonuc_1g={'getiri':value}))}

    def actual(self):return json.loads(self.target.read_text())
    def temps(self):return list(self.location.runtime.glob('.user-*.tmp'))
    def scan(self,**kwargs):
        with worker_lock(self.location.runtime):return inspect_atomic_temps(self.location,cleanup=True,resumable=True,**kwargs)
    def orphan(self,data,name='.user-legacy.tmp'):
        temp=self.location.runtime/name;temp.write_bytes(data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode());os.utime(temp,(0,0));return temp
    def large(self):
        self.value=self.history(600,2000);self.target.write_text(json.dumps(self.value));return copy.deepcopy(self.value)

    def test_same_final_thread_and_process_lock_max_one_temp(self):
        original=atomic.tempfile.mkstemp;counts=[];guard=threading.Lock()
        def allocate(**kwargs):
            answer=original(**kwargs)
            with guard:counts.append(len(self.temps()))
            return answer
        with patch.object(atomic.tempfile,'mkstemp',side_effect=allocate),ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda n:atomic.atomic_write_json(self.target,{'version':n}),range(12)))
        self.assertEqual(max(counts),1);self.assertFalse(self.temps());self.assertIn(self.actual()['version'],range(12))

    def test_unchanged_timestamp_only_does_not_allocate(self):
        value=self.large();value['guncelleme']='2026-10-08T12:00:00+03:00';before=self.target.read_bytes()
        with patch.object(atomic.tempfile,'mkstemp',side_effect=AssertionError('temp forbidden')),self.assertLogs(level='INFO') as logs:atomic.atomic_write_json(self.target,value)
        self.assertEqual(before,self.target.read_bytes());self.assertIn('SKIP_UNCHANGED_WRITE','\n'.join(logs.output))

    def test_dirty_check_does_not_ignore_removed_row(self):
        value=self.large();value['kayitlar'].pop();same,_=atomic.unchanged_history(self.target,value);self.assertFalse(same)
    def test_dirty_check_does_not_ignore_order(self):
        value=self.large();value['kayitlar'].reverse();self.assertFalse(atomic.unchanged_history(self.target,value)[0])
    def test_dirty_check_does_not_ignore_results(self):
        value=self.large();value['kayitlar'][0]['sonuc_60g']={'getiri':8};self.assertFalse(atomic.unchanged_history(self.target,value)[0])
    def test_dirty_check_does_not_accept_old_clock(self):
        value=self.large();value['guncelleme']='2025-01-01';self.assertFalse(atomic.unchanged_history(self.target,value)[0])

    def test_100_deltas_coalesce_into_one_commit(self):
        self.value=self.history(100);self.target.write_text(json.dumps(self.value))
        for i in range(100):self.journal.append([self.operation(i)])
        original=atomic.tempfile.mkstemp
        with patch.object(atomic.tempfile,'mkstemp',wraps=original) as allocate:self.assertEqual(self.journal.flush(),100)
        self.assertEqual(allocate.call_count,1);self.assertEqual(sum('sonuc_1g' in r for r in self.actual()['kayitlar']),100);self.assertFalse(self.temps())

    def test_wal_replay_and_second_flush_noop(self):
        self.journal.append([self.operation()]);self.assertEqual(self.journal.flush(),1);self.assertEqual(self.journal.flush(),0);self.assertEqual(self.actual()['kayitlar'][0]['sonuc_1g']['getiri'],2)
    def test_wal_replay_after_commit_before_unlink_is_idempotent(self):
        self.journal.append([self.operation()]);wal=self.journal.path.read_bytes();self.journal.flush();self.journal.path.write_bytes(wal);self.journal.flush();self.assertEqual(self.actual()['kayitlar'][0]['sonuc_1g']['getiri'],2)
    def test_wal_add_then_update_replay_after_commit(self):
        row={'kayit_id':'NEW','score':77};self.journal.append([{'id':identity(row),'add':row}]);self.journal.append([{'id':identity(row),'fields':field_patch(row,dict(row,sonuc_3g={'getiri':4}))}]);wal=self.journal.path.read_bytes();self.journal.flush();self.journal.path.write_bytes(wal);self.journal.flush();self.assertEqual(len(self.actual()['kayitlar']),4)
    def test_wal_checksum_corrupt_preserves_canonical_and_wal(self):
        self.journal.append([self.operation()]);entry=json.loads(self.journal.path.read_text());entry['checksum']='BAD';self.journal.path.write_text(json.dumps(entry)+'\n');before=self.target.read_bytes();wal=self.journal.path.read_bytes()
        self.assertRaises(JournalError,self.journal.flush);self.assertEqual(before,self.target.read_bytes());self.assertEqual(wal,self.journal.path.read_bytes())
    def test_wal_torn_line_is_not_truncated(self):
        self.journal.path.write_bytes(b'{"sequence":1');self.assertRaises(JournalError,self.journal.append,[]);self.assertEqual(self.journal.path.read_bytes(),b'{"sequence":1')
    def test_wal_wrong_sequence_rejected(self):
        self.journal.append([self.operation()]);entry=json.loads(self.journal.path.read_text());entry['sequence']=2;self.journal.path.write_text(json.dumps(entry)+'\n');self.assertRaises(JournalError,self.journal.flush)
    def test_wal_conflicting_outcome_is_not_silently_overwritten(self):
        self.journal.append([self.operation()]);v=self.actual();v['kayitlar'][0]['sonuc_1g']={'getiri':99};self.target.write_text(json.dumps(v));before=self.target.read_bytes();self.assertRaises(JournalError,self.journal.flush);self.assertEqual(before,self.target.read_bytes());self.assertTrue(self.journal.path.exists())
    def test_wal_capacity_preserves_previous_transactions(self):
        self.journal.append([self.operation()]);before=self.journal.path.read_bytes()
        with patch('history_journal.MAX_WAL',len(before)):self.assertRaises(OSError,self.journal.append,[self.operation(1)])
        self.assertEqual(before,self.journal.path.read_bytes())
    def test_wal_fsync_before_acknowledgement(self):
        with patch('history_journal.os.fsync',side_effect=OSError(errno.EIO,'failed fsync')):self.assertRaises(OSError,self.journal.append,[self.operation()])
        self.assertEqual(self.actual(),self.value);self.assertTrue(self.journal.path.exists())
    def test_wal_public_root_forbidden(self):self.assertRaises(ValueError,HistoryJournal,self.location.public/'ai_ogrenme_gecmisi.json')
    def test_pending_wal_private_and_not_public(self):
        self.journal.append([self.operation()]);self.assertTrue(self.journal.path.is_relative_to(self.location.runtime));self.assertFalse(list(self.location.public.glob('*.wal')));self.assertEqual(self.journal.path.stat().st_mode&0o777,0o600)

    def test_insufficient_headroom_before_temp_retains_intent(self):
        value=self.large();value['kayitlar'][0]['sonuc_1g']={'getiri':2};before=self.target.read_bytes();usage=shutil._ntuple_diskusage(5*1024**3,5*1024**3-300000,300000)
        with patch('shutil.disk_usage',return_value=usage),patch.object(atomic.tempfile,'mkstemp',side_effect=AssertionError('no large temp')):self.assertRaises(OSError,atomic.atomic_write_json,self.target,value)
        self.assertEqual(before,self.target.read_bytes());self.assertTrue(self.journal.path.exists());self.assertEqual(self.journal.flush(),1)
    def test_critical_with_headroom_queues_not_full_rewrite(self):
        value=self.large();value['kayitlar'][0]['sonuc_1g']={'getiri':2};usage=shutil._ntuple_diskusage(5*1024**3,4700*1024**2,420*1024**2)
        with patch('shutil.disk_usage',return_value=usage),patch.object(atomic.tempfile,'mkstemp',side_effect=AssertionError('no critical temp')):self.assertRaises(trace.StoragePendingError,atomic.atomic_write_json,self.target,value)
        self.assertLess(self.journal.path.stat().st_size,4096)
    def test_critical_cache_recreation_skipped(self):
        from disk_koruma import save_price_cache
        with patch.object(trace,'critical_storage',return_value=True):self.assertFalse(save_price_cache(self.location.runtime/'prices.json',{'X':100}))
        self.assertFalse((self.location.runtime/'prices.json').exists())
    def test_pending_queue_preserves_omitted_history(self):
        value=copy.deepcopy(self.value);value['kayitlar'].pop();value['kayitlar'][0]['sonuc_60g']={'getiri':4};self.journal.queue_state(value);self.journal.flush();self.assertEqual(len(self.actual()['kayitlar']),3);self.assertEqual(self.actual()['kayitlar'][0]['sonuc_60g']['getiri'],4)
    def test_pending_queue_preserves_omitted_fields(self):
        value=copy.deepcopy(self.value);del value['kayitlar'][0]['score'];value['kayitlar'][0]['sonuc_20g']={'getiri':8};self.journal.queue_state(value);self.journal.flush();self.assertEqual(self.actual()['kayitlar'][0]['score'],70)

    def test_sigterm_before_large_write(self):
        value=self.large();trace.shutdown_writes();before=self.target.read_bytes();self.assertRaises(OSError,atomic.atomic_write_json,self.target,value);self.assertEqual(before,self.target.read_bytes());self.assertFalse(self.temps())
    def test_sigterm_during_large_write_cleans_own_scratch(self):
        path=self.location.runtime/'large.json';path.write_text('{"keep":true}');before=path.read_bytes();original=atomic.BufferedJSON.flush
        def shutdown(buffer):
            if buffer.parts:trace.shutdown_writes()
            return original(buffer)
        with patch.object(atomic.BufferedJSON,'flush',shutdown):self.assertRaises(OSError,atomic.atomic_write_json,path,{'payload':'x'*1200000})
        self.assertEqual(before,path.read_bytes());self.assertFalse(self.temps());self.assertFalse(list(path.parent.glob('.atomic-meta-*')))
    def test_sigterm_small_transaction_can_finish(self):trace.shutdown_writes();atomic.atomic_write_json(self.target,{'small':True});self.assertEqual(self.actual(),{'small':True})
    def test_worker_shutdown_gate_only_bound_worker(self):
        active=threading.Event();trace.bind_shutdown(active);trace.shutdown_writes(threading.Event());self.assertFalse(trace._shutdown.is_set());trace.shutdown_writes(active);self.assertTrue(trace._shutdown.is_set())

    def test_sidecar_target_fingerprint_and_bound(self):
        original=atomic.os.replace;seen=[]
        def replace(src,dst):
            path=Path(src).parent/trace.sidecar_name(Path(src).name);raw=path.read_bytes();seen.append(json.loads(raw));self.assertLess(len(raw),4096);return original(src,dst)
        with patch.object(atomic.os,'replace',side_effect=replace):atomic.atomic_write_json(self.target,{'commit':True})
        self.assertEqual(seen[0]['target_hash'],hashlib.sha256(self.target.name.encode()).hexdigest()[:24]);self.assertEqual(seen[0]['state'],'READY_TO_RENAME');self.assertFalse(list(self.target.parent.glob('.atomic-meta-*')))
    def test_lifecycle_normal_and_failure(self):
        with self.assertLogs(level='INFO') as logs:atomic.atomic_write_json(self.target,{'ok':1})
        text='\n'.join(logs.output)
        for state in ('CREATED','WRITING','FSYNCED','READY_TO_RENAME','RENAMED','CLEANED'):self.assertIn('state='+state,text)
        with patch.object(atomic.os,'replace',side_effect=OSError(errno.EIO,'replace failure')),self.assertLogs(level='INFO') as logs:self.assertRaises(OSError,atomic.atomic_write_json,self.target,{'ok':2})
        self.assertIn('state=ABORTED','\n'.join(logs.output));self.assertFalse(self.temps())
    def test_write_trace_fields_no_content(self):
        with self.assertLogs(level='INFO') as logs:atomic.atomic_write_json(self.target,{'secret_payload':'NEVER_LOG_VALUE'})
        text='\n'.join(logs.output)
        for field in ('dataset','target','writer','reason','logical_changed_bytes','physical_temp_bytes','final_size','started_at','finished_at','duration_ms','success','temp_removed','free_before','free_after'):self.assertIn(field+'=',text)
        self.assertNotIn('NEVER_LOG_VALUE',text)

    def open_pair(self,temp):
        a=os.open(temp,os.O_RDONLY);b=os.open(self.target,os.O_RDONLY);self.addCleanup(os.close,a);self.addCleanup(os.close,b);return a,b
    def partial(self,temp,limit=40):
        a,b=self.open_pair(temp);session=ResumableProof(self.location);calls=0
        def deadline(*args):
            nonlocal calls
            calls+=1
            if calls>limit:raise TimeoutError('bounded round')
        try:
            with patch.object(proof,'check_deadline',side_effect=deadline):self.assertRaises(TimeoutError,session.prove,a,b,self.target.name,'masked',float('inf'))
        finally:session.close()
        return a,b

    def test_resumable_checkpoint_real_record_offsets(self):
        old=self.history(500);new=copy.deepcopy(old);new['kayitlar'][-1]['sonuc_1g']={'getiri':2};self.target.write_text(json.dumps(new));temp=self.orphan(old);a,b=self.partial(temp)
        checkpoint=json.loads((self.location.runtime/'disk_forensic_checkpoint.json').read_text())['checkpoint'];final=next(iter(checkpoint['finals'].values()));self.assertGreater(final['parser']['offset'],0);self.assertGreater(final['count'],0);self.assertFalse(final['completed'])
        session=ResumableProof(self.location)
        try:self.assertEqual(session.prove(a,b,self.target.name,'masked',float('inf'))[0],'PROVEN_OLDER_COMPLETE_COPY')
        finally:session.close()

    def test_multiple_budget_rounds_eventually_finish(self):
        old=self.history(500);new=copy.deepcopy(old);new['kayitlar'][-1]['sonuc_1g']={'getiri':2};self.target.write_text(json.dumps(new));temp=self.orphan(old);a,b=self.open_pair(temp);rounds=0;answer=None;offsets=[]
        while answer is None and rounds<60:
            rounds+=1;session=ResumableProof(self.location);calls=0
            def deadline(*args):
                nonlocal calls
                calls+=1
                if calls>50:raise TimeoutError('bounded')
            try:
                with patch.object(proof,'check_deadline',side_effect=deadline):
                    try:answer=session.prove(a,b,self.target.name,'masked',float('inf'))
                    except TimeoutError:pass
                state=next(iter(session.data['finals'].values()),{});offsets.append((state.get('parser') or {}).get('offset',0))
            finally:session.close()
        self.assertIsNotNone(answer);self.assertEqual(answer[0],'PROVEN_OLDER_COMPLETE_COPY');self.assertGreater(rounds,2);self.assertEqual(offsets,sorted(offsets))

    def invalidate(self,kind):
        old=self.history(500);new=copy.deepcopy(old);new['kayitlar'][0]['sonuc_1g']={'getiri':2};self.target.write_text(json.dumps(new));temp=self.orphan(old);self.partial(temp)
        if kind=='inode':fresh=temp.with_name('replacement');fresh.write_bytes(temp.read_bytes());os.replace(fresh,temp)
        elif kind=='size':temp.write_bytes(temp.read_bytes()+b' ')
        else:os.utime(temp,ns=(temp.stat().st_atime_ns,temp.stat().st_mtime_ns+1000000))
        a,b=self.open_pair(temp);session=ResumableProof(self.location)
        try:session.prove(a,b,self.target.name,'masked',float('inf'));self.assertEqual(session.data['files']['masked']['temp_stamp'],list(proof.fingerprint(a)))
        finally:session.close()
    def test_checkpoint_invalidated_inode(self):self.invalidate('inode')
    def test_checkpoint_invalidated_size(self):self.invalidate('size')
    def test_checkpoint_invalidated_mtime(self):self.invalidate('mtime')
    def test_checkpoint_corrupt_checksum_restarts_not_deletes(self):
        temp=self.orphan(self.value);a,b=self.open_pair(temp);s=ResumableProof(self.location);s.prove(a,b,self.target.name,'masked',float('inf'));s.close();path=self.location.runtime/'disk_forensic_checkpoint.json';value=json.loads(path.read_text());value['checksum']='BAD';path.write_text(json.dumps(value));s=ResumableProof(self.location)
        try:self.assertEqual(s.data['files'],{});self.assertTrue(temp.exists())
        finally:s.close()
    def test_unknown_checkpoint_file_preserved(self):
        path=self.location.runtime/'disk_forensic_checkpoint.json';path.write_text('UNKNOWN UNIQUE CONTENT');self.assertRaises(ValueError,ResumableProof,self.location);self.assertEqual(path.read_text(),'UNKNOWN UNIQUE CONTENT')
    def test_checkpoint_symlink_preserved(self):
        other=self.location.users/'unique';other.write_text('KEEP');path=self.location.runtime/'disk_forensic_checkpoint.json';path.symlink_to(other);self.assertRaises(ValueError,ResumableProof,self.location);self.assertEqual(other.read_text(),'KEEP')
    def test_checkpoint_contains_hashes_not_prediction_content(self):
        self.value['kayitlar'][0]['private_label']='DONT_STORE_RAW';self.target.write_text(json.dumps(self.value));temp=self.orphan(self.value);a,b=self.open_pair(temp);s=ResumableProof(self.location);s.prove(a,b,self.target.name,'masked',float('inf'));s.close();raw=(self.location.runtime/'disk_forensic_checkpoint.json').read_bytes();self.assertLess(len(raw),MAX_BYTES);self.assertNotIn(b'DONT_STORE_RAW',raw)
    def test_missing_hash_index_revalidates_progress(self):
        old=self.history(500);new=copy.deepcopy(old);new['kayitlar'][-1]['sonuc_1g']={'getiri':2};self.target.write_text(json.dumps(new));temp=self.orphan(old);a,b=self.partial(temp);s=ResumableProof(self.location)
        for path in s.index_dir.glob('*.sqlite'):path.unlink()
        try:self.assertEqual(s.prove(a,b,self.target.name,'masked',float('inf'))[0],'PROVEN_OLDER_COMPLETE_COPY')
        finally:s.close()

    def test_truncated_prefix_proven_but_other_truncated_unknown(self):
        prefix=self.orphan(self.target.read_bytes()[:30]);other=self.orphan(b'{"kayitlar":[{"kayit_id":"UNIQUE',' .user-bad.tmp'.strip());self.assertEqual(self.scan()['removed'],1);self.assertFalse(prefix.exists());self.assertTrue(other.exists())
    def test_unique_recovery_not_removed(self):
        value=self.history();value['kayitlar'][0]['kayit_id']='ONLY_COPY';temp=self.orphan(value);before=temp.read_bytes();self.scan();self.assertEqual(temp.read_bytes(),before)
    def test_startup_orphan_then_repeated_cleanup_idempotent(self):
        temp=self.orphan(self.value);self.assertEqual(self.scan()['removed'],1);self.assertEqual(self.scan()['removed'],0);self.assertFalse(temp.exists());self.assertEqual(self.actual(),self.value)
    def test_active_writer_lease_preserved(self):
        import fcntl
        temp=self.orphan(self.value);fd=os.open(temp,os.O_RDWR)
        try:fcntl.flock(fd,fcntl.LOCK_EX);self.assertEqual(self.scan()['removed'],0);self.assertTrue(temp.exists())
        finally:os.close(fd)
    def test_cleanup_requires_worker_lock(self):
        temp=self.orphan(self.value);result=inspect_atomic_temps(self.location,cleanup=True,resumable=True);self.assertEqual(result['removed'],0);self.assertTrue(temp.exists())
    def test_manifest_and_checkpoint_bounded(self):
        self.orphan(self.value);self.scan()
        for name,limit in [('disk_cleanup_manifest.json',256*1024),('disk_forensic_checkpoint.json',MAX_BYTES)]:self.assertLess((self.location.runtime/name).stat().st_size,limit)

    def test_data_update_workflow_no_commit_push_or_write_permission(self):
        workflow=(Path(__file__).parents[1]/'.github/workflows/main.yml').read_text();self.assertNotIn('git push',workflow);self.assertNotIn('git commit',workflow);self.assertNotIn('contents: write',workflow);self.assertIn('actions/upload-artifact',workflow);self.assertIn('retention-days: 3',workflow)
    def test_growth_logging_fields(self):
        monitor=trace.GrowthMonitor();monitor.sample(self.location);temp=self.orphan(self.value)
        with self.assertLogs(level='INFO') as logs:value=monitor.sample(self.location)
        self.assertEqual(value['new_temp_count'],1);self.assertEqual(value['new_temp_bytes'],temp.stat().st_size)
        for key in ('free_now','free_5m_ago','delta_free','temp_count','temp_bytes','new_temp_count','new_temp_bytes','removed_temp_count','removed_temp_bytes','largest_writer'):self.assertIn(key,'\n'.join(logs.output))
    def test_leak_detector_target_writer_and_age(self):
        monitor=trace.GrowthMonitor();monitor.sample(self.location);temp=self.orphan(self.value);writer=trace.WriteTrace(self.target);fd=os.open(temp,os.O_RDWR);writer.temp=str(temp)
        try:writer.create_metadata(fd);writer.transition('WRITING')
        finally:os.close(fd);os.close(writer.meta_fd);writer.meta_fd=None
        with self.assertLogs(level='WARNING') as logs:monitor.sample(self.location)
        text='\n'.join(logs.output);self.assertIn('STORAGE_LEAK_ALERT',text);self.assertIn(writer.target,text);self.assertIn('transaction_count=',text)
    def test_fresh_inflight_not_false_leak(self):
        monitor=trace.GrowthMonitor();monitor.sample(self.location);temp=self.orphan(self.value);os.utime(temp,None)
        with self.assertLogs(level='INFO') as logs:monitor.sample(self.location)
        self.assertNotIn('STORAGE_LEAK_ALERT','\n'.join(logs.output))
    def test_pending_and_shutdown_error_classifications(self):
        from gorev_hatalari import describe
        self.assertEqual(describe(trace.StoragePendingError())['code'],'STORAGE_PENDING');self.assertEqual(describe(OSError(errno.ECANCELED,'shutdown'))['code'],'STORAGE_SHUTDOWN');self.assertEqual(describe(JournalError('WAL_CHECKSUM_OR_SEQUENCE'))['code'],'WAL_CORRUPT')

    def test_resumable_fairness_includes_smallest_round(self):
        self.orphan(self.value,'.user-small.tmp');larger=copy.deepcopy(self.value);larger['extra']='x'*1000;self.orphan(larger,'.user-large.tmp')
        session=ResumableProof(self.location);session.data['round']=3;session.dirty=True;session.close()
        result=self.scan();self.assertEqual(result['findings'][0]['masked_file'],hashlib.sha256(b'.user-small.tmp').hexdigest()[:16])
    def test_proof_index_capacity_stops_without_deleting_payload(self):
        old=self.history(100);new=copy.deepcopy(old);new['kayitlar'][0]['sonuc_1g']={'getiri':2};self.target.write_text(json.dumps(new));temp=self.orphan(old);a,b=self.open_pair(temp);session=ResumableProof(self.location)
        try:
            with patch('disk_resumable.MAX_INDEX_BYTES',1):answer=session.prove(a,b,self.target.name,'masked',float('inf'))
            self.assertEqual(answer[0],'UNKNOWN');self.assertEqual(answer[1],'PROOF_INDEX_CAPACITY');self.assertTrue(temp.exists())
        finally:session.close()
    def test_checkpoint_size_bound_rejects_growth(self):
        session=ResumableProof(self.location);session.data['files']={'x':{'completed':False,'touched':0,'metadata':'X'*MAX_BYTES}};session.dirty=True
        self.assertRaises(ValueError,session.save);session.dirty=False;session.close();self.assertFalse((self.location.runtime/'disk_forensic_checkpoint.json').exists())
    def test_stale_sidecar_is_never_removed_without_payload_proof(self):
        temp=self.orphan(b'UNIQUE UNKNOWN');meta=self.location.runtime/trace.sidecar_name(temp.name);meta.write_text('{"version":4}');self.scan();self.assertTrue(temp.exists());self.assertTrue(meta.exists())
    def test_readonly_inspection_writes_no_checkpoint(self):
        self.orphan(self.value);inspect_atomic_temps(self.location,cleanup=False,resumable=True);self.assertFalse((self.location.runtime/'disk_forensic_checkpoint.json').exists())
    def test_critical_merge_waits_and_keeps_canonical_stable_for_proof(self):
        self.journal.append([self.operation()]);before=self.target.read_bytes()
        with patch.object(trace,'critical_storage',return_value=True),patch.object(atomic.tempfile,'mkstemp',side_effect=AssertionError('critical merge temp forbidden')):self.assertRaises(trace.StoragePendingError,self.journal.flush)
        self.assertEqual(before,self.target.read_bytes());self.assertTrue(self.journal.path.exists());self.assertEqual(self.journal.flush(),1)
    def test_wal_same_field_multiple_updates_replay(self):
        old=self.value['kayitlar'][0];one=dict(old,sonuc_1g={'getiri':2});two=dict(old,sonuc_1g={'getiri':3})
        self.journal.append([{'id':identity(old),'fields':field_patch(old,one)}]);self.journal.append([{'id':identity(old),'fields':field_patch(one,two)}]);wal=self.journal.path.read_bytes();self.journal.flush();self.journal.path.write_bytes(wal);self.journal.flush();self.assertEqual(self.actual()['kayitlar'][0]['sonuc_1g']['getiri'],3)
    def test_wal_incompatible_stale_updates_keep_both_intents(self):
        self.journal.append([self.operation(0,2)]);self.journal.append([self.operation(0,3)]);before=self.target.read_bytes();self.assertRaises(JournalError,self.journal.flush);self.assertEqual(before,self.target.read_bytes());self.assertEqual(len(list(self.journal.transactions())),2)


if __name__=='__main__':unittest.main()
