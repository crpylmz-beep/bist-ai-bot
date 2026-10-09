import json
import unittest
from unittest.mock import patch
from borsapy.exceptions import APIError
from gorev_hatalari import describe,ResponseLimitError,capture,TaskIssue
from saglayici_sembolleri import bist_symbol
from sirket_site_motoru import SirketSiteMotoru,MAX_RESPONSE_BYTES
import test_gorev_hatalari as diagnostics

class ProviderBoundaryTests(unittest.TestCase):
 def test_canonical_symbol_and_no_invented_alias(self):
  for value in (' thyao ','BIST:THYAO','THYAO.IS','THYAO.E'):self.assertEqual(bist_symbol(value),'THYAO')
  self.assertEqual(bist_symbol('OLDSTOCK'),'OLDSTOCK')
  for value in ('NASDAQ:THYAO','THYAO/','THYAO.IS.E','şirket',''):
   with self.assertRaises(ValueError):bist_symbol(value)
 def test_exact_protocol_invalid_symbol_not_all_api_errors(self):
  self.assertEqual(describe(APIError("TradingView error: ['cs_123', 'ser_1', 'invalid symbol']"))['code'],'PROVIDER_UNSUPPORTED')
  for text in ('No data received','network error','user text invalid symbol'):
   self.assertEqual(describe(APIError(text))['code'],'PROVIDER_API_ERROR')
 def test_history_gets_canonical_symbol(self):
  import bist_bot
  with patch.object(bist_bot.bp,'Ticker') as ticker:
   ticker.return_value.history.return_value=None
   self.assertIsNone(bist_bot.hisse_analiz_hesapla('BIST:THYAO.IS'))
  ticker.assert_called_once_with('THYAO')
 def response(self,chunks,length=None):
  class Response:
   encoding='utf-8';is_redirect=False;status_code=200
   headers={'Content-Type':'text/html'}
   def __enter__(self):return self
   def __exit__(self,*args):self.closed=True
   def raise_for_status(self):pass
   def iter_content(self,size):
    for part in chunks:self.reads+=1;yield part
  response=Response();response.reads=0;response.closed=False
  if length is not None:response.headers=dict(response.headers,**{'Content-Length':str(length)})
  return response
 def read(self,response):
  with patch('sirket_site_motoru.socket.getaddrinfo',return_value=[(0,0,0,'',('8.8.8.8',443))]),patch('sirket_site_motoru.requests.get',return_value=response):
   return SirketSiteMotoru.read_page('https://example.com/')
 def test_large_declared_response_not_downloaded(self):
  response=self.response([b'unread'],MAX_RESPONSE_BYTES+1)
  with self.assertRaises(ResponseLimitError) as error:self.read(response)
  self.assertEqual(response.reads,0);self.assertTrue(response.closed);self.assertEqual(describe(error.exception)['code'],'SOURCE_RESPONSE_TOO_LARGE')
 def test_chunked_response_stops_at_cap_and_closes(self):
  response=self.response([b'a'*8192]*100)
  with self.assertRaises(ResponseLimitError):self.read(response)
  self.assertLess(response.reads,100);self.assertTrue(response.closed)
 def test_response_exactly_at_cap_is_read(self):
  response=self.response([b'a'*MAX_RESPONSE_BYTES]);self.assertEqual(len(self.read(response)['text']),MAX_RESPONSE_BYTES)

# Reuse only temporary-data setup helpers, not inherited test methods.
class PartialBatchBoundaryTests(unittest.TestCase):
 setUp=diagnostics.TaskDiagnosticsTests.setUp
 worker=diagnostics.TaskDiagnosticsTests.worker
 def test_unsupported_stock_does_not_discard_successful_full_scan(self):
  worker=self.worker();worker.symbols=['AAA','BBB'];worker.batch_size=2
  issue=describe(APIError("TradingView error: ['ser_1', 'invalid symbol']"))
  with patch.object(worker.bot,'DATA_FILE',str(self.location.public/'test_hisseler.json')),patch.object(worker,'scan_one',side_effect=[('AAA',None,issue),('BBB',{'sembol':'BBB'},None)]),patch.object(worker.bot,'web_verisi_kaydet') as write,patch.object(worker,'market_context'),patch.object(worker,'ai_context'):
   result=worker.full_scan()
  self.assertEqual(result['diagnostics']['unsupported'],1);self.assertEqual(result['diagnostics']['successful'],1)
  self.assertEqual(write.call_args.args[0][0]['sembol'],'BBB');self.assertEqual(worker.cursor,2);self.assertNotIn('AAA',worker.events)
 def test_priority_records_unsupported_but_processes_good_stock(self):
  worker=self.worker();worker.enqueue('AAA');worker.enqueue('BBB')
  with patch.object(worker,'original_priority',side_effect=[APIError("TradingView error: ['ser_1', 'invalid symbol']"),{'sembol':'BBB'}]),patch.object(worker,'ai_context'):
   result=worker.priority()
  self.assertEqual(result['diagnostics']['unsupported'],1);self.assertEqual(result['diagnostics']['successful'],1)
  self.assertNotIn('AAA',worker.events);self.assertNotIn('BBB',worker.events)

