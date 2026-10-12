import errno
import json
import os
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
from veri_yollari import DataPaths,copy_new
from disk_koruma import cleanup_startup,report,trim_price_cache,save_price_cache,CACHE_LIMIT

class DiskSafetyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
  self.source=Path(self.temp.name)/'seed.json';self.source.write_text('{"source":true}')
  self.target=self.location.public/'bist_data.json'
 def usage(self,free=0):return shutil._ntuple_diskusage(500*1024*1024,500*1024*1024-free,free)
 def test_existing_target_never_allocates_or_copies(self):
  self.target.write_text('LIVE')
  with patch('veri_yollari.tempfile.mkstemp',side_effect=AssertionError('unnecessary temp')),patch('veri_yollari.shutil.copyfileobj',side_effect=AssertionError('unnecessary copy')):
   self.assertFalse(copy_new(self.source,self.target))
  self.assertEqual(self.target.read_text(),'LIVE')
 def test_not_enough_space_preserves_source_and_skips(self):
  with patch('veri_yollari.shutil.disk_usage',return_value=self.usage()),self.assertLogs(level='WARNING') as logs:
   self.assertFalse(copy_new(self.source,self.target))
  self.assertFalse(self.target.exists());self.assertTrue(self.source.exists());self.assertFalse(list(self.location.public.glob('.migration-*')))
  self.assertIn('required_bytes',' '.join(logs.output))
 def test_enospc_during_copy_cleans_partial_not_source(self):
  def fail(original,stream):stream.write(b'partial');raise OSError(errno.ENOSPC,'full')
  with patch('veri_yollari.shutil.copyfileobj',side_effect=fail):self.assertFalse(copy_new(self.source,self.target))
  self.assertTrue(self.source.exists());self.assertFalse(self.target.exists());self.assertFalse(list(self.location.public.glob('.migration-*')))
 def test_enospc_during_fsync_is_controlled(self):
  with patch('veri_yollari.os.fsync',side_effect=OSError(errno.ENOSPC,'full')):self.assertFalse(copy_new(self.source,self.target))
  self.assertFalse(self.target.exists());self.assertTrue(self.source.exists())
 def test_enospc_temp_creation_is_controlled(self):
  with patch('veri_yollari.tempfile.mkstemp',side_effect=OSError(errno.ENOSPC,'full')):self.assertFalse(copy_new(self.source,self.target))
 def test_concurrent_copies_only_one_full_copy(self):
  from veri_yollari import shutil as module
  actual=module.copyfileobj
  with patch('veri_yollari.shutil.copyfileobj',wraps=actual) as copies:
   with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:copy_new(self.source,self.target),range(4)))
   self.assertEqual(sum(results),1);self.assertEqual(copies.call_count,1)
  self.assertEqual(self.target.read_bytes(),self.source.read_bytes())
 def test_symlink_target_never_written(self):
  self.target.symlink_to(self.location.users/'missing.json');self.assertFalse(copy_new(self.source,self.target))
 def test_cleanup_preserves_all_durable_data_and_unknown_backups(self):
  protected=[self.location.archives/'2026-10-01.json',self.location.users/'account.json',self.location.runtime/'ai_ogrenme_gecmisi.json',self.location.runtime/'gun_ici_mumlar.json',self.location.runtime/'backup.bak',self.location.public/'.snapshot-abc.tmp',self.location.users/'.user-abc.tmp',self.location.archives/'.migration-abc',self.location.public/'.migration-unknown-old']
  for path in protected:path.write_text('KEEP');os.utime(path,(0,0))
  scratch=self.location.public/'.migration-bist_data.json-old';scratch.write_text('partial');os.utime(scratch,(0,0))
  fresh=self.location.public/'.migration-active';fresh.write_text('active')
  self.assertEqual(cleanup_startup(self.location),7);self.assertFalse(scratch.exists());self.assertTrue(fresh.exists())
  self.assertTrue(all(p.read_text()=='KEEP' for p in protected))
 def test_cache_only_removed_under_pressure_with_known_schema(self):
  cache=self.location.runtime/'performans_fiyat_cache.json';cache.write_text(json.dumps({'AAA':{'day':'2026-10-07','closed':True,'bars':[]}}))
  with patch('disk_koruma.shutil.disk_usage',return_value=self.usage()):self.assertGreater(cleanup_startup(self.location),0)
  self.assertFalse(cache.exists())
 def test_unknown_cache_content_is_preserved(self):
  cache=self.location.runtime/'performans_fiyat_cache.json';cache.write_text('{"history":[1,2,3]}')
  with patch('disk_koruma.shutil.disk_usage',return_value=self.usage()):self.assertEqual(cleanup_startup(self.location),0)
  self.assertTrue(cache.exists())
 def test_symlink_scratch_never_followed(self):
  protected=self.location.users/'user.json';protected.write_text('KEEP');(self.location.public/'.migration-old').symlink_to(protected)
  cleanup_startup(self.location);self.assertEqual(protected.read_text(),'KEEP')
 def test_report_all_files_and_never_prints_private_identity(self):
  (self.location.users/'SECRET_USER_ID.json').write_text('secret payload')
  (self.location.root/'unexpected.bin').write_bytes(b'x'*20)
  with self.assertLogs(level='INFO') as logs:result=report(self.location)
  self.assertEqual(result['groups']['other']['files'],2);self.assertEqual(result['groups']['private']['files'],1)
  self.assertNotIn('SECRET_USER_ID',' '.join(logs.output));self.assertNotIn('secret payload',' '.join(logs.output))
 def test_cache_retention_is_bounded_without_touching_input(self):
  day=date(2026,10,7);cache={'old':{'day':(day-timedelta(days=4)).isoformat(),'bars':[]},'new':{'day':day.isoformat(),'closed':True,'bars':[{'close':100}]},'future':{'day':(day+timedelta(days=1)).isoformat(),'bars':[]}}
  before=json.dumps(cache);result=trim_price_cache(cache,day);self.assertEqual(set(result),{'new'});self.assertEqual(json.dumps(cache),before)
  big={str(i):{'day':day.isoformat(),'bars':['x'*10000]*100} for i in range(10)}
  self.assertLess(len(json.dumps(trim_price_cache(big,day),indent=2).encode()),CACHE_LIMIT)
 def test_bootstrap_no_space_does_not_crash(self):
  from cloud_bootstrap import bootstrap_public
  with patch('cloud_bootstrap._bootstrap_public',side_effect=OSError(errno.ENOSPC,'full')):self.assertEqual(bootstrap_public(self.location)['storage_status'],'INSUFFICIENT_SPACE')
 def test_optional_cache_does_not_take_last_free_bytes(self):
  path=self.location.runtime/'performans_fiyat_cache.json';path.write_text('OLD')
  with patch('disk_koruma.shutil.disk_usage',return_value=self.usage()):self.assertFalse(save_price_cache(path,{}))
  self.assertEqual(path.read_text(),'OLD')
 def test_optional_cache_write_failure_preserves_old_file(self):
  path=self.location.runtime/'performans_fiyat_cache.json';path.write_text('OLD')
  with patch('kullanici_kayitlari.atomic_json',side_effect=OSError(errno.ENOSPC,'full')):self.assertFalse(save_price_cache(path,{}))
  self.assertEqual(path.read_text(),'OLD')
 def test_heartbeat_no_space_preserves_old_state(self):
  from ana_motor import AnaMotor
  path=self.location.runtime/'ana_motor_durum.json';path.write_text('{"yarin_completed_day":"2026-10-06"}')
  with patch('ana_motor.atomic_json',side_effect=OSError(errno.ENOSPC,'full')):
   motor=AnaMotor({},directory=self.location.runtime);motor.persist();motor.executor.shutdown()
  self.assertEqual(json.loads(path.read_text())['yarin_completed_day'],'2026-10-06')
