import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock,patch
import pandas as pd
import pay_evreni as universe
import tarama_verisi as cache

class UniverseTests(unittest.TestCase):
 def setUp(self):
  self.groups=json.loads(Path(universe.__file__).with_name('kap_pay_evreni.json').read_text())['groups']
 def test_verified_count_and_classes(self):
  codes=universe.validate(self.groups)
  self.assertEqual(len(codes),631)
  self.assertTrue({'KRDMA','KRDMB','KRDMD','ISATR','ISBTR','ISCTR','ISKUR'}<=set(codes))
  self.assertFalse({'KTEST','DMLKT','DRPHN','ADBNK'}&set(codes))
 def test_incomplete_rejected(self):
  with self.assertRaises(ValueError):universe.validate(self.groups[:-1])
 def test_duplicate_rejected(self):
  groups=copy.deepcopy(self.groups);groups[0]['content'].append(groups[0]['content'][0])
  with self.assertRaises(ValueError):universe.validate(groups)
 def test_fund_rejected(self):
  groups=copy.deepcopy(self.groups);groups[0]['content'][0]['fundOid']='fund'
  with self.assertRaises(ValueError):universe.validate(groups)
 def test_failure_retains_verified(self):
  with patch('requests.get',side_effect=OSError('offline')):
   before=universe.symbols(False);self.assertFalse(universe.refresh());self.assertEqual(before,universe.symbols(False))
 def test_page_parser(self):
  groups=[dict(g['metadata'],marketDetailContentList=g['content']) for g in self.groups]
  payload='1:'+json.dumps({'groups':groups})+'\n'
  page='<script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
  self.assertEqual(len(universe.parse_page(page)),631)
 def test_daily_singleflight(self):
  with patch.object(universe,'_attempt_day',None),patch.object(universe,'_refreshing',False),patch('threading.Thread') as thread:
   for _ in range(10):universe.symbols()
   thread.assert_called_once()
 def test_oversize_retains(self):
  response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
  response.iter_content.return_value=[b'x'*(universe.MAX_BYTES+1)]
  with patch('requests.get',return_value=response):self.assertFalse(universe.refresh())

class ScanCacheTests(unittest.TestCase):
 def setUp(self):
  cache._cache.clear();cache._locks.clear()
 def test_concurrent_single_query_and_copy(self):
  ticker=Mock();ticker.history.return_value=pd.DataFrame({'Close':[1,2]})
  with ThreadPoolExecutor(max_workers=8) as pool:
   rows=list(pool.map(lambda _:cache.history(ticker,'THYAO','6mo'),range(8)))
  self.assertEqual(ticker.history.call_count,1)
  rows[0].iloc[0,0]=999;self.assertEqual(rows[1].iloc[0,0],1)
 def test_manual_unlisted_allowed(self):
  ticker=Mock();ticker.history.return_value=pd.DataFrame({'Close':[1]})
  self.assertIsNotNone(cache.history(ticker,'DMLKT','6mo'))
 def test_expiry_and_period(self):
  ticker=Mock();ticker.history.return_value=pd.DataFrame({'Close':[1]})
  with patch.object(cache,'monotonic',side_effect=[0,2,2,2]):
   cache.history(ticker,'THYAO','6mo');cache.history(ticker,'THYAO','6mo')
  self.assertEqual(ticker.history.call_count,2)
 def test_errors_not_cached(self):
  ticker=Mock();ticker.history.side_effect=OSError('source')
  for _ in range(2):
   with self.assertRaises(OSError):cache.history(ticker,'THYAO','6mo')
  self.assertEqual(ticker.history.call_count,2)
