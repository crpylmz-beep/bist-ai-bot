"""V3 proof/continuation tests use isolated volumes, never production data."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from ana_motor import worker_lock
from atomik_depolama import atomic_write_json
from disk_bakimi import DiskMaintenance
from disk_forensik import inspect_atomic_temps
from disk_koruma import disk_health
from veri_yollari import DataPaths

class DiskV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.tmp.name});self.location.ensure()
        self.enterContext(patch('atomik_temp_temizligi.foreign_open',return_value=False))
    def fixture(self,old,new,filename='ai_ogrenme_gecmisi.json',name='.user-legacy.tmp'):
        final=self.location.runtime/filename;final.write_text(json.dumps(new,ensure_ascii=False))
        temp=self.location.runtime/name;temp.write_text(json.dumps(old,ensure_ascii=False));os.utime(temp,(0,0))
        return temp,final
    def scan(self,**kwargs):
        with worker_lock(self.location.runtime):return inspect_atomic_temps(self.location,cleanup=True,**kwargs)
    def ai(self,row,at='2026-10-08 11:00:00'):
        return dict(kayitlar=[dict(kayit_id='ONE',model='OTHER',score=70,**row)],guncelleme=at,toplam_kayit=1)
    def prediction(self,row,at='2026-10-08T11:00:00+03:00'):
        return dict(surum=1,tahminler=[dict(id='PRED_ONE',fiyat=100,**row)],ogrenme_gecmisi=[],son_guncelleme=at)
    def test_file_metadata_complete_masked(self):
        temp,_=self.fixture(self.ai({}),self.ai({},'2026-10-08 12:00:00'));result=self.scan();finding=result['findings'][0]
        required={'masked_file','age_seconds','probable_target_final','schema','classification','reason_code','comparison_method','unique_record_count','changed_record_count','missing_record_count','final_extra_record_count','eligible_for_cleanup'}
        self.assertTrue(required<=finding.keys());self.assertEqual(finding['masked_file'],hashlib.sha256(temp.name.encode()).hexdigest()[:16]);self.assertNotIn('ONE',str(finding))
    def test_unique_counters(self):
        old=self.ai({});old['kayitlar'][0]['kayit_id']='RECOVERY';self.fixture(old,self.ai({}));f=self.scan()['findings'][0]
        self.assertEqual(f['unique_record_count'],1);self.assertEqual(f['missing_record_count'],1);self.assertEqual(f['final_extra_record_count'],1);self.assertEqual(f['reason_code'],'UNIQUE_RECORD')
    def test_changed_frozen_counter(self):
        old=self.ai({});new=copy.deepcopy(old);new['kayitlar'][0]['score']=80;temp,_=self.fixture(old,new);f=self.scan()['findings'][0]
        self.assertEqual(f['changed_record_count'],1);self.assertEqual(f['reason_code'],'CHANGED_FROZEN_FIELD');self.assertTrue(temp.exists())
    def test_changed_completed_counter(self):
        temp,_=self.fixture(self.ai({'sonuc_1g':{'getiri':2}}),self.ai({'sonuc_1g':{'getiri':3}}));f=self.scan()['findings'][0]
        self.assertEqual(f['reason_code'],'CHANGED_RESULT');self.assertTrue(temp.exists())
    def test_completed_result_added_fields_only(self):
        temp,_=self.fixture(self.ai({'sonuc_1g':{'getiri':2}}),self.ai({'sonuc_1g':{'getiri':2,'MFE':4}}));self.scan();self.assertFalse(temp.exists())
    def test_result_deleted_field_preserved(self):
        temp,_=self.fixture(self.ai({'sonuc_1g':{'getiri':2,'MFE':4}}),self.ai({'sonuc_1g':{'getiri':2}}));self.scan();self.assertTrue(temp.exists())
    def test_prediction_null_completed(self):
        temp,_=self.fixture(self.prediction({'sonuc_1g':None}),self.prediction({'sonuc_1g':{'getiri_yuzde':2}},'2026-10-08T12:00:00+03:00'),'tahmin_gecmisi.json');self.scan();self.assertFalse(temp.exists())
    def test_prediction_completed_changed_kept(self):
        temp,_=self.fixture(self.prediction({'sonuc_1g':{'getiri':2}}),self.prediction({'sonuc_1g':{'getiri':3}}),'tahmin_gecmisi.json');self.scan();self.assertTrue(temp.exists())
    def test_prediction_empty_result_not_null(self):
        # An empty object is not automatically a documented empty placeholder;
        # containment permits added values only, not loss of existing values.
        temp,_=self.fixture(self.prediction({'sonuc_1g':{'status':'PENDING'}}),self.prediction({'sonuc_1g':{'status':'COMPLETE'}}),'tahmin_gecmisi.json');self.scan();self.assertTrue(temp.exists())
    def test_prediction_enrichment(self):
        temp,_=self.fixture(self.prediction({}),self.prediction({'confidence':60}),'tahmin_gecmisi.json');self.scan();self.assertFalse(temp.exists())
    def test_prediction_naive_clock(self):
        temp,_=self.fixture(self.prediction({},'2026-10-08 11:00:00'),self.prediction({},'2026-10-08T12:00:00+03:00'),'tahmin_gecmisi.json');self.scan();self.assertFalse(temp.exists())
    def test_prediction_metadata_unique(self):
        old=self.prediction({});old['ogrenme_gecmisi']=[{'unique':'KEEP'}];temp,_=self.fixture(old,self.prediction({}),'tahmin_gecmisi.json');self.scan();self.assertTrue(temp.exists())
    def test_prediction_duplicate_ids(self):
        old=self.prediction({});old['tahminler']*=2;temp,_=self.fixture(old,self.prediction({}),'tahmin_gecmisi.json');f=self.scan()['findings'][0];self.assertTrue(temp.exists());self.assertEqual(f['reason_code'],'DUPLICATE_RECORD_ID')
    def test_missing_target(self):
        temp,final=self.fixture(self.ai({}),self.ai({}));final.unlink();f=self.scan()['findings'][0];self.assertTrue(temp.exists());self.assertFalse(f['eligible_for_cleanup'])
    def test_large_prediction_streaming(self):
        old={'surum':1,'tahminler':[{'id':str(i),'fiyat':100,'padding':'a'*1000,'sonuc_1g':None} for i in range(9000)],'ogrenme_gecmisi':[]}
        new=copy.deepcopy(old);new['tahminler'][-1]['sonuc_1g']={'getiri':2}
        temp,_=self.fixture(old,new,'tahmin_gecmisi.json');self.assertGreater(temp.stat().st_size,8*1024**2)
        with patch('disk_forensik.small_json',side_effect=AssertionError('Full JSON read forbidden')):self.scan()
        self.assertFalse(temp.exists())
    def test_manifest_deletion_metadata(self):
        self.fixture(self.ai({}),self.ai({}));self.scan();entry=json.loads((self.location.runtime/'disk_cleanup_manifest.json').read_text())['entries'][0]
        self.assertTrue({'timestamp','masked_file','size','classification','reason','free_before','free_after'}<=entry.keys());self.assertIn('+03:00',entry['timestamp'])
    def test_watermark_normal(self):self.watermark(74,'NORMAL')
    def test_watermark_watch(self):self.watermark(75,'WATCH')
    def test_watermark_warning(self):self.watermark(80,'WARNING')
    def test_watermark_critical(self):self.watermark(90,'CRITICAL')
    def watermark(self,percent,status):
        with patch('disk_koruma.shutil.disk_usage',return_value=type('U',(),dict(total=1000,used=percent*10,free=1000-percent*10))()):
            self.assertEqual(disk_health(self.location)['status'],status)
    def test_summary_bytes_and_targets(self):
        temp,_=self.fixture(self.ai({}),self.ai({}));size=temp.stat().st_size;r=self.scan();self.assertEqual(r['classification_bytes']['PROVEN_REDUNDANT'],size);self.assertIn('target_2gib_reached',r)
    def test_budget_retry(self):
        temp,_=self.fixture(self.ai({}),self.ai({}));self.scan(budget_seconds=0);self.assertTrue(temp.exists());self.scan();self.assertFalse(temp.exists())
    def test_maintenance_worker_lock_required(self):
        maintenance=DiskMaintenance(self.location,threading.Event());self.assertRaises(RuntimeError,maintenance.start)
    def test_continuation_avoids_starvation(self):
        calls=[]
        def inspector(*args,**kwargs):
            calls.append(set(kwargs['skip_identifiers']))
            files=['a','b'] if not calls[-1] else ['b']
            return {'scanned':len(files),'findings':[{'masked_file':x,'reason':'BUDGET_EXHAUSTED'} for x in files]}
        m=DiskMaintenance(self.location,threading.Event(),inspector=inspector)
        with worker_lock(self.location.runtime):m.round();m.round()
        self.assertEqual(calls,[set(),{'a'}])
    def test_background_actual_cleanup_and_stop(self):
        temp,_=self.fixture(self.ai({}),self.ai({}));stop=threading.Event()
        with worker_lock(self.location.runtime):
            m=DiskMaintenance(self.location,stop,interval=.02).start()
            for _ in range(100):
                if not temp.exists():break
                time.sleep(.01)
            m.close();self.assertFalse(m.thread.is_alive())
        self.assertFalse(temp.exists())
    def test_background_stop_cancels_proof(self):
        from atomik_temp_temizligi import inspection_stop,check_deadline
        stop=threading.Event();stop.set();token=inspection_stop.set(stop)
        try:self.assertRaises(TimeoutError,check_deadline,float('inf'))
        finally:inspection_stop.reset(token)
    def test_repeated_cleanup_idempotent(self):
        self.fixture(self.ai({}),self.ai({}));self.assertEqual(self.scan()['removed'],1);self.assertEqual(self.scan()['removed'],0)
    def test_large_dirty_check_coalesces_identical_commits(self):
        target=self.location.runtime/'big.json';value={'payload':'x'*1024**2}
        atomic_write_json(target,value);stamp=target.stat().st_ino
        with patch('atomik_depolama.tempfile.mkstemp',side_effect=AssertionError('Unchanged temp forbidden')):
            atomic_write_json(target,value);atomic_write_json(target,value)
        self.assertEqual(target.stat().st_ino,stamp);self.assertFalse(list(self.location.runtime.glob('.user-*')))
    def interrupted_writer(self,kill):
        final=self.location.runtime/'ai_ogrenme_gecmisi.json';value=self.ai({});atomic_write_json(final,value)
        marker=self.location.runtime/'ready'
        script="""import os,sys,signal,time
