import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import Mock,patch
from concurrent.futures import ThreadPoolExecutor
from v6_storage import railway_schema_check as check

class RailwaySchemaCheckTests(unittest.TestCase):
 def result(self,code=0,**payload):return SimpleNamespace(returncode=code,stdout=json.dumps(payload))
 def setup_runner(self,result):
  self.enterContext(patch.dict(os.environ,{},clear=True))
  return Mock(return_value=result)
 def test_success_exact_readonly_command_and_env_preserved(self):
  runner=self.setup_runner(self.result(verified=True,read_only=True,applied=[]));before=dict(os.environ)
  with self.assertLogs(level='INFO') as logs:self.assertTrue(check.run_check(Path('/tmp/test-code'),runner))
  self.assertEqual(runner.call_args.args[0][1:],['-B','-m','v6_storage','schema','--check'])
  self.assertNotIn('env',runner.call_args.kwargs);self.assertEqual(dict(os.environ),before)
  self.assertEqual(runner.call_args.kwargs['stderr'],subprocess.DEVNULL);self.assertEqual(runner.call_args.kwargs['timeout'],45)
  self.assertIn('SUCCESS',str(logs.output))
 def test_missing_readonly_success_rejected(self):
  runner=self.setup_runner(self.result(verified=True,applied=[]))
  with self.assertLogs(level='INFO') as logs:self.assertFalse(check.run_check('/tmp/code',runner))
  self.assertIn('UNVERIFIED_OUTPUT',str(logs.output))
 def test_applied_migrations_success_rejected(self):
  runner=self.setup_runner(self.result(verified=True,read_only=True,applied=['001_core.sql']))
  with self.assertLogs(level='INFO') as logs:self.assertFalse(check.run_check('/tmp/code',runner))
  self.assertIn('UNVERIFIED_OUTPUT',str(logs.output))
 def test_secret_fields_never_logged(self):
  runner=self.setup_runner(self.result(2,error='SECRET_PASSWORD',stage='SECRET_HOST',sqlstate='TOKEN',dsn='SECRET_URI',trace='SECRET_TRACE'))
  with self.assertLogs(level='INFO') as logs:self.assertFalse(check.run_check('/tmp/code',runner))
  self.assertNotIn('SECRET',str(logs.output));self.assertNotIn('TOKEN',str(logs.output));self.assertIn('UNKNOWN_SAFE_ERROR',str(logs.output))
 def test_specific_codes_logged(self):
  for code in ('POSTGRES_TLS_REQUIRED','POSTGRES_AUTH_FAILED','POSTGRES_PERMISSION_DENIED','SCHEMA_MIGRATION_REQUIRED','POSTGRES_TABLE_MISSING','POSTGRES_DEPENDENCY_MISSING'):
   runner=self.setup_runner(self.result(2,error=code,stage='SCHEMA_VERIFY'))
   with self.assertLogs(level='INFO') as logs:self.assertFalse(check.run_check('/tmp/code',runner))
   self.assertIn(code,str(logs.output))
 def test_timeout_safe_and_no_retry(self):
  runner=self.setup_runner(None);runner.side_effect=subprocess.TimeoutExpired('SECRET_DSN',45)
  with self.assertLogs(level='INFO') as logs:self.assertFalse(check.run_check('/tmp/code',runner))
  self.assertIn('CHECK_TIMEOUT',str(logs.output));self.assertNotIn('SECRET',str(logs.output));runner.assert_called_once()
 def test_failed_launch_safe(self):
  runner=self.setup_runner(None);runner.side_effect=OSError('SECRET_DSN')
  with self.assertLogs(level='INFO') as logs:self.assertFalse(check.run_check('/tmp/code',runner))
  self.assertIn('CHECK_LAUNCH_FAILED',str(logs.output));self.assertNotIn('SECRET',str(logs.output))
 def test_invalid_output_safe(self):
  for output in ('SECRET_URI','[]','x'*9000):
   runner=self.setup_runner(SimpleNamespace(returncode=2,stdout=output))
   with self.assertLogs(level='INFO') as logs:self.assertFalse(check.run_check('/tmp/code',runner))
   self.assertIn('UNVERIFIED_OUTPUT',str(logs.output));self.assertNotIn('SECRET',str(logs.output))
 def test_default_off(self):
  with patch.dict(os.environ,{},clear=True),patch.object(check.threading,'Thread') as thread:
   self.assertFalse(check.start_once('/tmp/code'))
  thread.assert_not_called()
 def test_one_per_launcher_concurrent(self):
  import threading
  completed=threading.Event()
  with patch.dict(os.environ,{check.FLAG:'1'},clear=True),patch.object(check,'_attempted',False),patch.object(check,'run_check',side_effect=lambda root:completed.set()) as run:
   with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:check.start_once('/tmp/code'),range(12)))
   self.assertEqual(sum(results),1);self.assertTrue(completed.wait(2));run.assert_called_once()
 def test_old_write_flag_blocks_check(self):
  runner=Mock()
  with patch.dict(os.environ,{'BIST_RUN_POSTGRES_SCHEMA_ONCE':'1'},clear=True),self.assertLogs(level='INFO') as logs:
   self.assertFalse(check.run_check('/tmp/code',runner))
  runner.assert_not_called();self.assertIn('WRITE_CAPABLE_SCHEMA_FLAG_ENABLED',str(logs.output))
 def test_launcher_isolation_web_worker_keep_running(self):
  import cloud_baslat
  stop=Mock();stop.wait.return_value=True;child=Mock(pid=1);child.poll.return_value=None
  with patch.dict(os.environ,{check.FLAG:'1'},clear=True),patch.object(check,'start_once',side_effect=RuntimeError('SECRET')),patch.object(cloud_baslat,'stop_children'):
   with self.assertLogs(level='WARNING') as logs:self.assertEqual(cloud_baslat.supervise(Mock(return_value=child),stop),0)
  self.assertNotIn('SECRET',str(logs.output))

 def test_launcher_old_flag_cannot_start_writer(self):
  import cloud_baslat
  stop=Mock();stop.wait.return_value=True;child=Mock(pid=1);child.poll.return_value=None
  with patch.dict(os.environ,{'BIST_RUN_POSTGRES_SCHEMA_ONCE':'1'},clear=True),patch.object(cloud_baslat.subprocess,'run') as writer,patch.object(cloud_baslat,'stop_children'):
   with self.assertLogs(level='WARNING') as logs:self.assertEqual(cloud_baslat.supervise(Mock(return_value=child),stop),0)
  writer.assert_not_called();self.assertIn('WRITE_CAPABLE_SCHEMA_FLAG_ENABLED',str(logs.output))
 def test_launcher_both_flags_cannot_start_writer(self):
  import cloud_baslat
  stop=Mock();stop.wait.return_value=True;child=Mock(pid=1);child.poll.return_value=None
  with patch.dict(os.environ,{'BIST_RUN_POSTGRES_SCHEMA_ONCE':'1',check.FLAG:'1'},clear=True),patch.object(check,'_attempted',False),patch.object(check,'run_check',wraps=check.run_check) as run,patch.object(cloud_baslat.subprocess,'run') as writer,patch.object(cloud_baslat,'stop_children'):
   cloud_baslat.supervise(Mock(return_value=child),stop)
   import time
   deadline=time.monotonic()+2
   while not run.called and time.monotonic()<deadline:time.sleep(.01)
   self.assertTrue(run.called)
  writer.assert_not_called()
