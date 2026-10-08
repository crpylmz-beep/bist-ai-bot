import copy,errno,json,os,shutil,tempfile,threading,time,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import datetime,timezone
from veri_yollari import DataPaths
from kullanici_kayitlari import atomic_json
from atomik_depolama import atomic_write_json,target_lock_name
from atomik_temp_temizligi import cleanup_atomic_temps,MIN_AGE,HistoryIndex,foreign_open as actual_foreign_open

class AtomicStorageTests(unittest.TestCase):
 def setUp(self):
  self.enterContext(patch('atomik_temp_temizligi.foreign_open',return_value=False))  # fixture has no external writer
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure();self.path=self.location.runtime/'ai_ogrenme_gecmisi.json';self.path.write_text('{"original":true}')
 def temps(self):return list(self.location.runtime.glob('.user-*.tmp'))
 def old(self,name,data):
  path=self.location.runtime/name;path.write_bytes(data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,indent=2).encode());os.utime(path,(0,0));return path
 def clean(self):return cleanup_atomic_temps(self.location)
 def history(self,rows=None):return {'kayitlar':rows or [{'kayit_id':'ONE','fiyat':100,'sonuc_1g':None}], 'guncelleme':'2026-10-08T18:30:00+03:00','toplam_kayit':len(rows) if rows is not None else 1}
 def test_success_valid_final(self):atomic_json(self.path,{'new':True});self.assertEqual(json.loads(self.path.read_text()),{'new':True});self.assertFalse(self.temps())
 def test_temp_exists_before_replace(self):
  actual=os.replace;seen=[]
  def replace(source,target):seen.append(Path(source).exists());return actual(source,target)
  with patch('atomik_depolama.os.replace',side_effect=replace):atomic_json(self.path,{'a':1})
  self.assertEqual(seen,[True]);self.assertFalse(self.temps())
 def test_100_writes_no_accumulation(self):
  for n in range(100):atomic_json(self.path,{'n':n})
  self.assertFalse(self.temps());self.assertEqual(json.loads(self.path.read_text())['n'],99)
 def test_serialization_failure(self):
  with self.assertRaises(TypeError):atomic_json(self.path,{'bad':object()})
  self.assertFalse(self.temps());self.assertEqual(json.loads(self.path.read_text()),{'original':True})
 def test_nan_failure(self):
  with self.assertRaises(ValueError):atomic_json(self.path,{'bad':float('nan')})
  self.assertFalse(self.temps())
 def test_mid_serialization_failure(self):
  def fail(value,stream,**options):stream.write('partial');raise ValueError('serialize')
  with patch('atomik_depolama.json.dump',side_effect=fail),self.assertRaises(ValueError):atomic_json(self.path,{'a':1})
  self.assertFalse(self.temps());self.assertIn('original',self.path.read_text())
 def test_write_enospc_preserves_final(self):
  def fail(value,stream,**options):stream.write('x'*100000);raise OSError(errno.ENOSPC,'full')
  with patch('atomik_depolama.json.dump',side_effect=fail),self.assertRaises(OSError) as caught:atomic_json(self.path,{'a':1})
  self.assertEqual(caught.exception.errno,errno.ENOSPC);self.assertFalse(self.temps());self.assertIn('original',self.path.read_text())
 def test_fsync_enospc(self):
  with patch('atomik_depolama.os.fsync',side_effect=OSError(errno.ENOSPC,'full')),self.assertRaises(OSError):atomic_json(self.path,{'a':1})
  self.assertFalse(self.temps());self.assertIn('original',self.path.read_text())
 def test_replace_failure(self):
  with patch('atomik_depolama.os.replace',side_effect=OSError(errno.EIO,'replace')),self.assertRaises(OSError):atomic_json(self.path,{'a':1})
  self.assertFalse(self.temps());self.assertIn('original',self.path.read_text())
 def test_creation_failure(self):
  with patch('atomik_depolama.tempfile.mkstemp',side_effect=OSError(errno.ENOSPC,'full')),self.assertRaises(OSError):atomic_json(self.path,{'a':1})
  self.assertFalse(self.temps());self.assertIn('original',self.path.read_text())
 def test_cleanup_failure_does_not_mask_enospc(self):
  with patch('atomik_depolama.os.replace',side_effect=OSError(errno.ENOSPC,'full')),patch('atomik_depolama.os.unlink',side_effect=OSError(errno.EACCES,'cleanup')),self.assertRaises(OSError) as caught:atomic_json(self.path,{'a':1})
  self.assertEqual(caught.exception.errno,errno.ENOSPC);self.assertIn('original',self.path.read_text())
 def test_fdopen_failure_cleans(self):
  with patch('atomik_depolama.os.fdopen',side_effect=ValueError('open')),self.assertRaises(ValueError):atomic_json(self.path,{'a':1})
  self.assertFalse(self.temps())
 def test_concurrent_writers_single_temp(self):
  actual=json.dump;maximum=[0];lock=threading.Lock()
  def dumping(*args,**options):
   with lock:maximum[0]=max(maximum[0],len(self.temps()))
   time.sleep(.005);return actual(*args,**options)
  with patch('atomik_depolama.json.dump',side_effect=dumping),ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda n:atomic_json(self.path,{'n':n}),range(20)))
  self.assertEqual(maximum[0],1);self.assertFalse(self.temps());self.assertIn('n',json.loads(self.path.read_text()))
 def test_existing_caller_lock_no_deadlock(self):
  from ai_karar_motoru import locked
  with locked(self.path):atomic_json(self.path,{'ok':True})
  self.assertFalse(self.temps())
 def test_create_only_archive_kept(self):
  before=self.path.read_bytes()
  with self.assertRaises(FileExistsError):atomic_write_json(self.path,{'new':True},overwrite=False,prefix='.snapshot-')
  self.assertEqual(self.path.read_bytes(),before)
 def test_snapshot_writer_success_and_failure(self):
  from bist_bot import json_atomik_yaz
  target=self.location.archives/'2026-10-08.json';json_atomik_yaz(target,{'date':datetime(2026,10,8)},False);before=target.read_bytes()
  with self.assertRaises(FileExistsError):json_atomik_yaz(target,{},False)
  self.assertEqual(target.read_bytes(),before);self.assertFalse(list(target.parent.glob('.snapshot-*.tmp')))
 def test_large_guard_no_allocation(self):
  usage=shutil._ntuple_diskusage(10000000,9000000,1000000)
  with patch('atomik_depolama.shutil.disk_usage',return_value=usage),patch('atomik_depolama.tempfile.mkstemp',side_effect=AssertionError('allocation')),self.assertRaises(OSError) as caught:atomic_json(self.path,{'large':'x'*2000000})
  self.assertEqual(caught.exception.errno,errno.ENOSPC);self.assertIn('DISK_SPACE_GUARD',str(caught.exception));self.assertIn('original',self.path.read_text())
 def test_guard_measures_new_payload_not_old_size(self):
  with patch('atomik_depolama.space_guard') as guard:atomic_json(self.path,{'large':'ğ'*10000})
  self.assertEqual(guard.call_args.args[1],len(json.dumps({'large':'ğ'*10000},ensure_ascii=False,indent=2).encode()))
 def test_restart_exact_duplicate(self):
  temp=self.old('.user-old.tmp',self.path.read_bytes());result=self.clean();self.assertFalse(temp.exists());self.assertEqual(result['removed'],1);self.assertEqual(result['freed_bytes'],len(b'{"original":true}'));self.assertIn('original',self.path.read_text())
 def test_recent_skipped(self):
  p=self.old('.user-recent.tmp',self.path.read_bytes());os.utime(p,None);self.assertEqual(self.clean()['skipped_recent'],1);self.assertTrue(p.exists())
 def test_unverified_partial_preserved(self):p=self.old('.user-partial.tmp',b'{"unique":');self.assertEqual(self.clean()['removed'],0);self.assertTrue(p.exists())
 def test_missing_final_recovery_preserved(self):self.path.unlink();p=self.old('.user-only.tmp',b'{"only":true}');self.clean();self.assertTrue(p.exists())
 def test_symlink_skipped(self):
  p=self.location.runtime/'.user-link.tmp';p.symlink_to(self.path);self.clean();self.assertTrue(p.is_symlink());self.assertIn('original',self.path.read_text())
 def test_hardlink_preserved(self):
  p=self.location.runtime/'.user-linked.tmp';os.link(self.path,p);self.clean();self.assertTrue(p.exists())
 def test_private_public_archives_never_scanned(self):
  paths=[self.location.users/'.user-old.tmp',self.location.public/'.user-old.tmp',self.location.archives/'.user-old.tmp']
  for p in paths:p.write_bytes(self.path.read_bytes());os.utime(p,(0,0))
  self.clean();self.assertTrue(all(p.exists() for p in paths))
 def test_runtime_boundary_symlink(self):
  other=Path(self.temp.name)/'elsewhere';other.mkdir();p=other/'.user-old.tmp';p.write_text('unique');self.location.runtime.rename(Path(self.temp.name)/'saved-runtime');self.location.runtime.symlink_to(other,target_is_directory=True)
  self.assertGreater(self.clean()['errors'],0);self.assertTrue(p.exists())
 def test_active_temp_lease_skipped(self):
  import fcntl
  p=self.old('.user-active.tmp',self.path.read_bytes())
  with p.open('rb') as stream:
   fcntl.flock(stream,fcntl.LOCK_EX);self.assertEqual(self.clean()['skipped_active'],1)
  self.assertTrue(p.exists())
 def test_busy_final_lock_preserved(self):
  import fcntl
  p=self.old('.user-busy.tmp',self.path.read_bytes())
  with Path(str(self.path)+'.lock').open('a') as stream:
   fcntl.flock(stream,fcntl.LOCK_EX);self.assertEqual(self.clean()['removed'],0)
  self.assertTrue(p.exists())
 def test_idempotent(self):self.old('.user-old.tmp',self.path.read_bytes());self.clean();self.assertEqual(self.clean()['removed'],0)
 def test_unique_complete_history_preserved(self):
  target=self.history();self.path.write_text(json.dumps(target));different=self.history([{'kayit_id':'TWO','fiyat':120}]);p=self.old('.user-unique.tmp',different);self.clean();self.assertTrue(p.exists())
 def test_frozen_field_change_preserved(self):
  target=self.history();self.path.write_text(json.dumps(target));old=copy.deepcopy(target);old['kayitlar'][0]['fiyat']=101;p=self.old('.user-different.tmp',old);self.clean();self.assertTrue(p.exists())
 def test_old_completed_outcome_change_preserved(self):
  target=self.history();target['kayitlar'][0]['sonuc_1g']={'getiri':5};self.path.write_text(json.dumps(target));old=copy.deepcopy(target);old['kayitlar'][0]['sonuc_1g']['getiri']=7;p=self.old('.user-old-result.tmp',old);self.clean();self.assertTrue(p.exists())
 def test_history_superset_safe(self):
  old=self.history();target=copy.deepcopy(old);target['kayitlar'][0]['sonuc_1g']={'getiri':5};target['kayitlar'].append({'kayit_id':'TWO','fiyat':120});target.update(toplam_kayit=2,guncelleme='2026-10-09T18:30:00+03:00');self.path.write_text(json.dumps(target));before=self.path.read_bytes();p=self.old('.user-subset.tmp',old);self.assertEqual(self.clean()['removed'],1);self.assertFalse(p.exists());self.assertEqual(self.path.read_bytes(),before)
 def test_partial_subset_not_deleted(self):
  self.path.write_text(json.dumps(self.history()));unique=self.history();unique['kayitlar'][0]['fiyat']=101;p=self.old('.user-partial.tmp',json.dumps(unique).encode()[:-1]);self.clean();self.assertTrue(p.exists())
 def test_duplicate_record_id_not_deleted(self):
  target=self.history();self.path.write_text(json.dumps(target));old=self.history([target['kayitlar'][0],target['kayitlar'][0]]);p=self.old('.user-duplicate-id.tmp',old);self.clean();self.assertTrue(p.exists())
 def test_unknown_metadata_preserved(self):
  self.path.write_text(json.dumps(self.history()));old=self.history();old['unique_note']='keep';p=self.old('.user-metadata.tmp',old);self.clean();self.assertTrue(p.exists())
 def test_future_old_timestamp_preserved(self):
  self.path.write_text(json.dumps(self.history()));old=self.history();old['guncelleme']='2027-10-08T18:30:00+03:00';p=self.old('.user-future.tmp',old);self.clean();self.assertTrue(p.exists())
 def test_scan_log_no_contents(self):
  self.old('.user-secret.tmp',b'{"PRIVATE_SECRET":"keep"}')
  with self.assertLogs(level='INFO') as logs:self.clean()
  self.assertIn('[DISK_TEMP_CLEANUP]',' '.join(logs.output));self.assertNotIn('PRIVATE_SECRET',' '.join(logs.output))
 def test_inventory_temp_summary(self):
  from disk_koruma import report
  self.old('.user-old.tmp',b'abc');value=report(self.location)['atomic_temps'];self.assertEqual(value['count'],1);self.assertEqual(value['total_bytes'],3);self.assertGreater(value['oldest_age'],MIN_AGE)
 def test_startup_hook_before_tasks(self):
  import inspect,ana_motor
  body=inspect.getsource(ana_motor.main);self.assertLess(body.index('cleanup_atomic_temps(paths())'),body.index('adapter=WorkerTasks()'))
 def test_producer_reserved_namespace(self):
  with self.assertRaises(ValueError):atomic_json(self.location.runtime/'.user-final.tmp',{})

 def test_partial_exact_prefix_safe(self):
  data=json.dumps(self.history()).encode();self.path.write_bytes(data);p=self.old('.user-prefix.tmp',data[:-1]);result=self.clean();self.assertFalse(p.exists());self.assertEqual(self.path.read_bytes(),data);self.assertEqual(result['freed_bytes'],len(data)-1)
 def test_identical_large_payload_no_second_temp(self):
  value={'large':'x'*1100000};atomic_json(self.path,value);before=self.path.read_bytes()
  with patch('atomik_depolama.tempfile.mkstemp',side_effect=AssertionError('duplicate temp')),patch('atomik_depolama.shutil.disk_usage',return_value=shutil._ntuple_diskusage(1,1,0)):atomic_json(self.path,value)
  self.assertEqual(self.path.read_bytes(),before);self.assertFalse(self.temps())
 def test_directory_fsync_failure_keeps_valid_committed_final(self):
  actual=os.fsync;calls=[0]
  def sync(fd):
   calls[0]+=1
   if calls[0]==2:raise OSError(errno.EIO,'directory sync')
   actual(fd)
  with patch('atomik_depolama.os.fsync',side_effect=sync),self.assertRaises(OSError):atomic_json(self.path,{'committed':True})
  self.assertEqual(json.loads(self.path.read_text()),{'committed':True});self.assertFalse(self.temps())
 def test_uncertain_process_inventory_preserved(self):
  p=self.old('.user-uncertain.tmp',self.path.read_bytes())
  with patch('atomik_temp_temizligi.foreign_open',return_value=None):self.assertEqual(self.clean()['skipped_unverified'],1)
  self.assertTrue(p.exists())
 def test_budget_exhaustion_preserves(self):
  p=self.old('.user-limit.tmp',self.path.read_bytes());self.assertEqual(cleanup_atomic_temps(self.location,budget_seconds=0)['removed'],0);self.assertTrue(p.exists())
 def test_duplicate_json_keys_preserved(self):
  self.path.write_text(json.dumps(self.history()));p=self.old('.user-key.tmp',b'{"kayitlar":[{"kayit_id":"ONE","fiyat":101,"fiyat":100,"sonuc_1g":null}]}');self.clean();self.assertTrue(p.exists())
 def test_process_kill_recovery_copy_preserved_then_redundant_removed(self):
  import subprocess,select,sys
  code="""import time,sys
from unittest.mock import patch
from pathlib import Path
from kullanici_kayitlari import atomic_json
def gate(fd):
 print("READY",flush=True)
 time.sleep(30)
with patch('atomik_depolama.os.fsync',side_effect=gate):
 atomic_json(Path(sys.argv[1]),{'unique':'recover'})
"""
  child=subprocess.Popen([sys.executable,'-c',code,str(self.path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
  try:
   self.assertTrue(select.select([child.stdout],[],[],10)[0]);self.assertEqual(child.stdout.readline().strip(),'READY');child.kill();child.wait(timeout=5)
   orphan=self.temps()[0];os.utime(orphan,(0,0));self.clean();self.assertTrue(orphan.exists());self.assertIn('original',self.path.read_text())
   atomic_json(self.path,{'unique':'recover'});self.clean();self.assertFalse(orphan.exists());self.assertEqual(json.loads(self.path.read_text()),{'unique':'recover'})
  finally:
   if child.poll() is None:child.kill();child.wait()
   child.stdout.close();child.stderr.close()
 def test_two_processes_preserve_caller_read_modify_lock(self):
  import subprocess,sys
  atomic_json(self.path,{'count':0})
  code="""import json,sys
from pathlib import Path
from ai_karar_motoru import locked
from kullanici_kayitlari import atomic_json
p=Path(sys.argv[1])
for i in range(5):
 with locked(p):
  value=json.loads(p.read_text())
  value['count']+=1
  atomic_json(p,value)
"""
  children=[subprocess.Popen([sys.executable,'-c',code,str(self.path)],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}) for _ in range(2)]
  for child in children:self.assertEqual(child.wait(timeout=20),0)
  self.assertEqual(json.loads(self.path.read_text())['count'],10);self.assertFalse(self.temps())

 def test_legacy_open_fd_in_other_process_is_detected(self):
  import subprocess,sys
  fd=os.open(self.path,os.O_RDONLY)
  child=subprocess.Popen([sys.executable,'-c',"import time;print('READY',flush=True);time.sleep(30)"],pass_fds=(fd,),stdout=subprocess.PIPE,text=True)
  try:
   self.assertEqual(child.stdout.readline().strip(),'READY')
   self.assertTrue(actual_foreign_open(fd,processes=[Path('/proc')/str(child.pid)]))
  finally:
   child.kill();child.wait(timeout=5);child.stdout.close();os.close(fd)

 def test_explicit_null_metadata_not_equivalent_to_missing(self):
  self.path.write_text(json.dumps(self.history()));old=self.history();old['unique_note']=None
  p=self.old('.user-null-metadata.tmp',old);self.clean();self.assertTrue(p.exists())

 def test_minimum_age_boundary(self):
  p=self.old('.user-boundary.tmp',self.path.read_bytes());os.utime(p,(10000,10000))
  self.assertEqual(cleanup_atomic_temps(self.location,clock=lambda:10000+MIN_AGE-1)['skipped_recent'],1)
  self.assertTrue(p.exists())
  self.assertEqual(cleanup_atomic_temps(self.location,clock=lambda:10000+MIN_AGE)['removed'],1)
  self.assertFalse(p.exists())