import test_sirket_site_motoru as company_tests
class CompanyBoundaryRoundTests(unittest.TestCase):
 setUp=company_tests.CompanyMonitorTests.setUp
 rss=company_tests.CompanyMonitorTests.rss
 fetch=company_tests.CompanyMonitorTests.fetch
 monitor=company_tests.CompanyMonitorTests.monitor
 def test_large_site_backoff_keeps_next_site_running(self):
  self.mapping.write_text(json.dumps({'hisseler':{'AAA':{'siteler':['https://a.example/']},'BBB':{'siteler':['https://b.example/']}}}))
  self.fixture['https://a.example/']=ResponseLimitError('Yanıt boyutu sınırı')
  self.fixture['https://b.example/robots.txt']='User-agent: *\nAllow: /'
  monitor=self.monitor(batch_size=2,min_interval=0)
  monitor.tek_tur()
  state=json.loads(monitor.path.read_text())
  self.assertEqual(monitor.last_round_issue['code'],'SOURCE_RESPONSE_TOO_LARGE')
  self.assertEqual(state['sites']['AAA']['status'],'BACKOFF')
  self.assertEqual(state['sites']['BBB']['status'],'OK')

 def test_tls_site_does_not_stop_other_company_and_keeps_certificate_checks(self):
  import requests
  self.mapping.write_text(json.dumps({'hisseler':{'AAA':{'siteler':['https://a.example/']},'BBB':{'siteler':['https://b.example/']}}}))
  self.fixture['https://a.example/']=requests.exceptions.SSLError('unable to get local issuer certificate')
  self.fixture['https://b.example/robots.txt']='User-agent: *\nAllow: /'
  monitor=self.monitor(batch_size=2,min_interval=0);monitor.tek_tur()
  state=json.loads(monitor.path.read_text());self.assertEqual(state['sites']['BBB']['status'],'OK')
  self.assertEqual(monitor.last_round_issue['code'],'NETWORK_TLS');self.assertEqual(monitor.last_round_details['successful'],1)
  with patch('sirket_site_motoru.socket.getaddrinfo',return_value=[(0,0,0,'',('8.8.8.8',443))]),patch('sirket_site_motoru.requests.get',side_effect=requests.exceptions.SSLError()) as request:
   with self.assertRaises(requests.exceptions.SSLError):SirketSiteMotoru.read_page('https://example.com/')
  self.assertIs(request.call_args.kwargs['verify'],True)

class EquityUniverseTests(unittest.TestCase):
 def test_official_equity_components_not_untyped_companies(self):
  import bist_bot
  with patch('pay_evreni.symbols',return_value=['GARAN','THYAO']) as source,patch.object(bist_bot.bp,'companies') as issuers:
   self.assertEqual(bist_bot.bist_hisseleri_getir(),['GARAN','THYAO'])
   source.assert_called_once();issuers.assert_not_called()
 def test_equity_source_failure_does_not_fall_back_to_issuer_list(self):
  import bist_bot
  with patch('pay_evreni.symbols',return_value=[]) as source,patch.object(bist_bot.bp,'companies') as issuers:
   self.assertEqual(bist_bot.bist_hisseleri_getir(),[]);issuers.assert_not_called()

