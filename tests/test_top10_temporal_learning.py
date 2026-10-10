import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from ai_karar_motoru import HORIZONS, ISTANBUL
from performans_motoru import sessions_after
from sinyal_performansi import RELIABILITY, VERSION as REPORT_VERSION
from top10_temporal_learning import build_evidence
from veri_yollari import DataPaths
import yarin_kalibrasyon as learning


class TemporalLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.now = datetime(2026, 10, 7, 19, tzinfo=ISTANBUL)
        cls.holiday = staticmethod(lambda day: False)
        cls.records = []
        for day in sessions_after(datetime(2026, 1, 1).date(), 100, cls.holiday):
            at = datetime.combine(day, datetime.min.time(), ISTANBUL).replace(hour=19)
            sessions = sessions_after(day, 60, cls.holiday)
            for i in range(10):
                change = 2 if i < 5 else -2
                row = {'id': f'{day}-{i}', 'sembol': f'S{i}', 'zaman': at.isoformat(),
                       'model': 'YARIN_TOP10', 'fiyat': 100, 'hedef': 110,
                       'indicator_snapshot': {'captured_at': at.isoformat(),
                                              'inputs': {'fiyat': 100, 'rsi': 45 if i < 5 else 75}}}
                for h in HORIZONS:
                    end = sessions[h-1]
                    observed = datetime.combine(end, datetime.min.time(), ISTANBUL).replace(hour=19)
                    row[f'sonuc_{h}g'] = {'degerlendirme_tamamlandi': True, 'tarih': end.isoformat(),
                                         'observed_at': observed.isoformat(), 'baslangic_fiyati': 100,
                                         'fiyat': 100 + change, 'getiri_yuzde': change}
                cls.records.append(row)
        cls.evidence = build_evidence(cls.records, cls.now, cls.holiday)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.location = DataPaths({'BIST_DATA_DIR': self.temp.name}); self.location.ensure()
        self.enterContext(patch.dict('os.environ', {'TOP10_LEARNING_ENABLED': 'true'}))
        self.row = {'sembol': 'NEW', 'fiyat': 100, 'rsi': 45}

    def context(self, evidence=None):
        report = {'version': REPORT_VERSION, 'analysis_only': True,
                  'reliability_thresholds': RELIABILITY, 'updated_at': self.now.isoformat(),
                  'top10_temporal_learning': copy.deepcopy(evidence or self.evidence)}
        with patch('sinyal_performansi.read_report', return_value=report):
            return learning.top10_learning_context(self.location, self.now)

    def adjustment(self, model=None):
        return learning.top10_learning_adjustment(self.row, model or self.context(), self.now)

    def test_all_six_real_horizons_contribute_with_fixed_bounded_weights(self):
        result = self.adjustment()
        self.assertEqual(result['learning_status'], 'APPLIED')
        evidence = result['learning_reasons'][0]['evidence']
        self.assertEqual({e['horizon'] for e in evidence}, set(HORIZONS))
        self.assertAlmostEqual(sum(learning.TOP10_HORIZON_WEIGHTS.values()), 1)
        self.assertLessEqual(abs(result['learning_adjustment']), learning.TOP10_FAMILY_CAP)
        self.assertTrue(all(e['validation_sample_count'] >= 30 for e in evidence))

    def test_long_horizons_add_evidence_without_replacing_daily_primary(self):
        model = self.context(); full = self.adjustment(model)['learning_adjustment']
        model['index'] = {key: value for key, value in model['index'].items() if key[-1] <= 5}
        self.assertLess(self.adjustment(model)['learning_adjustment'], full)
        model['index'] = {key: value for key, value in self.context()['index'].items() if key[-1] != 1}
        self.assertEqual(self.adjustment(model)['learning_adjustment'], 0)

    def test_training_observations_are_purged_before_validation_predictions(self):
        for entry in self.evidence['rows']:
            self.assertLess(entry['train_observed_through'], entry['cutoff'])
        daily = self.evidence['baselines']['1']['train']['sample_size']
        long = self.evidence['baselines']['60']['train']['sample_size']
        self.assertLess(long, daily)
        rows = copy.deepcopy(self.records)
        cutoff = self.evidence['rows'][0]['cutoff']
        for row in rows:
            if row['zaman'] < cutoff:
                for h in HORIZONS: row[f'sonuc_{h}g']['observed_at'] = self.now.isoformat()
        purged = self.context(build_evidence(rows, self.now, self.holiday))
        self.assertEqual(self.adjustment(purged)['learning_adjustment'], 0)

    def test_holdout_reversal_preserves_base_scores_and_records(self):
        rows = copy.deepcopy(self.records)
        cutoffs = {e['horizon']: e['cutoff'] for e in self.evidence['rows']}
        for row in rows:
            for h in HORIZONS:
                if row['zaman'] >= cutoffs[h]:
                    result = row[f'sonuc_{h}g']; change = -result['getiri_yuzde']
                    result.update(getiri_yuzde=change, fiyat=100+change)
        original = copy.deepcopy(rows)
        model = self.context(build_evidence(rows, self.now, self.holiday))
        ranked = learning.rank_with_learning([(80, self.row)], model, self.now)
        self.assertEqual(ranked[0][0], 80)
        self.assertEqual(ranked[0][1]['learning_adjustment'], 0)
        self.assertEqual(rows, original)

    def test_many_stocks_on_one_day_do_not_establish_reliability(self):
        rows = [dict(row, id=f'copy-{i}', sembol=f'copy-{i}')
                for i, row in enumerate(self.records[:10] * 100)]
        model = self.context(build_evidence(rows, self.now, self.holiday))
        self.assertEqual(model['index'], {})
        self.assertEqual(self.adjustment(model)['learning_adjustment'], 0)

    def test_missing_unverified_future_and_conflicting_outcomes_do_not_train(self):
        for kind in ('pending', 'unverified', 'future', 'conflict', 'feature_future'):
            with self.subTest(kind=kind):
                rows = copy.deepcopy(self.records)
                for row in rows:
                    for h in HORIZONS:
                        result = row[f'sonuc_{h}g']
                        if kind == 'pending': result['degerlendirme_tamamlandi'] = False
                        if kind == 'unverified': result['unverified'] = True
                        if kind == 'future': result['observed_at'] = (self.now+timedelta(days=1)).isoformat()
                    if kind == 'feature_future': row['indicator_snapshot']['captured_at'] = self.now.isoformat()
                if kind == 'conflict':
                    other = copy.deepcopy(rows)
                    for row in other: row['hedef'] = 120
                    rows += other
                evidence = build_evidence(rows, self.now, self.holiday)
                self.assertEqual(evidence['rows'], [])

    def test_old_aggregate_cache_cannot_enable_unvalidated_learning(self):
        with patch('sinyal_performansi.read_report', return_value={
                'version': REPORT_VERSION, 'analysis_only': True, 'reliability_thresholds': RELIABILITY,
                'updated_at': self.now.isoformat(), 'indicator_analysis': {'rows': []}}):
            context = learning.top10_learning_context(self.location, self.now)
        self.assertEqual(context['status'], 'NO_TEMPORAL_VALIDATION')
        self.assertEqual(self.adjustment(context)['learning_adjustment'], 0)

    def test_bad_temporal_evidence_and_uncertain_daily_edges_fail_closed(self):
        for kind in ('few_days', 'few_samples', 'overlap', 'future_cutoff', 'uncertain', 'malformed'):
            model = self.context()
            for entry in model['index'].values():
                if kind == 'few_days': entry['validation']['independent_days'] = 1
                if kind == 'few_samples': entry['validation']['completed'] = 0
                if kind == 'overlap': entry['train_observed_through'] = entry['cutoff']
                if kind == 'future_cutoff': entry['cutoff'] = (self.now+timedelta(days=1)).isoformat()
                if kind == 'uncertain': entry['validation']['daily_edge_lower'] = -1
                if kind == 'malformed': entry['train']['mean_return'] = float('nan')
            with self.subTest(kind=kind): self.assertEqual(self.adjustment(model)['learning_adjustment'], 0)

    def test_frozen_inputs_only_and_input_histories_remain_unchanged(self):
        original = copy.deepcopy(self.records)
        build_evidence(self.records, self.now, self.holiday)
        self.assertEqual(self.records, original)
        model = self.context()
        self.row['indicator_snapshot'] = {'captured_at': (self.now+timedelta(seconds=1)).isoformat(),
                                          'inputs': {'fiyat': 100, 'rsi': 45}}
        self.assertEqual(self.adjustment(model)['learning_adjustment'], 0)

    def test_existing_publish_adds_evidence_to_same_derived_cache(self):
        from sinyal_performansi import publish, read_report
        with patch('sinyal_performansi.aggregate', return_value={'version': REPORT_VERSION}), \
             patch('sinyal_performansi.aggregate_indicators', return_value={}), \
             patch('top10_temporal_learning.build_evidence', return_value=self.evidence) as build:
            publish(self.location, self.records, self.now)
        build.assert_called_once_with(self.records, self.now)
        self.assertEqual(read_report(self.location)['top10_temporal_learning'], self.evidence)
        self.assertEqual(list(self.location.runtime.glob('*.json')), [])

    def test_numeric_string_returns_are_normalized_before_daily_statistics(self):
        rows = copy.deepcopy(self.records)
        for row in rows:
            for h in HORIZONS:
                row[f'sonuc_{h}g']['getiri_yuzde'] = str(row[f'sonuc_{h}g']['getiri_yuzde'])
        self.assertEqual(build_evidence(rows, self.now, self.holiday), self.evidence)

    def test_reliably_negative_real_results_reduce_score_with_same_cap(self):
        self.row['rsi'] = 75
        result = self.adjustment()
        self.assertLess(result['learning_adjustment'], 0)
        self.assertGreaterEqual(result['learning_adjustment'], -learning.TOP10_FAMILY_CAP)

    def test_future_predictions_cannot_change_current_weights(self):
        future = copy.deepcopy(self.records[:10])
        for row in future:
            row.update(id='future-'+row['id'], zaman=(self.now+timedelta(days=1)).isoformat())
        self.assertEqual(build_evidence(self.records+future, self.now, self.holiday), self.evidence)

    def test_variable_daily_edges_crossing_zero_cannot_enable_learning(self):
        rows = copy.deepcopy(self.records)
        dates = sorted({row['zaman'] for row in rows})
        for row in rows:
            if row['indicator_snapshot']['inputs']['rsi'] != 45: continue
            change = 2 if dates.index(row['zaman']) % 2 else -12
            for h in HORIZONS:
                row[f'sonuc_{h}g'].update(getiri_yuzde=change, fiyat=100+change)
        model = self.context(build_evidence(rows, self.now, self.holiday))
        self.assertEqual(self.adjustment(model)['learning_adjustment'], 0)
