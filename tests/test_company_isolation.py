import json
import unittest
from unittest.mock import patch
import requests
import test_sirket_site_motoru as fixtures
import test_gorev_hatalari as worker_fixtures
from gorev_hatalari import ResponseLimitError,TaskIssue,SiteUrlError

class CompanyIsolationTests(unittest.TestCase):
 setUp=fixtures.CompanyMonitorTests.setUp
 rss=fixtures.CompanyMonitorTests.rss
 fetch=fixtures.CompanyMonitorTests.fetch
 monitor=fixtures.CompanyMonitorTests.monitor
 def http(self,status):
  response=requests.Response();response.status_code=status
  return requests.HTTPError('private URL',response=response)
 def round(self,error,all_bad=False):
  self.mapping.write_text(json.dumps({'hisseler':{stock:{'siteler':[f'https://{host}.example/']} for stock,host in [('AAA','a'),('BBB','b'),('CCC','c')]}}))
  for stock,host in [('AAA','a'),('BBB','b'),('CCC','c')]:
   self.fixture[f'https://{host}.example/robots.txt']='User-agent: *\nAllow: /'
   self.fixture[f'https://{host}.example/']=error if all_bad or stock=='AAA' else '<html></html>'
  monitor=self.monitor(batch_size=3,min_interval=0);monitor.tek_tur()
  return monitor
 def test_isolated_source_failures_preserve_other_sites_and_state(self):
  failures=[self.http(404),self.http(410),self.http(503),self.http(429),requests.exceptions.SSLError('expired'),requests.Timeout(),requests.ConnectionError(),ResponseLimitError(),SiteUrlError('redirect blocked')]
  for error in failures:
   with self.subTest(type=type(error).__name__,status=getattr(error.response,'status_code',None) if isinstance(error,requests.HTTPError) else None):
    self.setUp()
    monitor=self.round(error)
    self.assertTrue(monitor.last_round_isolated);self.assertFalse(monitor.last_round_systemic)
    self.assertEqual(monitor.last_round_details['successful'],2);self.assertEqual(monitor.last_round_details['failed'],1)
    state=json.loads(monitor.path.read_text());self.assertEqual(state['sites']['BBB']['status'],'OK');self.assertEqual(state['sites']['CCC']['status'],'OK')
 def test_widespread_tls_dns_and_network_are_not_isolated(self):
  import socket
  for error in (requests.exceptions.SSLError('expired'),socket.gaierror(),requests.ConnectionError(),self.http(503)):
   with self.subTest(type=type(error).__name__):
    self.setUp();monitor=self.round(error,all_bad=True)
    self.assertFalse(monitor.last_round_isolated);self.assertTrue(monitor.last_round_systemic);self.assertEqual(monitor.last_round_details['systemic_errors'],3)
 def test_programming_error_is_never_source_skip(self):
  monitor=self.round(TypeError('wrong data model'))
  self.assertFalse(monitor.last_round_isolated);self.assertEqual(monitor.last_round_issue['code'],'CODE_ERROR')
 def test_source_counters(self):
  monitor=self.round(requests.exceptions.SSLError())
  self.assertEqual(monitor.last_round_details['tls_errors'],1)
  self.setUp();monitor=self.round(self.http(404));self.assertEqual(monitor.last_round_details['http_errors'],1)
  self.setUp();monitor=self.round(ResponseLimitError());self.assertEqual(monitor.last_round_details['response_too_large'],1)

class SchedulerIsolationTests(unittest.TestCase):
 setUp=worker_fixtures.TaskDiagnosticsTests.setUp
 fail_task=worker_fixtures.TaskDiagnosticsTests.fail_task
 def test_isolated_404_and_tls_have_no_900_second_global_pause(self):
  for code in ('HTTP_REQUEST','NETWORK_TLS','NETWORK_CONNECTION','SOURCE_RESPONSE_TOO_LARGE'):
   motor=self.fail_task(TaskIssue({'code':code,'http_status':404},completed=2,isolated=True),name='company_site');motor.stop.set()
   task=motor.state['tasks']['company_site'];self.assertEqual(task['status'],'DEGRADED');self.assertEqual(task['retry_in_seconds'],30)
 def test_widespread_failure_keeps_global_backoff_despite_a_success(self):
  motor=self.fail_task(TaskIssue({'code':'NETWORK_TLS'},completed=1,systemic=True),name='company_site');motor.stop.set()
  self.assertEqual(motor.state['tasks']['company_site']['status'],'DEGRADED');self.assertEqual(motor.state['tasks']['company_site']['retry_in_seconds'],900)
 def test_critical_code_error_with_success_stays_error(self):
  motor=self.fail_task(TaskIssue({'code':'CODE_ERROR'},completed=2),name='company_site');motor.stop.set()
  self.assertEqual(motor.state['tasks']['company_site']['status'],'ERROR');self.assertEqual(motor.state['tasks']['company_site']['retry_in_seconds'],900)

 def test_isolated_flag_cannot_hide_code_error(self):
  motor=self.fail_task(TaskIssue({'code':'CODE_ERROR'},completed=2,isolated=True),name='company_site');motor.stop.set()
  self.assertEqual(motor.state['tasks']['company_site']['status'],'ERROR');self.assertEqual(motor.state['tasks']['company_site']['retry_in_seconds'],900)

 def test_systemic_flag_cannot_hide_code_error(self):
  motor=self.fail_task(TaskIssue({'code':'CODE_ERROR'},completed=2,systemic=True),name='company_site');motor.stop.set()
  self.assertEqual(motor.state['tasks']['company_site']['status'],'ERROR');self.assertEqual(motor.state['tasks']['company_site']['retry_in_seconds'],900)
