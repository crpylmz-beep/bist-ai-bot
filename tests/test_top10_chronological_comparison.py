import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from ai_karar_motoru import HORIZONS, ISTANBUL
from performans_motoru import sessions_after
from veri_yollari import DataPaths
import top10_ogrenme_performansi as comparison


class ChronologicalComparisonTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,10,19,tzinfo=ISTANBUL)
        self.holiday=lambda day:False
        self.rows=[]
        dates=sessions_after(datetime(2026,5,1).date(),12,self.holiday)
        for index,day in enumerate(dates):
            at=datetime.combine(day,datetime.min.time(),ISTANBUL).replace(hour=19)
            ends=sessions_after(day,60,self.holiday)
            for name,model in comparison.MODELS.items():
                symbols=range(10) if name=='BASE' else range(1,11)
                for rank,symbol in enumerate(symbols,1):
                    change=-5 if symbol==0 else 5 if symbol==10 else 1
                    row={'id':f'{index}-{name}-{symbol}','snapshot_id':f'z{12-index:02}',
                         'sembol':f'S{symbol}','zaman':at.isoformat(),'model':model,
                         'kaynak':'IMMUTABLE_YARIN_SNAPSHOT','tahmin_sirasi':rank,
                         'fiyat':100,'hedef':110,'karar':'AL','learning_version':'TOP10_INDICATOR_V2',
                         'learning_adjustment':1 if name=='LEARNED' and symbol==10 else 0}
                    for h in HORIZONS:
                        end=ends[h-1]
                        observed=datetime.combine(end,datetime.min.time(),ISTANBUL).replace(hour=19)
                        row[f'sonuc_{h}g']={'degerlendirme_tamamlandi':True,'observed_at':observed.isoformat(),
                            'tarih':end.isoformat(),'baslangic_fiyati':100,'fiyat':100+change,'getiri_yuzde':change}
                    self.rows.append(row)

    def report(self,rows=None,current=None):
        return comparison.aggregate(self.rows if rows is None else rows,current or self.now,self.holiday)

    def evaluation(self,h=1,rows=None,current=None):
        return self.report(rows,current)['horizons'][str(h)]['chronological_evaluation']

    def test_six_horizon_realized_differences_and_chronological_order(self):
        report=self.report(list(reversed(self.rows)))
        for h in HORIZONS:
            result=report['horizons'][str(h)]['chronological_evaluation']
            self.assertEqual(result['paired_days'],12)
            self.assertEqual(result['paired_samples_per_model'],120)
            self.assertAlmostEqual(result['differences_vs_base']['mean_return'],1)
            self.assertAlmostEqual(result['differences_vs_base']['success_rate_percentage_points'],10)
            self.assertEqual(result['assessment'],'DESCRIPTIVE_LEARNED_AHEAD')
            timeline=result['timeline']
            self.assertEqual([r['snapshot_time'] for r in timeline],sorted(r['snapshot_time'] for r in timeline))
            self.assertEqual([r['paired_sample_count'] for r in timeline],list(range(10,121,10)))
            self.assertEqual(timeline[0]['snapshot_id'],'z12')
            self.assertEqual(timeline[-1]['snapshot_id'],'z01')
            self.assertTrue(all(r['outcomes_available_at']>r['snapshot_time'] for r in timeline))

    def test_few_days_have_descriptive_metrics_without_improvement_claim(self):
        result=self.evaluation(rows=self.rows[:20])
        self.assertEqual(result['assessment'],'INSUFFICIENT_DATA')
        self.assertFalse(result['sufficient'])
        self.assertEqual(result['paired_days'],1)
        self.assertAlmostEqual(result['differences_vs_base']['mean_return'],1)

    def test_missing_outcomes_never_enter_paired_denominators(self):
        for row in self.rows:
            if row['model']==comparison.MODELS['BASE'] and row['tahmin_sirasi']==1:
                for h in HORIZONS:row[f'sonuc_{h}g']=None
        report=self.report()
        for h in HORIZONS:
            result=report['horizons'][str(h)]['chronological_evaluation']
            self.assertEqual(result['assessment'],'INSUFFICIENT_DATA')
            self.assertEqual(result['paired_samples_per_model'],0)
            self.assertIsNone(result['differences_vs_base']['mean_return'])
            self.assertIsNone(result['differences_vs_base']['success_rate_percentage_points'])
            self.assertEqual(result['excluded_snapshots'],12)

    def test_future_labels_are_excluded_as_of_evaluation_time(self):
        current=datetime(2026,5,25,19,tzinfo=ISTANBUL)
        result=self.evaluation(60,current=current)
        self.assertEqual(result['assessment'],'INSUFFICIENT_DATA')
        self.assertEqual(result['paired_snapshots'],0)
        self.assertIsNone(result['models']['LEARNED']['mean_return'])
        self.assertGreater(self.evaluation(1,current=current)['paired_snapshots'],0)

    def test_current_models_are_not_applied_retroactively_and_histories_are_preserved(self):
        original=copy.deepcopy(self.rows)
        with patch('yarin_kalibrasyon.top10_learning_context',side_effect=AssertionError('rescore')), \
             patch('yarin_kalibrasyon.rank_with_learning',side_effect=AssertionError('rescore')):
            result=self.evaluation()
        self.assertFalse(result['reconstructed_scores'])
        self.assertEqual(result['comparison_basis'],'PROSPECTIVE_IMMUTABLE_SNAPSHOTS')
        self.assertEqual(self.rows,original)

    def test_model_versions_are_reported_separately(self):
        for row in self.rows[:120]:row['learning_version']='TOP10_INDICATOR_V1'
        result=self.evaluation()
        self.assertEqual(result['assessment'],'MULTIPLE_MODEL_VERSIONS')
        self.assertEqual(set(result['by_learning_version']),{'TOP10_INDICATOR_V1','TOP10_INDICATOR_V2'})
        for version in result['by_learning_version'].values():
            self.assertEqual(version['paired_days'],6)
            self.assertEqual(version['assessment'],'INSUFFICIENT_DATA')

    def test_absent_learning_or_unknown_versions_cannot_claim_improvement(self):
        for row in self.rows:row['learning_adjustment']=0
        self.assertEqual(self.evaluation()['assessment'],'INSUFFICIENT_APPLIED_LEARNING')
        for row in self.rows:row.pop('learning_version',None)
        result=self.evaluation()
        self.assertEqual(result['assessment'],'INSUFFICIENT_DATA')
        self.assertEqual(result['paired_days'],0)
        self.assertEqual(result['by_learning_version'],{})

    def test_duplicate_snapshot_ids_on_same_day_do_not_inflate_day_evidence(self):
        first=self.rows[:20];rows=[]
        for i in range(12):
            for row in first:
                item=copy.deepcopy(row);item.update(id=f'{i}-{row["id"]}',snapshot_id=f'copy-{i}')
                item['zaman']=(datetime.fromisoformat(item['zaman'])+timedelta(seconds=i)).isoformat()
                rows.append(item)
        result=self.evaluation(rows=rows)
        self.assertEqual(result['paired_snapshots'],12)
        self.assertEqual(result['paired_days'],1)
        self.assertEqual(result['assessment'],'INSUFFICIENT_DATA')

    def test_negative_and_mixed_differences_are_not_reported_as_improvement(self):
        for row in self.rows:
            if row['sembol']=='S10':
                for h in HORIZONS:row[f'sonuc_{h}g'].update(fiyat=90,getiri_yuzde=-10)
        result=self.evaluation()
        self.assertEqual(result['assessment'],'DESCRIPTIVE_BASE_AHEAD')
        for row in self.rows:
            if row['sembol']=='S10':
                for h in HORIZONS:row[f'sonuc_{h}g'].update(fiyat=98,getiri_yuzde=-2)
        result=self.evaluation()
        self.assertEqual(result['assessment'],'DESCRIPTIVE_LEARNED_AHEAD')
        # Higher return with fewer profitable selections is explicitly mixed.
        for row in self.rows:
            if row['sembol']=='S0':
                for h in HORIZONS:row[f'sonuc_{h}g'].update(fiyat=101,getiri_yuzde=1)
            if row['sembol']=='S9':
                for h in HORIZONS:row[f'sonuc_{h}g'].update(fiyat=110,getiri_yuzde=10)
            if row['sembol']=='S10':
                for h in HORIZONS:row[f'sonuc_{h}g'].update(fiyat=200,getiri_yuzde=100)
        # Make a learned-only shared member loss impossible to compare coherently;
        # use a distinct learned replacement instead.
        for row in self.rows:
            if row['model']==comparison.MODELS['LEARNED'] and row['sembol']=='S8':
                row['sembol']='OTHER'
                for h in HORIZONS:row[f'sonuc_{h}g'].update(fiyat=98,getiri_yuzde=-2)
        self.assertEqual(self.evaluation()['assessment'],'MIXED_RESULTS')

    def test_unverified_result_flags_and_boolean_returns_are_excluded(self):
        for kind in ('unverified','boolean','mixed_version'):
            rows=copy.deepcopy(self.rows)
            for row in rows:
                if row['model']!=comparison.MODELS['LEARNED'] or row['tahmin_sirasi']!=1:continue
                if kind=='mixed_version':row['learning_version']={'invalid':True}
                for h in HORIZONS:
                    if kind=='unverified':row[f'sonuc_{h}g']['unverified']=True
                    if kind=='boolean':row[f'sonuc_{h}g']['getiri_yuzde']=True
            with self.subTest(kind=kind):self.assertEqual(self.evaluation(rows=rows)['paired_snapshots'],0)

    def test_empty_actual_history_has_no_invented_improvement(self):
        report=self.report(rows=[])
        for h in HORIZONS:
            result=report['horizons'][str(h)]['chronological_evaluation']
            self.assertEqual(result['assessment'],'INSUFFICIENT_DATA')
            self.assertIsNone(result['differences_vs_base']['mean_return'])
            self.assertEqual(result['timeline'],[])

    def test_existing_api_selects_chronological_metrics_by_horizon_and_period(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        location=DataPaths({'BIST_DATA_DIR':temp.name});location.ensure()
        comparison.publish(location,self.rows,self.now,self.holiday)
        for h in HORIZONS:
            result=comparison.api_report({'horizon':[str(h)],'period':['all_time']},location)
            self.assertEqual(result['summary']['chronological_evaluation']['paired_days'],12)
            self.assertEqual(result['selected_horizon'],h)
        result=comparison.api_report({'period':['7d']},location)
        self.assertEqual(result['summary']['chronological_evaluation']['assessment'],'INSUFFICIENT_DATA')

    def test_timeline_bounds_preserve_full_history_totals_and_exclusion_reasons(self):
        source=self.report()['recent_comparisons']
        first=next(row for row in source if row['horizon']==1)
        rows=[]
        start=datetime(2025,1,1,19,tzinfo=ISTANBUL)
        for i in range(comparison.MAX_RECENT+10):
            row=copy.deepcopy(first)
            row.update(snapshot_id=str(i),snapshot_time=(start+timedelta(days=i)).isoformat())
            rows.append(row)
        result=comparison.chronological_evaluation(list(reversed(rows)))
        self.assertTrue(result['timeline_truncated'])
        self.assertEqual(len(result['timeline']),comparison.MAX_RECENT)
        self.assertEqual(result['paired_samples_per_model'],1100)
        self.assertEqual(result['timeline'][-1]['paired_sample_count'],1100)
        self.assertEqual(result['timeline'][0]['snapshot_id'],'10')
        rows[-1]['learning_version']=None
        rows[-2]['status']='INSUFFICIENT'
        result=comparison.chronological_evaluation(rows)
        self.assertEqual(result['timeline'][-1]['exclusion_reason'],'UNVERIFIED_LEARNING_VERSION')
        self.assertEqual(result['timeline'][-2]['exclusion_reason'],'INCOMPLETE_OR_UNVERIFIED_PAIR')
        self.assertFalse(result['timeline'][-1]['included_in_paired_metrics'])
        self.assertEqual(result['paired_samples_per_model'],1080)
