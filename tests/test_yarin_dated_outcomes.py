import copy
import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock
from veri_yollari import DataPaths
from yarin_degerlendirme import IST, attach_new, evaluate, evaluate_round


class OutcomesTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = attach_new({'tahmin_zamani':'2026-10-06T19:00:00+03:00',
            'analiz_tarihi':'2026-10-06','top10':[{'sembol':'AAA','tahmin':{'fiyat':100,'hedef':105,'stop':95},
            'teknik_gostergeler':{'data_time':'2026-10-06T18:00:00+03:00'}}]})
        self.value = next(iter(self.snapshot['dated_evaluations']['records'].values()))
        self.bars = [dict(timestamp=d,open=100,high=106,low=94,close=102)
                     for d in ('2026-10-07','2026-10-08','2026-10-09','2026-10-12','2026-10-13')]
        self.now = datetime(2026,10,13,20,tzinfo=IST)

    def test_horizons_and_ambiguity(self):
        for h in (1,3,5):
            out=evaluate(self.value,self.bars,h,self.now)
            self.assertAlmostEqual(out['return_pct'],2)
            self.assertAlmostEqual(out['mae_pct'],-6)
            self.assertTrue(out['hit']);self.assertTrue(out['target_hit']);self.assertTrue(out['stop_hit'])
            self.assertEqual(out['target_stop_order'],'UNKNOWN_SAME_BAR')

    def test_no_future_or_incomplete(self):
        early=datetime(2026,10,7,17,tzinfo=IST)
        self.assertIsNone(evaluate(self.value,self.bars,1,early))
        self.assertIsNone(evaluate(self.value,self.bars,3,datetime(2026,10,8,20,tzinfo=IST)))
        before=evaluate(self.value,self.bars,1,self.now)
        self.bars[-1].update(high=10000,low=1,close=200)
        self.assertEqual(before,evaluate(self.value,self.bars,1,self.now))

    def test_missing_and_invalid_bars(self):
        self.assertIsNone(evaluate(self.value,self.bars[:2],3,self.now))
        self.bars[0]['low']=110
        self.assertIsNone(evaluate(self.value,self.bars,1,self.now))

    def test_order(self):
        self.bars[0].update(high=104,low=94)
        self.bars[1].update(high=106,low=96)
        self.assertEqual(evaluate(self.value,self.bars,3,self.now)['target_stop_order'],'STOP_FIRST')
        self.bars[0].update(high=106,low=96)
        self.bars[1].update(high=104,low=94)
        self.assertEqual(evaluate(self.value,self.bars,3,self.now)['target_stop_order'],'TARGET_FIRST')

    def location(self, root):
        location=DataPaths(repo_root=root)
        location.archives.mkdir(parents=True)
        return location

    def test_durable_dedupe_and_preservation(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as root:
            location=self.location(root)
            archive=location.archives/'2026-10-06.json'
            archive.write_text(json.dumps(self.snapshot))
            old=location.archives/'old.json';old.write_text('{"top10":[]}')
            original=archive.read_bytes();legacy=old.read_bytes()
            provider=Mock(return_value=self.bars)
            self.assertEqual(evaluate_round(location,provider,self.now)['completed'],3)
            self.assertEqual(evaluate_round(location,provider,self.now)['completed'],0)
            self.assertEqual(provider.call_count,1)
            with closing(sqlite3.connect(location.runtime_file('yarin_dated_outcomes.sqlite3'))) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0],3)
            self.assertEqual(archive.read_bytes(),original);self.assertEqual(old.read_bytes(),legacy)

    def test_provider_error_isolated_and_retry(self):
        with tempfile.TemporaryDirectory() as root:
            location=self.location(root)
            other=copy.deepcopy(self.value);other['symbol']='BBB'
            self.snapshot['dated_evaluations']['records']['other']=other
            (location.archives/'new.json').write_text(json.dumps(self.snapshot))
            def provider(symbol):
                if symbol=='AAA':raise ConnectionError('offline')
                return self.bars
            with self.assertRaises(ConnectionError):evaluate_round(location,provider,self.now)
            # Success survives failure; failed symbol cooldown cannot starve later work.
            self.assertEqual(evaluate_round(location,Mock(side_effect=AssertionError()),self.now)['completed'],0)

    def test_unknown_reference_skips(self):
        self.value['status']='REFERENCE_TIME_UNKNOWN'
        self.assertIsNone(evaluate(self.value,self.bars,1,self.now))
