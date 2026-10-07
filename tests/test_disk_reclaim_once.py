import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from veri_yollari import DataPaths
from disk_koruma import reclaim_once,_replay_schema

class OneShotReclaimTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
  self.usage=shutil._ntuple_diskusage(500*1024**2,499*1024**2,1024**2)
  self.enterContext(patch('disk_koruma.shutil.disk_usage',return_value=self.usage))
 def file(self,folder,name,data,old=True):
  p=folder/name;p.write_bytes(data)
  if old:os.utime(p,(0,0))
  return p
 def test_exact_duplicate_temp_removed_original_byte_preserved(self):
  original=self.file(self.location.runtime,'ai_ogrenme_gecmisi.json',b'{"records":[1,2,3]}')
  duplicate=self.file(self.location.runtime,'.user-old.tmp',original.read_bytes());unique=self.file(self.location.runtime,'.user-unique.tmp',b'{"unique":true}')
  result=reclaim_once(self.location);self.assertFalse(duplicate.exists());self.assertTrue(unique.exists());self.assertEqual(original.read_bytes(),b'{"records":[1,2,3]}');self.assertFalse(result['permanent_data_deleted'])
 def test_archive_temp_duplicate_not_snapshot_is_removed(self):
  archive=self.file(self.location.archives,'2026-10-06.json',b'{"top10":[1]}');temp=self.file(self.location.archives,'.snapshot-old.tmp',archive.read_bytes())
  reclaim_once(self.location);self.assertTrue(archive.exists());self.assertFalse(temp.exists())
 def test_private_user_directory_is_never_cleaned(self):
  original=self.file(self.location.users,'user.json',b'KEEP');temp=self.file(self.location.users,'.user-old.tmp',b'KEEP');backup=self.file(self.location.users,'user.json.bak',b'KEEP')
  reclaim_once(self.location);self.assertTrue(all(p.read_bytes()==b'KEEP' for p in (original,temp,backup)))
 def test_exact_named_backup_removed_but_unique_history_backup_kept(self):
  main=self.file(self.location.runtime,'tahmin_gecmisi.json',b'KEEP');duplicate=self.file(self.location.runtime,'tahmin_gecmisi.json.bak',b'KEEP');unique=self.file(self.location.runtime,'tahmin_gecmisi.json.backup',b'OTHER')
  reclaim_once(self.location);self.assertFalse(duplicate.exists());self.assertTrue(unique.exists());self.assertEqual(main.read_bytes(),b'KEEP')
 def test_unknown_backup_and_partial_temp_preserved(self):
  paths=[self.file(self.location.runtime,'backup_123.json',b'KEEP'),self.file(self.location.public,'.migration-old',b'partial'),self.file(self.location.runtime,'.user-partial.tmp',b'partial')]
  reclaim_once(self.location);self.assertTrue(all(p.exists() for p in paths))
 def test_fresh_duplicate_is_not_removed(self):
  self.file(self.location.runtime,'ai_ogrenme_gecmisi.json',b'KEEP');fresh=self.file(self.location.runtime,'.user-new.tmp',b'KEEP',False)
  reclaim_once(self.location);self.assertTrue(fresh.exists())
 def test_idempotent_and_recreated_cache_not_deleted_twice(self):
  cache=self.file(self.location.runtime,'performans_fiyat_cache.json',b'{"AAA":{"day":"2026-10-07","closed":true,"bars":[]}}')
  self.assertEqual(reclaim_once(self.location)['status'],'COMPLETED');self.assertFalse(cache.exists())
  cache.write_bytes(b'{"AAA":{"day":"2026-10-07","closed":true,"bars":[]}}')
  self.assertEqual(reclaim_once(self.location)['status'],'ALREADY_ATTEMPTED');self.assertTrue(cache.exists())
 def test_marker_failure_prevents_any_deletion(self):
  import errno
  self.file(self.location.runtime,'ai_ogrenme_gecmisi.json',b'KEEP');duplicate=self.file(self.location.runtime,'.user-old.tmp',b'KEEP')
  with patch('kullanici_kayitlari.atomic_json',side_effect=OSError(errno.ENOSPC,'full')):self.assertEqual(reclaim_once(self.location)['status'],'INCOMPLETE')
  self.assertTrue(duplicate.exists())
 def test_unknown_cache_schema_not_deleted(self):
  cache=self.file(self.location.runtime,'performans_fiyat_cache.json',b'{"history":[1,2,3]}')
  reclaim_once(self.location);self.assertTrue(cache.exists())
 def test_symlink_not_followed_or_removed(self):
  original=self.file(self.location.runtime,'ai_ogrenme_gecmisi.json',b'KEEP');link=self.location.runtime/'.user-old.tmp';link.symlink_to(original)
  reclaim_once(self.location);self.assertTrue(link.is_symlink());self.assertEqual(original.read_bytes(),b'KEEP')
 def test_real_space_gain_is_logged_not_sum_of_file_sizes(self):
  cache=self.file(self.location.runtime,'performans_fiyat_cache.json',b'{"AAA":{"day":"2026-10-07","closed":true,"bars":[]}}')
  def usage(_):
   free=1024**2 if cache.exists() else 120*1024**2
   return shutil._ntuple_diskusage(500*1024**2,500*1024**2-free,free)
  with patch('disk_koruma.shutil.disk_usage',side_effect=usage),self.assertLogs(level='INFO') as logs:result=reclaim_once(self.location)
  self.assertEqual(result['freed_bytes'],119*1024**2);self.assertIn('freed_MiB=119.00',' '.join(logs.output));self.assertFalse(result['target_met'])
 def test_streaming_cache_schema_large_and_chunked(self):
  data={str(i):{'day':'2026-10-07','closed':True,'bars':[{'timestamp':'2026-10-06','open':100,'high':110,'low':90,'close':101}]*100} for i in range(100)}
  path=self.file(self.location.runtime,'performans_fiyat_cache.json',json.dumps(data).encode())
  self.assertTrue(_replay_schema(path))
 def test_streaming_schema_rejects_trailing_bytes_and_tracking_data(self):
  path=self.location.runtime/'performans_fiyat_cache.json'
  for data in (b'{"A":{"day":"2026-10-07","closed":true,"bars":[]}} TRAILING',b'{"A":{"day":"2026-10-07","closed":true,"bars":[{"sonuc_1g":12}]}}',b'{"A":{"day":"2026-10-07","closed":true,"bars":[]},}',b'{"A":{"day":"2026-10-07","closed":true,"bars":[{"timestamp":"2026-10-07","close":"PRIVATE_NOTE"}]}}'):
   path.write_bytes(data)
   try:self.assertFalse(_replay_schema(path))
   except ValueError:pass
