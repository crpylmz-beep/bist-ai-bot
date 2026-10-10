import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from ai_karar_motoru import HORIZONS, ISTANBUL
from kullanici_kayitlari import atomic_json
from performans_motoru import PerformansMotoru, outcome, sessions_after
from top10_frozen_pair import SCHEMA, freeze_pair, verify_pair
from veri_yollari import DataPaths
import bist_bot
import top10_ogrenme_performansi as performance


class FrozenPairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.at=datetime(2026,3,2,19,tzinfo=ISTANBUL)
        self.now=datetime(2026,10,10,19,tzinfo=ISTANBUL)
        self.holiday=lambda day:False
        candidates=[]
        for i in range(1,12):
            candidates.append({'sembol':f'S{i}','fiyat':100,'rsi':45,'macd':2,'signal':1,
                'yarin_top10_puani':80+i,'yarin_ai_karar':'AL','ai_yarin_hedef':120,'ai_yarin_stop':90,
                'learning_version':'TOP10_INDICATOR_V2','learning_adjustment':1,'base_score':80,
                'base_rank':i,'learned_rank':max(1,i-1),'calibration_version':'CAL_V1'})
        self.snapshot=bist_bot.yarin_snapshot_modeli({
            'analiz_tarihi':self.at.date().isoformat(),'top10':copy.deepcopy(candidates[1:]),
            'base_top10':copy.deepcopy(candidates[:10]),'kalibrasyon_modeli':{'version':'CAL_V1'},
            'piyasa_modeli':{'version':'MARKET_V1'},
            'comparison_context':{'learning_asof':(self.at-timedelta(hours=1)).isoformat(),
                                  'horizon_weights':{'1':.55,'3':.15,'5':.1,'10':.08,'20':.07,'60':.05}}
        },self.at.isoformat())
        self.archive=self.location.archives/(self.at.date().isoformat()+'.json')
        atomic_json(self.archive,self.snapshot)

    def records(self):
        return PerformansMotoru(self.location,clock=lambda:self.now,holiday=self.holiday).snapshot_records({})

    def completed(self,records=None):
        rows=self.records() if records is None else records
        days=sessions_after(self.at.date(),60,self.holiday)
        for row in rows:
            delta=int(row['sembol'][1:])-6
            bars=[{'date':day.isoformat(),'open':100,'close':100+delta,'high':120,'low':90,'complete':True}
                  for day in days]
            for h in HORIZONS:row[f'sonuc_{h}g']=outcome(row,bars,h,self.now,self.holiday)
        return rows

    def test_same_timestamp_slice_and_separate_versioned_lists_are_frozen(self):
        pair=self.snapshot['frozen_comparison']
        self.assertEqual(pair['schema'],SCHEMA);self.assertEqual(pair['status'],'READY')
        self.assertEqual(pair['snapshot_time'],self.at.isoformat())
        self.assertEqual(len(pair['data_slice_id']),64)
        self.assertEqual(pair['models']['BASE']['version'],'TOP10_BASE_V1')
        self.assertEqual(pair['models']['LEARNED']['version'],'TOP10_INDICATOR_V2')
        self.assertEqual([p['symbol'] for p in pair['models']['BASE']['top10']],[f'S{i}' for i in range(1,11)])
        self.assertEqual([p['symbol'] for p in pair['models']['LEARNED']['top10']],[f'S{i}' for i in range(2,12)])
        self.assertIsNone(verify_pair(self.snapshot))

    def test_existing_archive_cannot_be_replaced_and_ingestion_is_once_only(self):
        original=self.archive.read_bytes();state={}
        engine=PerformansMotoru(self.location)
        self.assertEqual(len(engine.snapshot_records(state)),20)
        self.assertEqual(engine.snapshot_records(state),[])
        with self.assertRaises(FileExistsError):bist_bot.json_atomik_yaz(str(self.archive),{'new':True},overwrite=False)
        self.assertEqual(self.archive.read_bytes(),original)

    def test_ingestion_preserves_both_versions_and_shared_integrity_identity(self):
        records=self.records()
        self.assertEqual(len(records),20)
        self.assertEqual({r['comparison_schema'] for r in records},{SCHEMA})
        self.assertEqual(len({r['data_slice_id'] for r in records}),1)
        self.assertEqual(len({r['comparison_digest'] for r in records}),1)
        self.assertEqual({r['model_version'] for r in records},{'TOP10_BASE_V1','TOP10_INDICATOR_V2'})
        self.assertTrue(all(r['comparison_integrity_error'] is None for r in records))
        self.assertTrue(all(r[f'sonuc_{h}g'] is None for r in records for h in HORIZONS))

    def test_six_session_horizons_success_median_risk_and_deltas(self):
        report=performance.aggregate(self.completed(),self.now,self.holiday)
        for h in HORIZONS:
            stats=report['horizons'][str(h)]
            self.assertAlmostEqual(stats['models']['BASE']['median_return'],-.5)
            self.assertAlmostEqual(stats['models']['LEARNED']['median_return'],.5)
            self.assertAlmostEqual(stats['differences_vs_base']['median_return'],1)
            self.assertAlmostEqual(stats['differences_vs_base']['success_rate_percentage_points'],10)
            self.assertTrue(stats['models']['BASE']['risk']['complete'])
            self.assertAlmostEqual(stats['models']['BASE']['risk']['mean_mae'],-10)
            self.assertAlmostEqual(stats['differences_vs_base']['mean_mae'],0)
            self.assertEqual(stats['display_status'],'YETERSİZ VERİ') # One day is not proof.

    def test_missing_risk_never_invents_risk_or_changes_realized_success(self):
        records=self.completed()
        for row in records:
            for h in HORIZONS:row[f'sonuc_{h}g'].pop('mae_pct',None)
        report=performance.aggregate(records,self.now,self.holiday)
        for h in HORIZONS:
            stats=report['horizons'][str(h)]
            self.assertEqual(stats['models']['LEARNED']['sample_count'],10)
            self.assertIsNone(stats['models']['BASE']['risk']['mean_mae'])
            self.assertEqual(stats['models']['BASE']['risk']['display_status'],'YETERSİZ VERİ')
            self.assertIsNone(stats['differences_vs_base']['mean_mae'])

    def test_incomplete_lists_mismatched_inputs_and_future_context_are_explicitly_insufficient(self):
        for issue in ('list','price','rsi','time','future'):
            snapshot=copy.deepcopy(self.snapshot)
            if issue=='list':snapshot['base_top10'].pop()
            if issue=='price':snapshot['base_top10'][1]['tahmin']['fiyat']=101
            if issue=='rsi':snapshot['base_top10'][1]['rsi']=99
            if issue=='time':snapshot['base_top10'][1]['tahmin']['tahmin_zamani']=(self.at+timedelta(seconds=1)).isoformat()
            if issue=='future':snapshot['comparison_context']['learning_asof']=(self.at+timedelta(seconds=1)).isoformat()
            result=freeze_pair(snapshot)
            with self.subTest(issue=issue):
                self.assertEqual(result['display_status'],'YETERSİZ VERİ')
                self.assertEqual(result['status'],'INSUFFICIENT')

    def test_tampered_archive_is_excluded_without_replacing_existing_records(self):
        self.snapshot['top10'][0]['tahmin']['skor']=999
        atomic_json(self.archive,self.snapshot)
        records=self.completed()
        self.assertTrue(all(r['comparison_integrity_error']=='PAIR_INTEGRITY_MISMATCH' for r in records))
        stats=performance.aggregate(records,self.now,self.holiday)['horizons']['1']
        self.assertEqual(stats['display_status'],'YETERSİZ VERİ')
        self.assertEqual(stats['models']['BASE']['sample_count'],0)
        self.assertIsNone(stats['differences_vs_base']['median_return'])

    def test_mixed_slice_and_model_version_cannot_produce_paired_success(self):
        for field in ('data_slice_id','model_version','model_configuration_digest'):
            records=self.completed();records[0][field]='different'
            stats=performance.aggregate(records,self.now,self.holiday)['horizons']['1']
            with self.subTest(field=field):self.assertEqual(stats['models']['BASE']['sample_count'],0)

    def test_new_weights_or_live_prices_never_recompute_historical_predictions(self):
        before=self.archive.read_bytes()
        with patch('yarin_kalibrasyon.TOP10_HORIZON_WEIGHTS',{1:999}), \
             patch('yarin_kalibrasyon.rank_with_learning',side_effect=AssertionError('rescore')), \
             patch('performans_motoru.provider_history',side_effect=AssertionError('quotes')):
            records=self.completed();performance.aggregate(records,self.now,self.holiday)
            self.assertIsNone(verify_pair(self.snapshot))
        self.assertEqual(self.archive.read_bytes(),before)

    def test_snapshot_builder_copies_lists_and_does_not_mutate_old_payloads(self):
        original=copy.deepcopy(self.snapshot)
        pair=freeze_pair(self.snapshot);pair['models']['BASE']['top10'][0]['prediction']['fiyat']=999
        self.assertEqual(self.snapshot,original)
        legacy=bist_bot.yarin_snapshot_modeli({'top10':[{'sembol':'LEGACY','fiyat':100}],'base_top10':[]},None)
        self.assertNotIn('frozen_comparison',legacy)

    def test_not_yet_closed_long_horizons_are_not_successes(self):
        records=self.completed()
        current=self.at+timedelta(days=2)
        report=performance.aggregate(records,current,self.holiday)
        for h in (3,5,10,20,60):
            stats=report['horizons'][str(h)]
            self.assertEqual(stats['display_status'],'YETERSİZ VERİ')
            self.assertEqual(stats['models']['BASE']['sample_count'],0)
            self.assertIsNone(stats['models']['LEARNED']['median_return'])

    def test_integer_horizon_keys_keep_integrity_after_archive_roundtrip(self):
        snapshot=copy.deepcopy(self.snapshot)
        snapshot['comparison_context']['horizon_weights']={1:.55,3:.15,5:.1,10:.08,20:.07,60:.05}
        snapshot['frozen_comparison']=freeze_pair(snapshot)
        saved=json.loads(json.dumps(snapshot))
        self.assertIsNone(verify_pair(saved))
        atomic_json(self.archive,saved)
        self.assertTrue(all(r['comparison_integrity_error'] is None for r in self.records()))

    def test_summary_median_uses_all_actual_returns_not_median_of_daily_medians(self):
        records=self.completed()
        first=performance.comparison('one',[(r,False) for r in records],1,self.now,self.holiday)
        second=copy.deepcopy(first)
        second.update(snapshot_id='two',snapshot_time=(self.at+timedelta(days=1)).isoformat())
        values=[-10]+[100]*9
        for model in ('base','learned'):
            second[model].update(return_samples=values,median_return=100,mean_return=89,positive_count=9,success_rate=.9)
        stats=performance.summary([first,second])
        self.assertEqual(stats['models']['BASE']['median_return'],3.5)
        self.assertNotEqual(stats['models']['BASE']['median_return'],49.75)

    def test_malformed_pair_metadata_fails_closed_without_breaking_ingestion(self):
        self.snapshot['frozen_comparison']['models']=[]
        atomic_json(self.archive,self.snapshot)
        records=self.completed()
        self.assertEqual(len(records),20)
        stats=performance.aggregate(records,self.now,self.holiday)['horizons']['1']
        self.assertEqual(stats['display_status'],'YETERSİZ VERİ')
        self.assertEqual(stats['models']['BASE']['sample_count'],0)
        records=self.completed(self.records())
        # A structurally inconsistent shared slice cannot produce observed rates.
        for row in records:row['comparison_integrity_error']=None
        records[0]['data_slice_id']='different'
        stats=performance.aggregate(records,self.now,self.holiday)['horizons']['1']
        self.assertEqual(stats['observed_models']['BASE']['sample_count'],0)
