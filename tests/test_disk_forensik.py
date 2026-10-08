import copy
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from ana_motor import worker_lock
from atomik_temp_temizligi import cleanup_atomic_temps,MIN_AGE
from atomik_depolama import atomic_write_json
from disk_forensik import inspect_atomic_temps,CLASSES,PROVEN,TARGET_FREE
from veri_yollari import DataPaths

class ForensicTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.tmp.name});self.location.ensure()
        self.final=self.location.runtime/'ai_ogrenme_gecmisi.json'
        self.enterContext(patch('atomik_temp_temizligi.foreign_open',return_value=False))
    def row(self,identity='ONE'):
        return {'kayit_id':identity,'model':'GUN_ICI','sembol':'AAA','zaman':'2026-10-08 10:05:00','egitim_durumu':'EGITIM','karar':'AL','fiyat':100,'hedef':105,'stop':97,'teknik_puan':70,'sonuc':'BEKLIYOR','sonuc_fiyat':None,'sonuc_zaman':None,'getiri_yuzde':None,'hedef_vurdu':False,'stop_vurdu':False}
    def history(self,rows=None,at='2026-10-08 12:00:00'):
        rows=[self.row()] if rows is None else rows
        return {'guncelleme':at,'toplam_kayit':len(rows),'kayitlar':rows}
    def seed(self,value):self.final.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def temp(self,value,name='.user-old.tmp',recent=False):
        p=self.location.runtime/name;p.write_bytes(value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,indent=2).encode())
        if not recent:os.utime(p,(0,0))
        return p
    def scan(self,**kwargs):return inspect_atomic_temps(self.location,**kwargs)
    def clean(self,**kwargs):
        with worker_lock(self.location.runtime):return cleanup_atomic_temps(self.location,**kwargs)
    def finding(self,result):return result['findings'][0]
    def test_six_classes(self):self.assertEqual(len(CLASSES),6);self.assertEqual(len(PROVEN),3)
    def test_exact_duplicate_readonly(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes());before=set(self.location.runtime.iterdir());r=self.scan()
        self.assertEqual(self.finding(r)['classification'],'PROVEN_REDUNDANT');self.assertEqual(set(self.location.runtime.iterdir()),before);self.assertTrue(p.exists());self.assertEqual(r['removed'],0)
    def test_hash_identical_cleanup(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes());r=self.clean();self.assertEqual(r['removed'],1);self.assertFalse(p.exists());self.assertEqual(r['classifications']['PROVEN_REDUNDANT'],1)
    def test_older_naive_complete_history(self):
        old=self.history(at='2026-10-08 10:00:00');self.seed(self.history(at='2026-10-08T12:00:00+03:00'));p=self.temp(old);r=self.clean();self.assertFalse(p.exists());self.assertEqual(self.finding(r)['classification'],'PROVEN_OLDER_COMPLETE_COPY')
    def test_strict_subset(self):
        self.seed(self.history([self.row(),self.row('TWO')]));p=self.temp(self.history());r=self.clean();self.assertEqual(self.finding(r)['classification'],'PROVEN_SUBSET_OF_FINAL');self.assertFalse(p.exists())
    def completed(self):
        row=self.row();row.update(egitim_durumu='TAMAMLANDI',sonuc='BASARILI',sonuc_fiyat=105,sonuc_zaman='2026-10-08 12:00:00',getiri_yuzde=5,hedef_vurdu=True)
        return row
    def test_pending_to_completed(self):
        self.seed(self.history([self.completed()]));p=self.temp(self.history());r=self.clean();self.assertFalse(p.exists());self.assertEqual(self.finding(r)['classification'],'PROVEN_OLDER_COMPLETE_COPY')
    def test_same_completed_results(self):
        old=self.history([self.completed()]);self.seed(self.history([self.completed(),self.row('TWO')]));p=self.temp(old);self.clean();self.assertFalse(p.exists())
    def test_different_completed_result_unique(self):
        self.seed(self.history([self.completed()]));row=self.completed();row['getiri_yuzde']=7;p=self.temp(self.history([row]));r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unique'],1)
    def test_unique_record(self):
        self.seed(self.history());p=self.temp(self.history([self.row('TWO')]));r=self.clean();self.assertTrue(p.exists());self.assertEqual(self.finding(r)['classification'],'UNIQUE_RECOVERY_CANDIDATE')
    def test_one_missing_record_preserved(self):
        self.seed(self.history());p=self.temp(self.history([self.row(),self.row('MISSING')]));r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['eligible'],0)
    def test_final_missing(self):p=self.temp(self.history());r=self.clean();self.assertTrue(p.exists());self.assertEqual(self.finding(r)['classification'],'UNKNOWN')
    def test_enrichment_additions_contained(self):
        old=self.history();new=copy.deepcopy(old)
        from performans_motoru import PerformansMotoru
        PerformansMotoru.enrich(new['kayitlar'][0]);self.seed(new);p=self.temp(old);r=self.clean();self.assertFalse(p.exists());self.assertEqual(r['eligible'],1)
    def test_enriched_frozen_score_change_unique(self):
        new=self.history();new['kayitlar'][0]['teknik_puan']=71;new['kayitlar'][0]['model_version']='V1';self.seed(new);p=self.temp(self.history());r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unique'],1)
    def test_null_frozen_value_not_overwritten(self):
        old=self.history();old['kayitlar'][0]['confidence']=None;new=copy.deepcopy(old);new['kayitlar'][0]['confidence']=50;self.seed(new);p=self.temp(old);self.clean();self.assertTrue(p.exists())
    def test_sat_pending_levels_preserved_by_result(self):
        old=self.history();old['kayitlar'][0].update(karar='SAT',sat_hedef=95,sat_stop=103)
        new=self.history([self.completed()]);new['kayitlar'][0].update(karar='SAT',sat_hedef=95,sat_stop=103)
        self.seed(new);p=self.temp(old);r=self.clean();self.assertFalse(p.exists());self.assertEqual(r['eligible'],1)
    def test_changed_sat_level_unique(self):
        old=self.history();old['kayitlar'][0].update(karar='SAT',sat_hedef=95,sat_stop=103)
        new=copy.deepcopy(old);new['kayitlar'][0]['sat_hedef']=94;self.seed(new);p=self.temp(old);r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unique'],1)
    def test_nonempty_pending_unknown(self):
        old=self.history();old['kayitlar'][0]['sonuc_fiyat']=101;self.seed(self.history());p=self.temp(old);r=self.clean();self.assertTrue(p.exists());self.assertEqual(self.finding(r)['classification'],'UNKNOWN')
    def test_invalid_json_unknown(self):
        self.seed(self.history());p=self.temp(b'{bad data}');r=self.clean();self.assertTrue(p.exists());self.assertEqual(self.finding(r)['classification'],'UNKNOWN')
    def test_truncated_unique_unknown(self):
        self.seed(self.history());p=self.temp(json.dumps(self.history([self.row('RECOVERY')])).encode()[:-2]);r=self.clean();self.assertTrue(p.exists());self.assertEqual(self.finding(r)['classification'],'UNKNOWN')
    def test_truncated_exact_prefix_safe(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes()[:-20]);r=self.clean();self.assertFalse(p.exists());self.assertEqual(r['classifications']['PROVEN_REDUNDANT'],1)
    def test_suffix_safe(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes()[-30:]);r=self.clean();self.assertFalse(p.exists());self.assertEqual(r['removed'],1)
    def test_recent(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes(),recent=True);r=self.clean();self.assertTrue(p.exists());self.assertEqual(self.finding(r)['classification'],'ACTIVE_OR_RECENT')
    def test_active_lease(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes())
        with p.open('rb') as f:
            fcntl.flock(f,fcntl.LOCK_EX);r=self.clean()
        self.assertTrue(p.exists());self.assertEqual(r['skipped_active'],1)
    def test_process_audit_uncertain_logged(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes())
        with patch('atomik_temp_temizligi.foreign_open',return_value=None):r=self.clean()
        self.assertTrue(p.exists());self.assertIn('PROCESS_AUDIT_UNCERTAIN',r['reasons'])
    def test_unknown_name(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes(),name='.user-user.txt');r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unknown'],1)
    def test_symlink(self):
        self.seed(self.history());p=self.location.runtime/'.user-link.tmp';p.symlink_to(self.final);r=self.clean();self.assertTrue(p.is_symlink());self.assertEqual(r['eligible'],0)
    def test_path_boundary(self):
        other=self.location.users/'.user-old.tmp';other.write_text('KEEP');self.seed(self.history());self.clean();self.assertEqual(other.read_text(),'KEEP')
    def test_hardlink_preserved(self):
        self.seed(self.history());p=self.location.runtime/'.user-linked.tmp';os.link(self.final,p);os.utime(p,(0,0));self.clean();self.assertTrue(p.exists())
    def test_cleanup_requires_worker_lock(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes());r=cleanup_atomic_temps(self.location);self.assertTrue(p.exists());self.assertIn('WORKER_LOCK_REQUIRED',r['reasons'])
    def test_busy_final_lock(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes())
        with Path(str(self.final)+'.lock').open('w') as f:
            fcntl.flock(f,fcntl.LOCK_EX);r=self.clean()
        self.assertTrue(p.exists());self.assertEqual(r['removed'],0)
    def test_largest_first(self):
        self.seed(self.history());small=self.temp(self.final.read_bytes(),name='.user-a.tmp');large=self.temp(b' '+self.final.read_bytes(),name='.user-z.tmp');r=self.clean()
        self.assertGreater(r['findings'][0]['size'],r['findings'][1]['size']);self.assertFalse(small.exists());self.assertFalse(large.exists())
    def test_manifest_accounting(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes());size=p.stat().st_size;r=self.clean();m=json.loads((self.location.runtime/'disk_cleanup_manifest.json').read_text())
        self.assertEqual(m['removed_bytes'],size);self.assertEqual(m['removed_count'],r['removed']);self.assertEqual(m['entries'][0]['size'],size);self.assertEqual(len(m['entries'][0]['hash_prefix']),16)
    def test_manifest_small_and_no_payload(self):
        self.seed(self.history());self.temp(self.final.read_bytes());self.clean();p=self.location.runtime/'disk_cleanup_manifest.json';self.assertLess(p.stat().st_size,4096);self.assertNotIn('teknik_puan',p.read_text())
    def test_no_payload_copy_readonly(self):
        self.seed(self.history([self.row(),self.row('TWO')]));self.temp(self.history())
        with patch('shutil.copyfile',side_effect=AssertionError('copy')),patch('shutil.copyfileobj',side_effect=AssertionError('copy')),patch('atomik_depolama.atomic_write_json',side_effect=AssertionError('write')):r=self.scan()
        self.assertEqual(r['eligible'],1)
    def test_low_free_scan(self):
        self.seed(self.history([self.row(),self.row('TWO')]));self.temp(self.history())
        with patch('disk_forensik.shutil.disk_usage',return_value=shutil._ntuple_diskusage(5*1024**3,5*1024**3-1,1)):r=self.scan()
        self.assertEqual(r['eligible'],1);self.assertEqual(r['before_free'],1)
    def test_target_does_not_loosen_proof(self):
        self.seed(self.history());p=self.temp(self.history([self.row('UNIQUE')]))
        with patch('disk_forensik.shutil.disk_usage',return_value=shutil._ntuple_diskusage(5*1024**3,5*1024**3-100000,100000)):r=self.clean()
        self.assertTrue(p.exists());self.assertEqual(r['target_free'],TARGET_FREE);self.assertEqual(r['removed'],0)
    def test_repeat_idempotent(self):
        self.seed(self.history());self.temp(self.final.read_bytes());self.assertEqual(self.clean()['removed'],1);self.assertEqual(self.clean()['removed'],0)
    def test_guard_after_cleanup(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes());self.clean();atomic_write_json(self.final,{'updated':True});self.assertEqual(json.loads(self.final.read_text()),{'updated':True});self.assertFalse(p.exists())
    def test_final_and_unique_bytes_unchanged(self):
        self.seed(self.history());before=self.final.read_bytes();p=self.temp(self.history([self.row('RECOVERY')]));original=p.read_bytes();self.clean();self.assertEqual(before,self.final.read_bytes());self.assertEqual(original,p.read_bytes())
    def test_future_timestamp_unknown(self):
        self.seed(self.history());p=self.temp(self.history(at='2026-10-09 12:00:00'));r=self.clean();self.assertTrue(p.exists());self.assertIn('FUTURE_HISTORY_TIMESTAMP',r['reasons'])
    def test_duplicate_id_unknown(self):
        self.seed(self.history());p=self.temp(self.history([self.row(),self.row()]));r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unknown'],1)
    def test_changed_file_preserved(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes())
        with patch('disk_forensik.same_entry',return_value=False):r=self.clean()
        self.assertTrue(p.exists());self.assertEqual(r['removed'],0)
    def test_budget_exhausted_reason(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes());r=self.clean(budget_seconds=0);self.assertTrue(p.exists());self.assertIn('BUDGET_EXHAUSTED',r['reasons'])
    def test_v2_destination_routing(self):
        target=self.location.runtime/'gun_ici_mumlar.json';target.write_text(json.dumps({'AAA':[{'timestamp':'t','close':100}],'BBB':[]}));token=hashlib.sha256(target.name.encode()).hexdigest()[:24]
        p=self.temp({'AAA':[{'timestamp':'t','close':100}]},name='.user-v2-'+token+'-old.tmp');r=self.clean();self.assertFalse(p.exists());self.assertEqual(self.finding(r)['dataset'],target.name)
    def test_v2_missing_destination_unknown(self):
        self.seed(self.history());token=hashlib.sha256(b'not_present.json').hexdigest()[:24];p=self.temp(self.final.read_bytes(),name='.user-v2-'+token+'-old.tmp');r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unknown'],1)
    def test_legacy_unrelated_root_not_deleted(self):
        self.final.write_text('{}');(self.location.runtime/'performans_durum.json').write_text('{"updated_at":"2026-10-09T00:00:00+03:00","other":5}');p=self.temp({'updated_at':'2026-10-08T00:00:00+03:00'});r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['eligible'],0)
    def test_unicode_and_crlf_offset_enrichment(self):
        old=self.history();old['kayitlar'][0]['aciklama']='İstanbul güçlü';new=copy.deepcopy(old);new['kayitlar'][0]['model_version']='YENİ'
        self.final.write_bytes(json.dumps(new,ensure_ascii=False,indent=2).replace('\n','\r\n').encode());p=self.temp(old);self.clean();self.assertFalse(p.exists())
    def test_large_sparse_production_like(self):
        # 280 MiB opaque byte fixture tests bounded hashing/accounting. Semantic
        # JSON proofs are tested separately against actual repository schemas.
        self.seed(self.history());large=self.location.runtime/'gun_ici_mumlar.json'
        with large.open('wb') as f:f.truncate(280*1024**2)
        duplicate=self.location.runtime/'.user-large.tmp'
        with duplicate.open('wb') as f:f.truncate(large.stat().st_size)
        os.utime(duplicate,(0,0));unique=self.temp(self.history([self.row('RECOVERY')]),name='.user-unique.tmp');recent=self.temp(self.final.read_bytes(),name='.user-recent.tmp',recent=True);before=self.final.read_bytes();r=self.clean()
        self.assertFalse(duplicate.exists());self.assertTrue(unique.exists());self.assertTrue(recent.exists());self.assertEqual(self.final.read_bytes(),before);self.assertEqual(r['freed_bytes'],280*1024**2)
    def test_root_unique_metadata_preserved(self):
        self.seed(self.history());old=self.history();old['unique_note']=None;p=self.temp(old);r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unique'],1)
    def test_unlink_failure_accounting(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes())
        actual=os.unlink
        def unlink(name,*args,**kwargs):
            if str(name)==p.name:raise OSError(errno.EACCES,'denied')
            return actual(name,*args,**kwargs)
        with patch('disk_forensik.os.unlink',side_effect=unlink):r=self.clean()
        self.assertTrue(p.exists());self.assertEqual(r['eligible'],1);self.assertEqual(r['removed'],0);self.assertEqual(r['freed_bytes'],0);self.assertEqual(r['errors'],1)
    def test_one_gib_target_and_all_proven_cleanup(self):
        self.seed(self.history());candidates=[self.temp(self.final.read_bytes(),name='.user-'+str(i)+'.tmp') for i in range(4)]
        def usage(root):
            free=100*1024**2+sum(400*1024**2 for p in candidates if not p.exists())
            return shutil._ntuple_diskusage(5*1024**3,5*1024**3-free,free)
        with patch('disk_forensik.shutil.disk_usage',side_effect=usage):r=self.clean()
        self.assertEqual(r['removed'],4);self.assertGreaterEqual(r['after_free'],TARGET_FREE);self.assertEqual(r['after_free']-r['before_free'],1600*1024**2)
    def test_manifest_retention_bound(self):
        from disk_forensik import write_manifest
        entries=[{'classification':'PROVEN_REDUNDANT','size':1,'hash_prefix':'abc','reason':'SHA256_AND_SIZE_EQUAL','dataset':'ai_ogrenme_gecmisi.json'} for _ in range(300)]
        write_manifest(self.location,entries);m=json.loads((self.location.runtime/'disk_cleanup_manifest.json').read_text());self.assertEqual(len(m['entries']),256);self.assertEqual(m['removed_count'],300);self.assertEqual(m['removed_bytes'],300)
    def test_log_contains_counts_not_payload(self):
        self.seed(self.history());p=self.temp(b'{"SECRET_USER_VALUE":true}')
        with self.assertLogs(level='INFO') as logs:r=self.clean()
        text=' '.join(logs.output);self.assertIn('[DISK_FORENSIC]',text);self.assertIn('[DISK_TEMP_CLEANUP]',text);self.assertNotIn('SECRET_USER_VALUE',text);self.assertTrue(p.exists())
    def test_real_concurrent_writer_lease(self):
        import threading
        self.seed(self.history());ready=threading.Event();release=threading.Event();errors=[];actual=json.dump
        def dumping(*args,**kwargs):
            actual(*args,**kwargs);p=next(self.location.runtime.glob('.user-*.tmp'));os.utime(p,(0,0));ready.set();release.wait(10)
        def write():
            try:atomic_write_json(self.final,self.history([self.row(),self.row('TWO')]))
            except Exception as error:errors.append(error)
        with patch('atomik_depolama.json.dump',side_effect=dumping):
            t=threading.Thread(target=write);t.start()
            try:
                self.assertTrue(ready.wait(5));r=self.clean();self.assertEqual(r['skipped_active'],1);self.assertEqual(r['removed'],0)
            finally:release.set();t.join(timeout=10)
        self.assertFalse(t.is_alive());self.assertFalse(errors);self.assertFalse(list(self.location.runtime.glob('.user-*.tmp')))
    def test_guard_large_rewrite_reenabled_after_cleanup(self):
        payload={'large':'x'*1100000};atomic_write_json(self.final,payload);p=self.temp(self.final.read_bytes())
        def usage(root):
            free=100000 if p.exists() else 10000000
            return shutil._ntuple_diskusage(20000000,20000000-free,free)
        with patch('disk_forensik.shutil.disk_usage',side_effect=usage):
            with self.assertRaises(OSError):atomic_write_json(self.final,{'large':'z'*1100000})
            r=self.clean();self.assertEqual(r['removed'],1);atomic_write_json(self.final,{'large':'z'*1100000})
        self.assertEqual(json.loads(self.final.read_text())['large'][0],'z')
    def test_provenance_timestamp_not_assumed_housekeeping(self):
        target=self.location.runtime/'ai_fiyat_teyit.json';target.write_text('{"updated_at":"2026-10-09T00:00:00+03:00","price":100}')
        token=hashlib.sha256(target.name.encode()).hexdigest()[:24];p=self.temp({'updated_at':'2026-10-08T00:00:00+03:00','price':100},name='.user-v2-'+token+'-old.tmp');r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unique'],1)
    def test_record_named_metadata_not_confused_with_array_entry(self):
        self.seed(self.history([self.row(),self.row('TWO')]));old=self.history();old['record']=self.row('TWO');p=self.temp(old);r=self.clean();self.assertTrue(p.exists());self.assertEqual(r['skipped_unique'],1)
    def test_manifest_failure_visible_and_final_safe(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes());before=self.final.read_bytes()
        with patch('kullanici_kayitlari.atomic_json',side_effect=OSError(errno.ENOSPC,'full')):r=self.clean()
        self.assertFalse(p.exists());self.assertEqual(r['removed'],1);self.assertEqual(r['errors'],1);self.assertEqual(self.final.read_bytes(),before)
    def test_temp_fd_closed_before_free_measurement(self):
        self.seed(self.history());p=self.temp(self.final.read_bytes());identity=(p.stat().st_dev,p.stat().st_ino);actual=shutil.disk_usage;checks=[]
        def usage(root):
            if not p.exists():
                for fd in Path('/proc/self/fd').iterdir():
                    try:info=fd.stat()
                    except FileNotFoundError:continue
                    self.assertNotEqual((info.st_dev,info.st_ino),identity)
                checks.append(True)
            return actual(root)
        with patch('disk_forensik.shutil.disk_usage',side_effect=usage):r=self.clean()
        self.assertTrue(checks);self.assertEqual(r['removed'],1)
