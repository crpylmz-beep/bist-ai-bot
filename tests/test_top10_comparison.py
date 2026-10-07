import copy
import json
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from unittest.mock import patch

from ai_karar_motoru import HORIZONS, ISTANBUL
from performans_motoru import sessions_after, outcome
from veri_yollari import DataPaths
from kullanici_kayitlari import RecordError, atomic_json
import top10_ogrenme_performansi as module


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 10, 2, 18, 30, tzinfo=ISTANBUL)
        self.holiday = lambda day: False
        self.days = sessions_after(self.at.date(), 60, self.holiday)
        self.now = datetime.combine(self.days[-1], datetime.min.time(), ISTANBUL).replace(hour=19)
        self.rows = []
        for name, model in module.MODELS.items():
            for rank in range(1, 11):
                row = {'kayit_id': name + str(rank), 'sembol': 'S' + str(rank), 'zaman': self.at.isoformat(),
                       'snapshot_id': 'day_one', 'model': model, 'kaynak': 'IMMUTABLE_YARIN_SNAPSHOT',
                       'tahmin_sirasi': rank, 'base_rank': rank, 'learned_rank': rank, 'rank_change': 0,
                       'learning_adjustment': 0, 'learning_version': 'TOP10_INDICATOR_V1',
                       'fiyat': 100, 'hedef': 120, 'stop': 80, 'karar': 'AL'}
                bars = [{'date': day.isoformat(), 'open': 100, 'close': 100 + rank, 'high': 115,
                         'low': 90, 'complete': True} for day in self.days]
                for h in HORIZONS: row[f'sonuc_{h}g'] = outcome(row, bars, h, self.now, self.holiday)
                self.rows.append(row)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.paths = DataPaths({'BIST_DATA_DIR': self.temp.name}); self.paths.ensure()
    def report(self): return module.aggregate(self.rows, self.now, self.holiday)
    def first(self, h=1): return next(r for r in self.report()['recent_comparisons'] if r['horizon'] == h)
    def change_learned_order(self):
        for row in self.rows[10:]:
            rank = 11 - row['base_rank']; row.update(tahmin_sirasi=rank, learned_rank=rank, rank_change=row['base_rank']-rank)
    def enter(self):
        row = self.rows[-1]; row.update(sembol='NEW', base_rank=11, learned_rank=10, rank_change=1, learning_adjustment=1)
        for h in HORIZONS: row[f'sonuc_{h}g'].update(fiyat=115, getiri_yuzde=15, yon_getirisi=15)
        self.rows[9].update(learned_rank=11, rank_change=-1)
    def test_identical_lists_tie(self): self.assertEqual(self.first()['status'], 'TIE')
    def test_learned_better(self): self.enter(); self.assertEqual(self.first()['status'], 'LEARNED_BETTER')
    def test_base_better(self):
        self.enter()
        for h in HORIZONS: self.rows[-1][f'sonuc_{h}g'].update(fiyat=90, getiri_yuzde=-10, yon_getirisi=-10)
        self.assertEqual(self.first()['status'], 'BASE_BETTER')
    def test_missing_member_insufficient(self): self.rows.pop(); self.assertEqual(self.first()['status'], 'INSUFFICIENT')
    def test_all_six_horizons(self):
        for h in HORIZONS: self.assertEqual(self.first(h)['status'], 'TIE')
    def test_mean_median_best_worst(self):
        stat = self.first()['base']; self.assertEqual(stat['mean_return'], 5.5); self.assertEqual(stat['median_return'], 5.5)
        self.assertEqual(stat['best_return'], 10); self.assertEqual(stat['worst_return'], 1)
    def test_positive_and_success(self): self.assertEqual(self.first()['base']['positive_count'], 10); self.assertEqual(self.first()['base']['success_rate'], 1)
    def test_top3_top5_top10(self):
        self.change_learned_order(); result = self.first()
        self.assertEqual(result['base']['top3_return'], 2); self.assertEqual(result['base']['top5_return'], 3)
        self.assertEqual(result['learned']['top3_return'], 9); self.assertEqual(result['learned']['top5_return'], 8)
        self.assertEqual(result['differences']['top10_return'], 0)
    def test_mfe_mae_and_risk_metric(self):
        stat = self.first()['base']; self.assertEqual(stat['mean_mfe'], 15); self.assertEqual(stat['mean_mae'], -10)
        self.assertEqual(stat['return_to_adverse_excursion'], .55)
    def test_pending_exclusion(self): self.rows[0]['sonuc_1g'] = None; self.assertEqual(self.first()['excluded']['PENDING'], 1)
    def test_legacy_exclusion(self): self.rows[0]['legacy_unverified'] = True; self.assertIn('UNVERIFIED', self.first()['excluded'])
    def test_unverified_result(self): del self.rows[0]['sonuc_1g']['degerlendirme_tamamlandi']; self.assertIn('UNVERIFIED', self.first()['excluded'])
    def test_future_signal(self): self.rows[0]['zaman'] = (self.now + timedelta(days=1)).isoformat(); self.assertIn('FUTURE_SIGNAL', self.first()['excluded'])
    def test_future_observation(self): self.rows[0]['sonuc_1g']['observed_at'] = (self.now + timedelta(days=1)).isoformat(); self.assertIn('UNVERIFIED_TIME', self.first()['excluded'])
    def test_future_feature_lookahead(self): self.rows[0]['criteria_snapshot'] = {'asof': (self.at + timedelta(seconds=1)).isoformat()}; self.assertIn('FUTURE_FEATURES', self.first()['excluded'])
    def test_price_not_verified(self): self.rows[0]['sonuc_1g']['getiri_yuzde'] = 99; self.assertIn('BASE_OR_RETURN_MISMATCH', self.first()['excluded'])
    def test_wrong_session(self): self.rows[0]['sonuc_1g']['tarih'] = self.at.date().isoformat(); self.assertIn('INVALID_SESSION_DATE', self.first()['excluded'])
    def test_conflicting_duplicate(self):
        row = copy.deepcopy(self.rows[0]); row['base_score'] = 999; self.rows.append(row)
        self.assertIn('CONFLICTING_DUPLICATE', self.first()['excluded'])
    def test_exact_duplicate_not_inflate(self): self.rows.append(copy.deepcopy(self.rows[0])); self.assertEqual(self.first()['status'], 'TIE'); self.assertEqual(self.report()['duplicates'], 1)
    def test_rank_change(self): self.change_learned_order(); row = self.report()['rank_changes'][0]; self.assertNotEqual(row['rank_change'], 0); self.assertIsNotNone(row['returns']['1'])
    def test_enter_exit(self): self.enter(); rows = self.report()['rank_changes']; self.assertTrue(any(r['entered_top10'] for r in rows)); self.assertTrue(any(r['exited_top10'] for r in rows))
    def test_periods(self):
        report = self.report(); self.assertEqual(set(report['periods']), {'7d', '30d', '90d', 'all_time'})
        self.assertEqual(report['periods']['7d']['1']['completed_days'], 0); self.assertEqual(report['periods']['all_time']['1']['completed_days'], 1)
    def test_win_rate_insufficient_not_loss(self):
        self.rows[0]['sonuc_1g'] = None; stat = self.report()['summary']
        self.assertEqual(stat['completed_days'], 0); self.assertEqual(stat['insufficient_days'], 1); self.assertIsNone(stat['learned_win_rate'])
    def test_win_rate(self): self.enter(); self.assertEqual(self.report()['summary']['learned_win_rate'], 1)
    def test_snapshot_input_immutable(self): before = copy.deepcopy(self.rows); self.report(); self.assertEqual(before, self.rows)
    def test_d1_does_not_use_later_results(self):
        before = self.first(); self.rows[0]['sonuc_60g']['getiri_yuzde'] = 999; self.assertEqual(before, self.first())
    def test_weekend_and_holiday(self):
        days = sessions_after(self.at.date(), 3, lambda day: day.isoformat() == '2026-10-05')
        self.assertEqual([d.isoformat() for d in days], ['2026-10-06', '2026-10-07', '2026-10-08'])
    def test_no_calendar_day_shortcut(self): self.assertEqual(self.days[0].isoformat(), '2026-10-05')
    def test_bad_rank(self): self.rows[0]['tahmin_sirasi'] = 11; self.assertEqual(self.first()['status'], 'INSUFFICIENT')
    def test_mismatched_frozen_price(self): self.rows[0]['fiyat'] = 110; self.assertIn('INCONSISTENT_BASE_PRICE', self.first()['excluded'])
    def test_non_live(self): self.rows[10]['analysis_only'] = True; self.assertIn('NON_LIVE', self.first()['excluded'])
    def test_malformed_input(self): self.rows[0]['sembol'] = {}; self.assertEqual(self.report()['malformed'], 1); self.assertEqual(self.first()['status'], 'INSUFFICIENT')
    def test_atomic_cache_and_history_preserved(self):
        history = self.paths.runtime_file('history_test.json'); atomic_json(history, {'records': self.rows}); before = history.read_bytes()
        report = module.publish(self.paths, self.rows, self.now, self.holiday)
        with patch('kullanici_kayitlari.os.replace', side_effect=OSError('failed')):
            self.assertIsNone(module.safe_publish(self.paths, [], self.now))
        self.assertEqual(module.api_report({}, self.paths)['summary'], report['summary']); self.assertEqual(history.read_bytes(), before)
    def test_corrupt_cache_503(self):
        self.paths.public_file('top10_ogrenme_performansi.json').write_text('{bad')
        with self.assertRaises(RecordError) as error: module.api_report({}, self.paths)
        self.assertEqual(error.exception.status, 503)
    def test_missing_cache_503(self):
        with self.assertRaises(RecordError) as error: module.api_report({}, self.paths)
        self.assertEqual(error.exception.status, 503)
    def test_invalid_filter_400(self):
        for query in ({'horizon':['2']}, {'period':['evil']}, {'horizon':['1','3']}, {'path':['private']}):
            with self.assertRaises(RecordError) as error: module.api_report(query, self.paths)
            self.assertEqual(error.exception.status, 400)
    def test_api_filters(self):
        module.publish(self.paths, self.rows, self.now, self.holiday)
        report = module.api_report({'horizon':['3'], 'period':['90d']}, self.paths)
        self.assertEqual(report['selected_horizon'], 3); self.assertTrue(all(r['horizon'] == 3 for r in report['recent_comparisons']))
    def test_http_smoke(self):
        from web_server import create_server
        module.publish(self.paths, self.rows, self.now, self.holiday)
        server = create_server('127.0.0.1', 0, data_paths=self.paths)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/top10-learning-performance?horizon=3') as response:
                self.assertEqual(json.load(response)['selected_horizon'], 3)
        finally: server.shutdown(); server.server_close(); thread.join()
    def test_aggregation_error_isolated(self):
        with patch.object(module, 'aggregate', side_effect=ValueError('failure')):
            self.assertIsNone(module.safe_publish(self.paths, self.rows, self.now))
    def test_multiple_day_summary(self):
        comparisons = [{'status': status, 'differences': {'mean_return': edge}} for status, edge in
                       (('LEARNED_BETTER', 2), ('BASE_BETTER', -1), ('TIE', 0), ('INSUFFICIENT', 100))]
        result = module.summary(comparisons)
        self.assertEqual(result['completed_days'], 3); self.assertEqual(result['learned_win_rate'], 1/3)
        self.assertEqual(result['mean_learned_edge'], 1/3); self.assertEqual(result['median_learned_edge'], 0)
    def test_result_price_conflict(self):
        self.rows[10]['sonuc_1g'].update(fiyat=102, getiri_yuzde=2, yon_getirisi=2)
        self.assertIn('INCONSISTENT_RESULT_PRICE', self.first()['excluded'])
    def test_other_horizons_survive_pending(self):
        self.rows[0]['sonuc_1g'] = None; self.assertEqual(self.first(3)['status'], 'TIE')
    def test_baseline_is_not_backtest(self):
        self.rows[0]['performance_source'] = 'BACKTEST'; self.assertIn('NON_PROSPECTIVE_CONTROL', self.first()['excluded'])
    def test_unknown_snapshot_source(self):
        self.rows[0]['kaynak'] = 'MANUAL_IMPORT'; self.assertIn('UNVERIFIED_SNAPSHOT', self.first()['excluded'])
    def test_period_endpoints_empty_are_not_wins(self):
        result = self.report()['periods']['30d']['1']; self.assertEqual(result['completed_days'], 0); self.assertIsNone(result['learned_win_rate'])
    def test_missing_mfe_not_zero(self):
        for row in self.rows: row['sonuc_1g']['mfe_pct'] = None
        self.assertIsNone(self.first()['base']['mean_mfe']); self.assertEqual(self.first()['base']['mfe_samples'], 0)
    def test_report_worker_failure_isolation(self):
        from performans_motoru import PerformansMotoru
        with patch.object(module, 'aggregate', side_effect=ValueError('auxiliary failure')):
            PerformansMotoru(location=self.paths, clock=lambda: self.now).reports([], self.now)
        report = json.loads(self.paths.public_file('performans_ozeti.json').read_bytes())
        self.assertEqual(report['top10_learning_comparison']['status'], 'UNAVAILABLE')


if __name__ == '__main__': unittest.main()
