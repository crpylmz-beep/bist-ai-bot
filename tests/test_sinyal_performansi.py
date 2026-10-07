import copy
import json
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ai_karar_motoru import HORIZONS, ISTANBUL
from performans_motoru import outcome, sessions_after
from sinyal_performansi import aggregate, clean_dataset, quality, reliability, publish, read_report
from veri_yollari import DataPaths


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 10, 2, 18, 30, tzinfo=ISTANBUL)
        self.days = sessions_after(self.at.date(), 60, lambda day: False)
        self.now = datetime.combine(self.days[-1], datetime.min.time(), ISTANBUL).replace(hour=19)
        self.holiday = lambda day: False
        self.row = {'id': 'one', 'sembol': 'THYAO', 'tarih': self.at.isoformat(),
                    'sinyal': 'AGRESIF_ALIS', 'karar': 'AL', 'fiyat': 100,
                    'hedef1': 120, 'stop': 80, 'teknik_skor': 85, 'guven': 75,
                    'rsi': 55, 'macd': 2, 'signal': 1, 'hacim_orani': 180,
                    'sma20': 110, 'sma50': 100, 'performance_source': 'LIVE'}
        bars = [{'date': day.isoformat(), 'open': 100, 'close': 105, 'high': 110, 'low': 90, 'complete': True} for day in self.days]
        for h in HORIZONS:
            self.row[f'sonuc_{h}g'] = outcome(self.row, bars, h, self.now, self.holiday)
    def report(self, rows=None): return aggregate(rows or [self.row], self.now, self.holiday)
    def stats(self, rows=None, h=1): return self.report(rows)['periods']['ALL']['overall']['ALL'][str(h)]
    def short(self):
        row = copy.deepcopy(self.row); row.update(id='two', sembol='ASELS', karar='SAT', sinyal='AGRESIF_SATIS', hedef1=80, stop=120)
        for h in HORIZONS:
            row[f'sonuc_{h}g'].update(fiyat=95, getiri_yuzde=-5, yon_getirisi=5)
        return row
    def test_all_six_horizon_aggregations(self):
        for h in HORIZONS:
            with self.subTest(horizon=h):
                stat = self.stats(h=h); self.assertEqual(stat['completed'], 1); self.assertEqual(stat['mean_return'], 5)
    def test_upward_success(self): self.assertEqual(self.stats()['success_rate'], 1)
    def test_downward_success_and_raw_return_separated(self):
        stat = self.stats([self.short()]); self.assertEqual(stat['success_rate'], 1)
        self.assertEqual(stat['mean_return'], 5); self.assertEqual(stat['mean_raw_price_return'], -5)
    def test_pending_not_failure(self):
        row = copy.deepcopy(self.row); row['sonuc_1g'] = None
        stat = self.stats([row]); self.assertEqual(stat['pending'], 1); self.assertEqual(stat['completed'], 0); self.assertIsNone(stat['success_rate'])
    def test_legacy_unverified_not_repaired(self):
        row = copy.deepcopy(self.row); del row['sonuc_1g']['degerlendirme_tamamlandi']
        stat = self.stats([row]); self.assertEqual(stat['excluded'], {'UNVERIFIED': 1}); self.assertEqual(stat['completed'], 0)
    def test_reliability_thresholds(self):
        for n, expected in ((0,'INSUFFICIENT'),(2,'INSUFFICIENT'),(29,'INSUFFICIENT'),(30,'LOW'),(99,'LOW'),(100,'MEDIUM'),(299,'MEDIUM'),(300,'HIGH')):
            self.assertEqual(reliability(n), expected)
        self.assertFalse(self.stats()['sufficient'])
    def test_mean_median_best_worst_and_negative_results(self):
        loser = copy.deepcopy(self.row); loser.update(id='loser', sembol='OTHER')
        for h in HORIZONS: loser[f'sonuc_{h}g'].update(fiyat=90, getiri_yuzde=-10, yon_getirisi=-10)
        stat = self.stats([self.row, loser]); self.assertEqual(stat['mean_return'], -2.5); self.assertEqual(stat['median_return'], -2.5)
        self.assertEqual(stat['best_return'],5); self.assertEqual(stat['worst_return'],-10)
        self.assertEqual(stat['payoff_ratio'],.5); self.assertEqual(stat['profit_factor'],.5)
    def test_mfe_mae_and_sample_sizes(self):
        stat = self.stats(); self.assertEqual(stat['mean_mfe'],10); self.assertEqual(stat['mean_mae'],-10); self.assertEqual(stat['mfe_samples'],1)
    def test_missing_excursions_not_zero(self):
        row = copy.deepcopy(self.row); row['sonuc_1g']['mfe_pct'] = None
        stat = self.stats([row]); self.assertIsNone(stat['mean_mfe']); self.assertEqual(stat['mfe_samples'],0)
    def test_score_bands_and_signal_groups(self):
        report = self.report()['periods']['ALL']; self.assertIn('80-89',report['scores']); self.assertIn('AGRESIF_ALIS',report['signals'])
        self.assertEqual(report['scores']['80-89']['1']['completed'],1)
    def test_time_filter_uses_signal_date(self):
        report = self.report(); self.assertNotIn('7', report['periods']); self.assertNotIn('30',report['periods']); self.assertIn('90',report['periods'])
    def test_duplicate_ids_and_identical_imports_not_inflate(self):
        duplicate = copy.deepcopy(self.row); duplicate['id'] = 'another-import-id'
        report = self.report([self.row, self.row, duplicate]); self.assertEqual(report['duplicates'],2)
        self.assertEqual(report['periods']['ALL']['overall']['ALL']['1']['sample_size'],1)
    def test_future_feature_timestamp_excluded(self):
        row = copy.deepcopy(self.row); row['criteria_snapshot'] = {'captured_at':(self.at+timedelta(days=1)).isoformat()}
        self.assertEqual(self.stats([row])['excluded'],{'FUTURE_FEATURES':1})
    def test_future_outcome_excluded(self):
        row = copy.deepcopy(self.row); row['sonuc_1g']['observed_at'] = (self.now+timedelta(days=1)).isoformat()
        self.assertEqual(self.stats([row])['completed'],0)
    def test_missing_base_or_target_excluded(self):
        for key, reason in (('fiyat','MISSING_BASE_PRICE'),('hedef1','MISSING_TARGET_PRICE')):
            row = copy.deepcopy(self.row); row[key] = None
            self.assertEqual(self.stats([row])['excluded'],{reason:1})
    def test_learning_features_do_not_contain_outcomes(self):
        original = copy.deepcopy(self.row); rows = list(clean_dataset([self.row], self.now, self.holiday))
        self.assertEqual(len(rows),6); self.assertEqual(self.row,original)
        for row in rows:
            self.assertNotIn('mfe_pct',row['features']); self.assertNotIn('sonuc_60g',row['features']); self.assertEqual(row['features']['rsi'],55)
    def test_later_result_does_not_change_short_horizon(self):
        before = self.stats(); row = copy.deepcopy(self.row); row['sonuc_60g'].update(fiyat=99999,getiri_yuzde=99999)
        self.assertEqual(self.stats([row]), before)
    def test_frozen_criteria_only(self):
        report = self.report()['periods']['ALL']['criteria']; self.assertIn('RSI:50-69',report); self.assertIn('MACD:USTUNDE',report)
        self.assertFalse(any('OBV' in key.upper() for key in report))
    def test_overbought_is_not_invented_sell_signal(self):
        row = copy.deepcopy(self.row); row.update(sinyal='ASIRI_ALIM',karar=None)
        self.assertEqual(self.stats([row])['excluded'],{'UNKNOWN_DIRECTION':1})
    def test_malformed_record_reported(self):
        row = copy.deepcopy(self.row); row['kriterler'] = ['invalid']
        self.assertEqual(self.stats([row])['excluded'],{'MALFORMED':1})
    def test_invalid_session_or_return_excluded(self):
        row = copy.deepcopy(self.row); row['sonuc_1g']['getiri_yuzde']=42
        self.assertEqual(self.stats([row])['excluded'],{'BASE_OR_RETURN_MISMATCH':1})
        row['sonuc_1g']['tarih']='2026-10-06'; self.assertEqual(quality(row,1,self.now,self.holiday),'INVALID_SESSION_DATE')
    def test_conflicting_duplicates_excluded_from_dataset_and_statistics(self):
        other = copy.deepcopy(self.row); other['sonuc_1g'].update(fiyat=90,getiri_yuzde=-10)
        stat = self.stats([self.row,other]); self.assertEqual(stat['completed'],0)
        self.assertEqual(stat['excluded'],{'DUPLICATE_CONFLICT':1})
        self.assertEqual(list(clean_dataset([self.row,other],self.now,self.holiday)),[])
    def test_excursions_with_wrong_direction_not_used_in_learning(self):
        row=self.short();row['sonuc_1g']['yon_getirisi']=-5
        stat=self.stats([row]);self.assertEqual(stat['mean_return'],5);self.assertIsNone(stat['mean_mfe'])
        example=next(clean_dataset([row],self.now,self.holiday));self.assertIsNone(example['outcome']['mfe_pct'])
    def test_future_timestamp_inside_frozen_inputs_excluded(self):
        row=copy.deepcopy(self.row);row['kriterler']={'rsi':55,'captured_at':(self.at+timedelta(days=1)).isoformat()}
        self.assertEqual(self.stats([row])['excluded'],{'FUTURE_FEATURES':1})
    def test_empty_report_and_unavailable_optional_ratios(self):
        self.assertEqual(aggregate([],self.now)['periods'],{})
        stat=self.stats();self.assertIsNone(stat['profit_factor']);self.assertIsNone(stat['payoff_ratio'])
    def test_malformed_outcome_metadata_is_excluded_without_crash(self):
        row=copy.deepcopy(self.row);row['sonuc_1g']['kalite_uyarilari']={'bad':'format'}
        self.assertEqual(self.stats([row])['excluded'],{'MALFORMED_RESULT':1})
        row['sembol']={'bad':'format'};self.assertEqual(self.stats([row])['excluded'],{'MALFORMED':1})
    def test_atomic_publish_restart_and_http_api_preserve_history(self):
        from kullanici_kayitlari import atomic_json
        from web_server import create_server
        with tempfile.TemporaryDirectory() as directory:
            location = DataPaths({'BIST_DATA_DIR':directory}); location.ensure()
            source = location.runtime_file('tahmin_gecmisi.json'); atomic_json(source, {'tahminler':[self.row]}); before=source.read_bytes()
            publish(location,[self.row],self.now); cached=read_report(location)
            self.assertEqual(cached,read_report(DataPaths({'BIST_DATA_DIR':directory})))
            with patch('kullanici_kayitlari.os.replace',side_effect=OSError('write failed')):
                with self.assertRaises(OSError): publish(location,[],self.now)
            self.assertEqual(read_report(location),cached); self.assertEqual(source.read_bytes(),before)
            server=create_server('127.0.0.1',0,data_paths=location)
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/signal-performance') as response:
                    self.assertEqual(json.load(response),cached)
            finally: server.shutdown(); server.server_close(); thread.join()