from pathlib import Path
from atomik_depolama import atomic_write_json
signal.signal(signal.SIGTERM,lambda *args:sys.exit(0))
def wait(fd):
 Path(sys.argv[2]).touch()
 while True:time.sleep(.02)
import atomik_depolama
atomik_depolama.os.fsync=wait
atomic_write_json(Path(sys.argv[1]),%r)
"""%value
        child=subprocess.Popen([sys.executable,'-c',script,str(final),str(marker)])
        try:
            for _ in range(250):
                if marker.exists():break
                time.sleep(.01)
            self.assertTrue(marker.exists());os.kill(child.pid,kill);child.wait(timeout=5)
        finally:
            if child.poll() is None:child.kill();child.wait()
        return final
    def test_sigterm_finally_removes_temp(self):
        final=self.interrupted_writer(signal.SIGTERM);self.assertTrue(final.exists());self.assertFalse(list(self.location.runtime.glob('.user-*')))
    def test_sigkill_orphan_recovery(self):
        final=self.interrupted_writer(signal.SIGKILL);temps=list(self.location.runtime.glob('.user-*'));self.assertEqual(len(temps),1);os.utime(temps[0],(0,0));self.assertEqual(self.scan()['removed'],1);self.assertTrue(final.exists())

    def test_intraday_legacy_empty_outcomes(self):
        row={'id':'SIGNAL','sembol':'AAA','sinyal_zamani':'2026-10-08T11:00:00+03:00','giris_fiyati':100,'sonuclar':{}}
        old={'kayitlar':[row],'listeler':[]};new=copy.deepcopy(old);new['kayitlar'][0]['sonuclar']['60']={'getiri':2}
        temp,_=self.fixture(old,new,'gun_ici_sonuclar.json');self.scan();self.assertFalse(temp.exists())
    def test_intraday_legacy_changed_completed_kept(self):
        row={'id':'SIGNAL','sembol':'AAA','sinyal_zamani':'2026-10-08T11:00:00+03:00','giris_fiyati':100,'sonuclar':{'60':{'getiri':2}}}
        old={'kayitlar':[row],'listeler':[]};new=copy.deepcopy(old);new['kayitlar'][0]['sonuclar']['60']['getiri']=3
        temp,_=self.fixture(old,new,'gun_ici_sonuclar.json');self.scan();self.assertTrue(temp.exists())
    def test_intraday_lifecycle_not_ignored(self):
        row={'id':'SIGNAL','sembol':'AAA','sinyal_zamani':'2026-10-08T11:00:00+03:00','giris_fiyati':100,'sonuclar':{},'durum':'YENI_AL'}
        old={'kayitlar':[row],'listeler':[]};new=copy.deepcopy(old);new['kayitlar'][0]['durum']='STOP'
        temp,_=self.fixture(old,new,'gun_ici_sonuclar.json');self.scan();self.assertTrue(temp.exists())
    def test_indicator_legacy_changed_hash_kept(self):
        old={'version':'INDICATOR_PERFORMANCE_V1','sources':{},'report_hash':'old','updated_at':'2026-10-08T11:00:00+03:00'}
        new=dict(old,report_hash='new',updated_at='2026-10-08T12:00:00+03:00')
        temp,_=self.fixture(old,new,'indicator_performance_state.json');self.scan();self.assertTrue(temp.exists())
    def test_indicator_legacy_same_content_new_clock(self):
        old={'version':'INDICATOR_PERFORMANCE_V1','sources':{},'report_hash':'same','updated_at':'2026-10-08T11:00:00+03:00'}
        new=dict(old,updated_at='2026-10-08T12:00:00+03:00')
        temp,_=self.fixture(old,new,'indicator_performance_state.json');self.scan();self.assertFalse(temp.exists())

    def test_background_final_writer_not_blocked_and_proof_invalidated(self):
        from disk_forensik import classify_locked
        import disk_forensik
        temp,final=self.fixture(self.ai({}),self.ai({}))
        changed=self.ai({'score_after_write':90})
        def concurrent(*args,**kwargs):
            answer=classify_locked(*args,**kwargs)
            atomic_write_json(final,changed)  # must not deadlock behind background proof locks
            return answer
        with patch.object(disk_forensik,'classify_locked',side_effect=concurrent):
            result=self.scan(release_locks_during_proof=True)
        self.assertTrue(temp.exists());self.assertEqual(result['removed'],0)
        self.assertEqual(result['findings'][0]['reason'],'FILE_CHANGED_DURING_PROOF')
        self.assertEqual(json.loads(final.read_text()),changed)
    def test_background_stable_final_cleanup(self):
        temp,final=self.fixture(self.ai({}),self.ai({}));result=self.scan(release_locks_during_proof=True)
        self.assertFalse(temp.exists());self.assertTrue(final.exists());self.assertEqual(result['removed'],1)
