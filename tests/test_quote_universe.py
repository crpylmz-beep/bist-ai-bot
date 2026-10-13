import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock,patch
import pandas as pd
import pay_evreni as universe

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

