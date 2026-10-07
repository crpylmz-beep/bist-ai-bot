import errno
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock,patch
from concurrent.futures import Future
import requests
from gorev_hatalari import describe,public_issue,capture,remember,TaskIssue
from ana_motor import AnaMotor,health_snapshot,ISTANBUL
from ana_motor_gorevleri import WorkerTasks
from veri_yollari import DataPaths

class TaskDiagnosticsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
  self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name}));self.now=datetime(2026,10,7,12,tzinfo=ISTANBUL);self.mono=0
 def worker(self):
  worker=WorkerTasks();self.addCleanup(worker.close);return worker
 def error(self,status):
  response=requests.Response();response.status_code=status
  return requests.HTTPError('secret TOKEN URL',response=response)
 def test_http_status_classification_has_no_secrets(self):
  for status,code in ((403,'HTTP_BLOCKED'),(429,'HTTP_RATE_LIMIT'),(401,'HTTP_AUTH'),(503,'HTTP_UNAVAILABLE'),(404,'HTTP_REQUEST')):
   with self.subTest(status=status):self.assertEqual(describe(self.error(status))['code'],code);self.assertNotIn('secret',json.dumps(describe(self.error(status))))
 def test_network_and_disk_are_separate(self):
  self.assertEqual(describe(requests.Timeout('secret'))['category'],'REMOTE');self.assertEqual(describe(OSError(errno.ENOSPC,'secret'))['code'],'DISK_FULL')
 def test_code_and_provider_data_are_separate(self):
  self.assertEqual(describe(ValueError('secret'))['code'],'CODE_ERROR');self.assertEqual(describe(ValueError('secret'),'PROVIDER')['code'],'PROVIDER_DATA')
 def test_public_error_rebuilds_whitelist_not_persisted_messages(self):
  issue=public_issue({'code':'DISK_FULL','message':'TOKEN','category':'FAKE','url':'SECRET','http_status':'TOKEN'})
  self.assertEqual(issue['category'],'STORAGE');self.assertNotIn('TOKEN',json.dumps(issue));self.assertNotIn('SECRET',json.dumps(issue))
 def test_capture_is_local_and_does_not_change_default_return_contract(self):
  remember(TypeError('outside'))
  with capture() as items:remember(requests.Timeout('secret'));self.assertEqual(items[0]['code'],'NETWORK_TIMEOUT')
  with capture() as other:self.assertEqual(other,[])
 def fail_task(self,error,name='kap'):
  motor=AnaMotor({name:Mock()},self.location.runtime,clock=lambda:self.now,monotonic=lambda:self.mono);self.addCleanup(motor.shutdown)
  future=Future();future.set_exception(error);motor.tasks[name].future=future;motor.tick()
  return motor
 def test_external_failure_is_retrying_and_engine_remains_running(self):
  motor=self.fail_task(self.error(429));self.assertEqual(motor.state['tasks']['kap']['status'],'RETRYING');self.assertEqual(motor.state['motor_durumu'],'RUNNING')
 def test_disk_failure_is_not_hidden_as_remote(self):
  motor=self.fail_task(OSError(errno.ENOSPC,'secret'));self.assertEqual(motor.state['tasks']['kap']['status'],'ERROR');self.assertEqual(motor.state['tasks']['kap']['last_error']['code'],'DISK_FULL')
 def test_partial_remote_failure_is_degraded(self):
  motor=self.fail_task(TaskIssue(describe(self.error(503)),completed=2));self.assertEqual(motor.state['tasks']['kap']['status'],'DEGRADED')
 def test_retry_countdown_and_recovery_clear_current_error(self):
  motor=self.fail_task(requests.Timeout('secret'));initial=motor.state['tasks']['kap']['retry_in_seconds'];self.mono=5;motor.tick()
  self.assertEqual(motor.state['tasks']['kap']['retry_in_seconds'],initial-5)
  future=Future();future.set_result(1);motor.tasks['kap'].future=future;motor.tick();self.assertEqual(motor.state['tasks']['kap']['status'],'OK');self.assertNotIn('last_error',motor.state['tasks']['kap'])
 def test_health_has_safe_short_error(self):
  motor=self.fail_task(OSError(errno.ENOSPC,'TOKEN'))
  with patch('ana_motor.istanbul_now',return_value=self.now):result=health_snapshot(self.location.runtime)
  self.assertTrue(result['healthy']);self.assertEqual(result['tasks']['kap']['last_error']['code'],'DISK_FULL');self.assertNotIn('TOKEN',json.dumps(result))
 def test_failed_full_scan_batch_does_not_starve_next_batch(self):
  worker=self.worker();worker.symbols=['AAA','BBB','CCC'];worker.batch_size=2
  with patch.object(worker.live,'tek_hisse_guncelle',return_value=('AAA',None)),patch.object(worker.bot,'web_verisi_kaydet') as write:
   with self.assertRaises(TaskIssue) as error:worker.full_scan()
   self.assertEqual(error.exception.issue['code'],'ANALYSIS_NO_RESULT');self.assertEqual(worker.cursor,2);self.assertEqual(set(worker.events),{'AAA','BBB'});write.assert_not_called()
 def test_priority_continues_other_stocks_after_failure(self):
  worker=self.worker();worker.enqueue('AAA');worker.enqueue('BBB')
  with patch.object(worker,'original_priority',side_effect=[self.error(503),{'sembol':'BBB'}]) as provider,patch.object(worker,'ai_context',return_value={}):
   with self.assertRaises(TaskIssue) as error:worker.priority()
   self.assertEqual(provider.call_count,2)
  self.assertEqual(error.exception.completed,1);self.assertIn('AAA',worker.events);self.assertNotIn('BBB',worker.events)
 def test_company_site_partial_errors_are_reported(self):
  worker=self.worker();worker.company=Mock();worker.company.tek_tur.return_value=1;worker.company.last_round_issue=describe(self.error(403))
  with self.assertRaises(TaskIssue) as error:worker.company_site()
  self.assertEqual(error.exception.issue['code'],'HTTP_BLOCKED');self.assertEqual(error.exception.completed,1)
 def test_performance_provider_failure_is_not_generic_runtime_error(self):
  worker=self.worker();result={'hatalar':{'AAA':'Timeout'},'error_details':{'AAA':describe(requests.Timeout())},'tamamlanan_vade':0}
  with patch('performans_motoru.bekleyen_sonuclari_guncelle',return_value=result),patch('yarin_kalibrasyon.YarinKalibrasyon.refresh',return_value={}):
   with self.assertRaises(TaskIssue) as error:worker.performance()
  self.assertEqual(error.exception.issue['code'],'NETWORK_TIMEOUT')
 def test_analysis_provider_exception_is_preserved_without_raising_ui(self):
  import bist_bot
  with patch.object(bist_bot.bp,'Ticker') as ticker:
   ticker.return_value.history.side_effect=requests.Timeout('secret')
   with capture() as issues:self.assertIsNone(bist_bot.hisse_analiz_hesapla('THYAO'))
  self.assertEqual(issues[0]['code'],'NETWORK_TIMEOUT')
 def test_degraded_last_batch_does_not_restart_bootstrap_forever(self):
  worker=self.worker();worker.symbols=['AAA','BBB'];worker.cursor=1;worker.cycle_successful=1
  with patch.object(worker.live,'tek_hisse_guncelle',return_value=('BBB',None)):
   with self.assertRaises(TaskIssue):worker.bootstrap()
  marker=json.loads((worker.directory/'public_bootstrap_complete.json').read_text());self.assertEqual(marker['status'],'DEGRADED')
 def test_borsapy_api_error_is_not_unknown_or_ok(self):
  from borsapy.exceptions import APIError
  motor=self.fail_task(TaskIssue(describe(APIError('secret URL TOKEN'))),name='priority')
  task=motor.state['tasks']['priority'];self.assertEqual(task['status'],'RETRYING');self.assertEqual(task['last_error']['code'],'PROVIDER_API_ERROR');self.assertNotIn('TOKEN',json.dumps(task))
 def test_borsapy_api_http_status_and_wrapped_timeout(self):
  from borsapy.exceptions import APIError
  import httpx
  self.assertEqual(describe(APIError('secret',status_code=429))['code'],'HTTP_RATE_LIMIT')
  try:
   try:raise httpx.ConnectTimeout('secret')
   except httpx.ConnectTimeout as cause:raise APIError('secret') from cause
  except APIError as error:self.assertEqual(describe(error)['code'],'NETWORK_TIMEOUT')
 def test_provider_missing_data_and_invalid_config_are_distinct(self):
  from borsapy.exceptions import DataNotAvailableError,InvalidPeriodError
  self.assertEqual(describe(DataNotAvailableError('secret'))['code'],'PROVIDER_DATA')
  self.assertEqual(describe(InvalidPeriodError('secret'))['code'],'PROVIDER_CONFIG')
 def test_source_trace_preserves_location_without_exception_contents(self):
  def broken():raise RuntimeError('TOKEN https://private/?key=SECRET')
  with self.assertLogs(level='WARNING') as logs:
   with capture() as issues:
    try:broken()
    except RuntimeError as error:remember(error,'ANALYSIS')
  output=' '.join(logs.output);self.assertIn('broken',output);self.assertIn('RuntimeError',output);self.assertNotIn('TOKEN',output);self.assertNotIn('SECRET',output)
  self.assertEqual(issues[0]['code'],'TASK_ERROR')
 def test_full_scan_provider_errors_retain_source_reason(self):
  from borsapy.exceptions import APIError
  worker=self.worker();worker.symbols=['AAA'];worker.batch_size=1
  with patch.object(worker.live,'tek_hisse_guncelle',side_effect=APIError('secret')):
   with self.assertRaises(TaskIssue) as error:worker.full_scan()
  self.assertEqual(error.exception.issue['code'],'PROVIDER_API_ERROR');self.assertEqual(worker.cursor,1);self.assertIn('AAA',worker.events)
 def test_dns_and_tls_are_not_generic_connection(self):
  import socket
  self.assertEqual(describe(socket.gaierror('secret'))['code'],'NETWORK_DNS')
  self.assertEqual(describe(requests.exceptions.SSLError('secret'))['code'],'NETWORK_TLS')
