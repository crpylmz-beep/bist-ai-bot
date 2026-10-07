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
   with self.assertRaises(TaskIssue) as error:worker.full_scan()
  self.assertEqual(error.exception.issue['code'],'PROVIDER_UNSUPPORTED');self.assertEqual(error.exception.completed,1)
  self.assertEqual(write.call_args.args[0][0]['sembol'],'BBB');self.assertEqual(worker.cursor,2);self.assertIn('AAA',worker.events)
 def test_priority_keeps_bad_stock_but_processes_good_stock(self):
  worker=self.worker();worker.enqueue('AAA');worker.enqueue('BBB')
  with patch.object(worker,'original_priority',side_effect=[APIError("TradingView error: ['ser_1', 'invalid symbol']"),{'sembol':'BBB'}]),patch.object(worker,'ai_context'):
   with self.assertRaises(TaskIssue) as error:worker.priority()
  self.assertEqual(error.exception.issue['code'],'PROVIDER_UNSUPPORTED');self.assertEqual(error.exception.completed,1)
  self.assertIn('AAA',worker.events);self.assertNotIn('BBB',worker.events)

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