class SkipIsolationTests(unittest.TestCase):
 setUp=diagnostics.TaskDiagnosticsTests.setUp
 worker=diagnostics.TaskDiagnosticsTests.worker
 fail_task=diagnostics.TaskDiagnosticsTests.fail_task
 def test_many_unsupported_priority_entries_are_recorded_not_retried(self):
  worker=self.worker()
  for stock in ('AAA','BBB','CCC'):worker.enqueue(stock)
  with patch.object(worker,'original_priority',side_effect=APIError("TradingView error: ['ser_1', 'invalid symbol']")) as provider:
   report=worker.priority();self.assertEqual(report['diagnostics']['unsupported'],3);self.assertEqual(len(worker.events),0)
   worker.priority();self.assertEqual(provider.call_count,3)
  saved=json.loads((self.location.runtime/'provider_unsupported.json').read_text());self.assertEqual(set(saved),{'AAA','BBB','CCC'})
 def test_priority_non_equity_is_skipped_before_history(self):
  worker=self.worker();worker.symbols=[];worker.enqueue('ADBNK')
  with patch.object(worker,'original_priority') as provider:result=worker.priority()
  provider.assert_not_called();self.assertEqual(result['diagnostics']['skipped'],1)
  self.assertEqual(result['diagnostics']['reasons'][0]['code'],'OUTSIDE_EQUITY_UNIVERSE')
 def test_all_unsupported_full_scan_advances_without_outage_or_empty_write(self):
  worker=self.worker();worker.symbols=['AAA','BBB'];worker.batch_size=2
  issue=describe(APIError("TradingView error: ['ser_1', 'invalid symbol']"))
  with patch.object(worker,'scan_one',side_effect=[('AAA',None,issue),('BBB',None,issue)]),patch.object(worker.bot,'web_verisi_kaydet') as writer:
   result=worker.full_scan()
  writer.assert_not_called();self.assertEqual(worker.cursor,2);self.assertEqual(result['diagnostics']['unsupported'],2);self.assertFalse(worker.events)
 def test_real_outage_is_still_a_task_issue(self):
  worker=self.worker();worker.enqueue('AAA')
  with patch.object(worker,'original_priority',side_effect=APIError('upstream request failed')):
   with self.assertRaises(TaskIssue) as error:worker.priority()
  self.assertEqual(error.exception.issue['code'],'PROVIDER_API_ERROR');self.assertIn('AAA',worker.events)
 def test_isolated_company_tls_is_degraded_without_global_900_second_pause(self):
  motor=self.fail_task(TaskIssue({'code':'NETWORK_TLS'},completed=2),name='company_site');motor.stop.set()
  self.assertEqual(motor.state['tasks']['company_site']['status'],'DEGRADED')
  self.assertEqual(motor.state['tasks']['company_site']['retry_in_seconds'],30)
 def test_systemwide_tls_outage_remains_error(self):
  motor=self.fail_task(TaskIssue({'code':'NETWORK_TLS'}),name='company_site');motor.stop.set()
  self.assertEqual(motor.state['tasks']['company_site']['status'],'ERROR');self.assertEqual(motor.state['tasks']['company_site']['retry_in_seconds'],900)

 def test_skips_remain_visible_in_health_without_failure_backoff(self):
  motor=self.fail_task(TaskIssue({'code':'PROVIDER_API_ERROR'}),name='priority');motor.stop.set()
  result={'diagnostics':{'processed':2,'successful':1,'skipped':1,'unsupported':1,'failed':0,'reasons':[{'symbol':'AAA','code':'PROVIDER_UNSUPPORTED','message':'private data'}]}}
  future=diagnostics.Future();future.set_result(result);motor.tasks['priority'].future=future;motor.tick()
  task=motor.state['tasks']['priority'];self.assertEqual(task['status'],'OK_WITH_SKIPS');self.assertEqual(motor.tasks['priority'].failures,0)
  with patch('ana_motor.istanbul_now',return_value=self.now):health=diagnostics.health_snapshot(self.location.runtime)
  self.assertEqual(health['tasks']['priority']['diagnostics']['unsupported'],1);self.assertNotIn('private data',json.dumps(health))
  self.assertEqual(health['tasks']['priority']['diagnostics']['reasons'][0]['reason']['code'],'PROVIDER_UNSUPPORTED')

 def test_company_adapter_counts_sites_not_only_news_events(self):
  worker=self.worker();worker.company=diagnostics.Mock()
  worker.company.tek_tur.return_value=0
  worker.company.last_round_issue=describe(__import__('requests').exceptions.SSLError())
  worker.company.last_round_details={'processed':2,'successful':1,'skipped':0,'failed':1,'reasons':[{'symbol':'ICBCT','code':'NETWORK_TLS'}]}
  with self.assertRaises(TaskIssue) as error:worker.company_site()
  self.assertEqual(error.exception.completed,1);self.assertEqual(error.exception.details['failed'],1)
