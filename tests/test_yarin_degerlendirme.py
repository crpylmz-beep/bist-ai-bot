import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from yarin_degerlendirme import attach_new, schedule, due
from tests import test_yarin_snapshot as fixtures

IST=ZoneInfo('Europe/Istanbul')


class DatedEvaluationTests(unittest.TestCase):
    def snapshot(self):
        return {'analiz_tarihi':'2026-10-06','tahmin_zamani':'2026-10-06T19:00:00+03:00',
            'top10':[{'sembol':'THYAO','calibration_version':'BASE','learning_version':'LEARN_V1',
                'teknik_gostergeler':{'data_time':'2026-10-06T18:00:00+03:00'},
                'tahmin':{'fiyat':100,'hedef':105,'stop':98},'hedef1':900,'stop':10}]}

    def test_fields_frozen_dedupe_and_bounded_no_files(self):
        snapshot=self.snapshot()
        with patch('builtins.open',side_effect=AssertionError('no files')):
            attach_new(snapshot)
        row=snapshot['top10'][0];value=snapshot['dated_evaluations']['records'][row['evaluation_id']]
        self.assertEqual((value['reference_price'],value['daily_target'],value['daily_stop']),(100,105,98))
        self.assertEqual(value['evaluation_dates'],{'1':'2026-10-07','3':'2026-10-09','5':'2026-10-13'})
        self.assertTrue(value['signal_time'].endswith('+03:00'));self.assertIn('LEARN_V1',value['model_version'])
        before=copy.deepcopy(snapshot);attach_new(snapshot);self.assertEqual(snapshot,before)
        snapshot['top10'].append(copy.deepcopy(row));attach_new(snapshot)
        self.assertEqual(len(snapshot['dated_evaluations']['records']),1)
        self.assertLess(len(json.dumps(snapshot['dated_evaluations'])),1000)

    def test_missing_daily_levels_no_generic_backfill(self):
        snapshot=self.snapshot();snapshot['top10'][0]['tahmin']={'fiyat':100}
        attach_new(snapshot);value=next(iter(snapshot['dated_evaluations']['records'].values()))
        self.assertIsNone(value['daily_target']);self.assertIsNone(value['daily_stop'])
        self.assertEqual(value['status'],'MISSING_LEVELS');self.assertEqual(due(value,'2026-11-01T19:00:00+03:00'),[])

    def test_calendar_weekend_holiday_and_before_open(self):
        dates,_=schedule(datetime(2026,10,4,21,tzinfo=IST));self.assertEqual(dates['1'],'2026-10-05')
        dates,_=schedule(datetime(2026,10,6,0,16,tzinfo=IST));self.assertEqual(dates['1'],'2026-10-06')
        dates,_=schedule(datetime(2026,10,28,19,tzinfo=IST));self.assertEqual(dates['1'],'2026-10-30')
        self.assertEqual(dates['3'],'2026-11-03')

    def test_due_only_completed_sessions_no_snapshot_mutation(self):
        snapshot=self.snapshot();attach_new(snapshot);value=next(iter(snapshot['dated_evaluations']['records'].values()))
        before=copy.deepcopy(snapshot)
        self.assertEqual(due(value,'2026-10-09T14:00:00+03:00'),[1])
        self.assertEqual(due(value,'2026-10-09T18:15:00+03:00'),[1,3])
        self.assertEqual(snapshot,before)

    def test_future_or_unknown_reference_not_evaluable(self):
        for data in (None,'2026-10-07T18:00:00+03:00'):
            snapshot=self.snapshot();snapshot['top10'][0]['teknik_gostergeler']['data_time']=data
            attach_new(snapshot);value=next(iter(snapshot['dated_evaluations']['records'].values()))
            self.assertNotEqual(value['status'],'READY');self.assertEqual(due(value,'2026-11-01T19:00:00+03:00'),[])

    def test_conflicting_duplicate_never_overwrites(self):
        snapshot=self.snapshot();other=copy.deepcopy(snapshot['top10'][0]);other['tahmin']['fiyat']=101
        snapshot['top10'].append(other)
        with self.assertRaises(ValueError):attach_new(snapshot)

    def test_no_outcomes_or_live_fields_used(self):
        first=self.snapshot();second=self.snapshot()
        second['top10'][0].update(sonuc_1g={'getiri':9999},canli_fiyat=99999)
        attach_new(first);attach_new(second)
        self.assertEqual(first['dated_evaluations'],second['dated_evaluations'])

    def test_requires_aware_time_and_top10_limit(self):
        snapshot=self.snapshot();snapshot['tahmin_zamani']='2026-10-06T19:00:00'
        with self.assertRaises(ValueError):attach_new(snapshot)
        snapshot=self.snapshot();snapshot['top10']*=11
        with self.assertRaises(ValueError):attach_new(snapshot)

    def test_real_writer_freezes_metadata_and_same_day_does_not_rewrite(self):
        case=fixtures.SnapshotTests(methodName='test_snapshot_fields_and_same_day_no_overwrite')
        case.setUp();self.addCleanup(case.doCleanups)
        sample=copy.deepcopy(case.sample)
        sample['teknik_gostergeler']={'data_time':'2026-10-06T18:00:00+03:00'}
        first=case.save(sample);archived=case.archive/'2026-10-06.json'
        before=archived.read_bytes();mtime=archived.stat().st_mtime_ns
        self.assertIn('dated_evaluations',first)
        record=next(iter(first['dated_evaluations']['records'].values()))
        self.assertEqual(record['status'],'READY');self.assertEqual(record['daily_target'],300)
        case.save(dict(sample,fiyat=999,ai_yarin_hedef=2000))
        self.assertEqual(archived.read_bytes(),before);self.assertEqual(archived.stat().st_mtime_ns,mtime)

    def test_legacy_conversion_never_backfills_evaluations(self):
        import bist_bot
        legacy={'analiz_tarihi':'2026-10-05','olusturma_zamani':'2026-10-05 19:00:00','top10':[{'sembol':'THYAO','fiyat':100,'hedef1':105,'stop':98}]}
        before=copy.deepcopy(legacy)
        with patch('yarin_degerlendirme.attach_new',side_effect=AssertionError('no legacy enrichment')):
            result=bist_bot.yarin_snapshot_modeli(legacy)
        self.assertNotIn('dated_evaluations',result);self.assertEqual(legacy,before)
