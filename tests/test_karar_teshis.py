"""Step 19: bounded combinations, diagnostic risks and source-isolated health."""
import copy
import json
import os
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime,timedelta
from unittest.mock import patch,Mock
import test_kontrollu_ogrenme as fixtures
from ai_karar_motoru import ISTANBUL
from kullanici_kayitlari import atomic_json
from performans_motoru import (combination_catalog,combination_report,combination_limits,source_reliability,
    diagnostic_rows,diagnostic_stats,decision_error,decision_diagnostics,algorithm_health,calibration_report,
    quality_report,excursion_metrics,evidence_features,evidence_rows,controlled_publish,controlled_score,
    EVIDENCE_BASE,ERROR_TYPES,PerformansMotoru,performance_source,outcome)


class DecisionDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ControlledLearningTests('test_catalog_and_families');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.paths=self.fixture.paths;self.now=self.fixture.now
        self.enterContext(patch.dict(os.environ,{'MIN_COMBINATION_SAMPLES':'50','MIN_COMBINATION_DAYS':'7','MAX_CRITERION_COMBINATIONS':'64',
            'PERFORMANCE_LIVE_RELIABILITY':'1','PERFORMANCE_BACKTEST_RELIABILITY':'.5','PERFORMANCE_SHADOW_RELIABILITY':'.75'}))
    def rows(self,n=120):return [self.fixture.row(i,i<n//2) for i in range(n)]
    def pairs(self,rows=None,source='LIVE',h=1):return diagnostic_rows(rows or self.rows(),self.now,'DAILY',h,source)
    def combo_pairs(self,n=120):
        pairs=self.pairs(self.rows(n))
        for i,(r,o,f) in enumerate(pairs):f.update(VWAP=o['durum']=='BASARILI',HACIM=o['durum']=='BASARILI',RSI=o['durum']=='BASARILI')
        return pairs
    def report(self,pairs=None):return combination_report(pairs or self.combo_pairs(),[('VWAP','HACIM')],'LIVE')['VWAP+HACIM']
    def error(self,updates=None,features=None,record=None):
        r=record or self.fixture.row(61,False);r['fiyat']=100;r['hedef']=110;r['stop']=95
        r['analiz'].update(updates or {});f=evidence_features(r,'DAILY');f.update(features or {})
        return decision_error((r,r['sonuc_1g'],f),'DAILY',performance_source(r),1)
    def test_combination_success_metrics(self):
        report=self.report();self.assertEqual(report['sample_count'],60);self.assertEqual(report['different_days'],8)
        self.assertEqual(report['success_rate'],1);self.assertEqual(report['median_return'],4);self.assertEqual(report['trimmed_mean'],4)
        self.assertEqual((report['target_hit_rate'],report['stop_hit_rate']),(1,0));self.assertTrue(report['strong'])
    def test_combination_minimum_samples(self):
        report=self.report(self.combo_pairs(98));self.assertIsNone(report['success_rate']);self.assertFalse(report['strong']);self.assertEqual(report['shadow_contribution_proposal'],0)
    def test_combination_minimum_days(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:r['zaman']='2026-09-01T19:00:00+03:00';r['sinyal_zamani']=r['zaman']
        report=self.report(pairs);self.assertIsNone(report['success_rate']);self.assertFalse(report['strong'])
    def test_combination_requires_control_group(self):
        report=self.report(self.combo_pairs()[:60]);self.assertFalse(report['strong']);self.assertEqual(report['shadow_contribution_proposal'],0)
    def test_configurable_combination_limits(self):
        with patch.dict(os.environ,{'MIN_COMBINATION_SAMPLES':'80','MIN_COMBINATION_DAYS':'10','MAX_CRITERION_COMBINATIONS':'12'}):self.assertEqual(combination_limits(),(80,10,12))
        with patch.dict(os.environ,{'MIN_COMBINATION_SAMPLES':'20'}),self.assertRaises(ValueError):combination_limits()
    def test_unknown_does_not_become_control(self):
        pairs=self.combo_pairs();pairs[0][2]['VWAP']=None
        report=self.report(pairs);self.assertEqual(report['unknown_count'],1);self.assertEqual(report['sample_count'],59);self.assertEqual(report['without']['sample_count'],60)
    def test_catalog_cap_and_cross_family(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:f.update(SMA_TREND=True,EMA_TREND=True,MACD=True,MOMENTUM=True)
        catalog=combination_catalog(pairs);self.assertLessEqual(len(catalog),64)
        self.assertFalse(any('SMA_TREND' in c and 'EMA_TREND' in c for c in catalog))
        self.assertTrue(any(len(c)==3 for c in catalog))
    def test_catalog_does_not_select_using_future_returns(self):
        pairs=self.combo_pairs();catalog=combination_catalog(pairs)
        for r,o,f in pairs:o['getiri_yuzde']=999;o['durum']='BASARISIZ'
        self.assertEqual(combination_catalog(pairs),catalog)
    def test_news_confirmation_pair_allowed(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:f.update(HABER_POZITIF=True,HABER_FIYAT_TEYIDI=True)
        self.assertIn(('HABER_POZITIF','HABER_FIYAT_TEYIDI'),combination_catalog(pairs))
    def test_small_shadow_reward_no_stack_no_main_change(self):
        pairs=self.combo_pairs();before=copy.deepcopy(pairs);report=self.report(pairs)
        self.assertEqual(report['shadow_contribution_proposal'],.25);self.assertEqual(report['double_count_policy'],'REPLACE_SINGLETONS_NO_STACK')
        self.assertFalse(report['applied']);self.assertEqual(pairs,before)
    def test_negative_shadow_proposal(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:f['VWAP']=not f['VWAP'];f['HACIM']=not f['HACIM']
        self.assertEqual(self.report(pairs)['shadow_contribution_proposal'],-.25)
    def test_regime_sector_distribution(self):
        report=self.report();self.assertEqual(sum(report['regime_distribution'].values()),60);self.assertEqual(sum(report['sector_distribution'].values()),60)
    def test_source_isolation(self):
        rows=self.rows();back=[dict(r,performance_source='BACKTEST',decision_asof=r['zaman'],model_created_at=r['zaman']) for r in self.rows()];shadow=[dict(r,performance_source='SHADOW') for r in self.rows()]
        for source in ('LIVE','BACKTEST','SHADOW'):self.assertEqual(len(self.pairs(rows+back+shadow,source)),120)
        self.assertEqual(len(evidence_rows(rows+back+shadow,self.now,'DAILY',1)),120)
    def test_source_default_and_unknown_fail_closed(self):
        self.assertEqual(performance_source({'model':'YARIN_SHADOW'}),'SHADOW');self.assertEqual(performance_source({'model':'BACKTEST'}),'BACKTEST')
        self.assertEqual(performance_source({'performance_source':'OTHER'}),'UNKNOWN')
    def test_source_reliability_proposals_remain_separate(self):
        live=self.report();back=combination_report(self.combo_pairs(),[('VWAP','HACIM')],'BACKTEST')['VWAP+HACIM']
        self.assertEqual(back['shadow_contribution_proposal'],live['shadow_contribution_proposal']*.5)
        with patch.dict(os.environ,{'PERFORMANCE_BACKTEST_RELIABILITY':'1.5'}),self.assertRaises(ValueError):source_reliability()
    def test_false_al_classification(self):self.assertIn('FALSE_AL',self.error()['failure_types'])
    def test_false_sat_requires_directional_model(self):
        r=self.fixture.row(61,False);r.update(model='ORTAK_AI',karar='SAT');r['nihai_karar']['karar']='SAT'
        self.assertIn('FALSE_SAT',self.error(record=r)['failure_types'])
    def test_no_fake_yarin_short(self):
        r=self.fixture.row(61,False);r.update(karar='SAT');r['nihai_karar']['karar']='SAT'
        self.assertNotIn('FALSE_SAT',self.error(record=r)['failure_types'])
    def test_stop_too_tight(self):self.assertIn('STOP_TOO_TIGHT',self.error(updates={'atr14':10})['failure_types'])
    def test_target_too_aggressive(self):self.assertIn('TARGET_TOO_AGGRESSIVE',self.error(updates={'atr14':2})['failure_types'])
    def test_volume_false_breakout(self):self.assertIn('VOLUME_FALSE_BREAKOUT',self.error(features={'BOLLINGER_KIRILIM':True,'HACIM':False})['failure_types'])
    def test_news_false_positive(self):self.assertIn('NEWS_FALSE_POSITIVE',self.error(features={'HABER_POZITIF':True,'HABER_FIYAT_TEYIDI':False})['failure_types'])
    def test_market_sector_missed(self):
        error=self.error(features={'PIYASA_NEGATIF':True,'SEKTOR_ZAYIF':True});self.assertIn('MARKET_CONTEXT_MISSED',error['failure_types']);self.assertIn('SECTOR_CONTEXT_MISSED',error['failure_types'])
    def test_entry_timing_only_explicit_frozen(self):
        error=self.error(updates={'gun_ici_sinyal_yasi_dk':30,'entry_confirmation':False});self.assertIn('LATE_ENTRY',error['failure_types']);self.assertIn('EARLY_ENTRY',error['failure_types'])
    def test_stale_data_error(self):
        r=self.fixture.row(61,False);r['teknik_gostergeler']['stale']=True
        self.assertIn('STALE_DATA_ERROR',self.error(record=r)['failure_types'])
    def test_unknown_and_error_metadata(self):
        r=self.fixture.row(61,False);r['karar']='BEKLE';r['nihai_karar'].update(karar='BEKLE',model_version='VERSION_AT_SIGNAL')
        error=self.error(record=r);self.assertIn('UNKNOWN',error['failure_types']);self.assertEqual(error['model_version'],'VERSION_AT_SIGNAL')
        for key in ('symbol','signal_time','signal_type','decision','score','confidence','target','stop','actual_result','failure_type','main_reason','missed_risk','misleading_criteria','market_regime','sector','news_context'):self.assertIn(key,error)
    def test_success_has_no_failure_log(self):
        r=self.fixture.row();self.assertIsNone(decision_error((r,r['sonuc_1g'],evidence_features(r,'DAILY')),'DAILY','LIVE',1))
    def test_confidence_calibration_warning(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:r['nihai_karar']['confidence']=65 if o['durum']=='BASARILI' else 85
        cal=calibration_report(pairs);self.assertTrue(cal['confidence_warnings']);self.assertFalse(cal['thresholds_changed'])
    def test_confirmation_calibration_warning(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:r['nihai_karar']['teyit_sayisi']=3 if o['durum']=='BASARILI' else 6
        self.assertTrue(calibration_report(pairs)['confirmation_warnings'])
    def test_calibration_low_sample_no_warning(self):self.assertFalse(calibration_report(self.combo_pairs()[:20])['confidence_warnings'])
    def health(self,pairs=None,current=None):
        pairs=pairs or self.combo_pairs();return algorithm_health([r for r,o,f in pairs],{'LIVE':pairs,'BACKTEST':[],'SHADOW':[]},current or self.now,'DAILY','VERSION',{})
    def test_health_low_sample(self):self.assertEqual(self.health(self.combo_pairs()[:20])['health_status'],'YETERSIZ_VERI')
    def test_health_multiple_metrics(self):
        pairs=self.combo_pairs();first=self.health(pairs)
        for r,o,f in pairs:o.update(stop_oldu=True,hedefe_ulasti=False)
        second=self.health(pairs);self.assertLess(second['health_score'],first['health_score'])
    def test_model_drift_disjoint_periods(self):
        pairs=self.combo_pairs(160);at=datetime(2026,9,1,19,tzinfo=ISTANBUL)
        old_days=self.fixture.days;recent=[];day=datetime(2026,10,1,19,tzinfo=ISTANBUL)
        while len(recent)<8:
            if day.weekday()<5:recent.append(day)
            day+=timedelta(days=1)
        for i,(r,o,f) in enumerate(pairs):
            when=old_days[i%8] if i<80 else recent[i%8];r['zaman']=when.isoformat();r['sinyal_zamani']=r['zaman'];r['nihai_karar']['updated_at']=when.isoformat();o['observed_at']=(when+timedelta(days=1)).isoformat();o.update(durum='BASARILI' if i<80 else 'STOP',getiri_yuzde=4 if i<80 else -2,yon_getirisi=4 if i<80 else -2)
        health=self.health(pairs);self.assertTrue(health['model_drift']['assessed']);self.assertEqual(health['model_drift']['warning'],'MODEL_DRIFT')
    def test_performance_curve_no_fake_small_percent(self):
        health=self.health();self.assertEqual(set(health['performance_curve']),{'5','20','60'});self.assertIsNone(health['performance_curve']['5']['success_rate'])
    def test_regime_sector_news_error_breakdown(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:r['haber_metadata']={'category':'SOZLESME','confidence':90,'observed_at':r['zaman']}
        health=self.health(pairs);self.assertEqual(health['error_breakdown']['sektor']['BANKA']['error_rate'],1)
        self.assertEqual(health['error_breakdown']['piyasa_rejimi']['DUSUS']['false_al_rate'],1)
        self.assertIn('SOZLESME',health['error_breakdown']['news'])
    def test_small_sector_rates_suppressed(self):self.assertIsNone(self.health(self.combo_pairs()[:20])['error_breakdown']['sektor']['TEKNOLOJI']['error_rate'])
    def test_mfe_mae_long(self):
        metrics=excursion_metrics([{'high':105,'low':98},{'high':112,'low':94}],100,110,95)
        self.assertEqual((metrics['mfe_pct'],metrics['mae_pct']),(12,-6));self.assertEqual(metrics['mfe_before_stop_pct'],5);self.assertEqual(metrics['mae_before_target_pct'],-2)
    def test_mfe_mae_short(self):
        metrics=excursion_metrics([{'high':102,'low':95},{'high':106,'low':88}],100,90,105,True)
        self.assertEqual((metrics['mfe_pct'],metrics['mae_pct']),(12,-6));self.assertEqual(metrics['mfe_before_stop_pct'],5);self.assertEqual(metrics['mae_before_target_pct'],-2)
    def test_touch_bar_is_not_ordered(self):
        m=excursion_metrics([{'high':112,'low':94}],100,110,95);self.assertEqual((m['mfe_before_stop_pct'],m['mae_before_target_pct']),(0,0));self.assertEqual(m['pre_contact_resolution'],'EXCLUDES_TOUCH_BAR')
    def test_missing_ohlc_excursions_unknown(self):self.assertIsNone(excursion_metrics([{'high':None,'low':94}],100,110,95)['mfe_pct'])
    def test_quality_report_sample_gate_and_values(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:o.update(mfe_pct=5,mae_pct=-2,target_approach_ratio=.5,mfe_before_stop_pct=1,mae_before_target_pct=-1)
        report=quality_report(pairs);self.assertEqual(report['mfe_pct']['median'],5);self.assertEqual(report['mae_pct']['median'],-2)
        self.assertIsNone(quality_report(pairs[:10])['mfe_pct']['median'])
    def test_daily_outcome_excursions_added_without_status_change(self):
        r={'zaman':'2026-10-06T18:15:00+03:00','fiyat':100,'hedef':110,'stop':95,'karar':'AL'}
        bars=[dict(timestamp='2026-10-07T18:15:00+03:00',open=100,high=112,low=98,close=110)]
        result=outcome(r,bars,1,self.now);self.assertEqual(result['durum'],'BASARILI');self.assertEqual(result['mfe_pct'],12);self.assertEqual(result['mae_pct'],-2)
    def test_intraday_outcome_excursions(self):
        from gun_ici_performans import outcome as intra
        at=datetime(2026,10,6,11,tzinfo=ISTANBUL);r={'sinyal_zamani':at.isoformat(),'giris_fiyati':100,'hedef':110,'stop':95,'karar':'AL'}
        bars=[dict(timestamp=at.isoformat(),open=100,high=112,low=98,close=110)]
        result=intra(r,bars,5,at+timedelta(minutes=5));self.assertEqual(result['durum'],'BASARILI');self.assertEqual(result['mfe_pct'],12)
    def test_snapshot_freeze_in_new_shadow(self):
        at=self.now;row=self.fixture.row(100,at=at);model={'created_at':(at-timedelta(days=1)).isoformat(),'training_end':(at-timedelta(days=1)).isoformat(),'mode':'DAILY','model_version':'FROZEN','weights':EVIDENCE_BASE}
        score=controlled_score(row,80,at,'DAILY',model);row['controlled_shadow']=copy.deepcopy(score);first=evidence_features(row,'DAILY')
        row['analiz'].update(rsi=0,hacim_orani=9999);row['teknik_gostergeler']['asof']=(at+timedelta(days=1)).isoformat()
        self.assertEqual(evidence_features(row,'DAILY'),first);self.assertEqual(score['criteria_snapshot']['model_version'],'FROZEN')
    def test_backtest_future_model_rejected(self):
        rows=self.rows();rows[0].update(performance_source='BACKTEST',model_created_at=(self.now+timedelta(days=1)).isoformat())
        self.assertFalse(self.pairs(rows,'BACKTEST'))
    def test_backtest_future_news_market_candles_rejected(self):
        r=self.fixture.row();r.update(performance_source='BACKTEST',haber_metadata={'observed_at':(self.now+timedelta(days=1)).isoformat(),'canonical_id':'future','kaynak':'KAP'},piyasa_baglami={'updated_at':(self.now+timedelta(days=1)).isoformat(),'rejim_score':100,'rejim_confidence':100})
        r['sonuc_1g']['observed_at']=(self.now+timedelta(days=1)).isoformat();self.assertFalse(self.pairs([r],'BACKTEST'))
        flags=evidence_features(r,'DAILY');self.assertIsNone(flags['KAP']);self.assertIsNone(flags['PIYASA_POZITIF'])
        r['teknik_gostergeler']['asof']=(self.now+timedelta(days=1)).isoformat();self.assertTrue(all(v is None for v in evidence_features(r,'DAILY').values()))
    def test_backtest_future_decision_asof_rejected(self):
        r=self.fixture.row();r.update(performance_source='BACKTEST',decision_asof=(self.now+timedelta(days=1)).isoformat());self.assertFalse(self.pairs([r],'BACKTEST'))
    def test_private_errors_and_public_health(self):
        result=decision_diagnostics(self.paths,self.rows(),self.now,'DAILY','V',{});private=json.loads((self.paths.runtime/'karar_hata_gunlugu.json').read_text())
        self.assertTrue(private['modes']['DAILY']);self.assertIn('health',result)
        public=(self.paths.public/'algoritma_saglik.json').read_text();self.assertNotIn('symbol',public);self.assertNotIn('signal_time',public)
    def test_private_error_idempotence(self):
        decision_diagnostics(self.paths,self.rows(),self.now,'DAILY','V',{});first=json.loads((self.paths.runtime/'karar_hata_gunlugu.json').read_text())
        decision_diagnostics(self.paths,self.rows(),self.now,'DAILY','V',{});second=json.loads((self.paths.runtime/'karar_hata_gunlugu.json').read_text());self.assertEqual(first,second)
    def test_modes_remain_separate_and_atomic(self):
        decision_diagnostics(self.paths,self.rows(),self.now,'DAILY','V',{})
        decision_diagnostics(self.paths,self.fixture.rows('INTRADAY'),self.now,'INTRADAY','I',{})
        for name in ('algoritma_saglik.json','kombinasyon_performansi.json'):
            self.assertEqual(set(json.loads((self.paths.public/name).read_text())['modes']),{'DAILY','INTRADAY'})
    def test_publish_adds_diagnostics_and_no_main_learning(self):
        rows=self.rows();before=copy.deepcopy(rows);result=controlled_publish(self.paths,rows,self.now,'DAILY')
        self.assertIn('diagnostics',result);self.assertFalse(result['learning_enabled']);self.assertEqual(rows,before)
    def test_incremental_cached_reports_no_new_network(self):
        rows=self.rows();controlled_publish(self.paths,rows,self.now,'DAILY')
        with patch('performans_motoru.decision_diagnostics',side_effect=AssertionError('No rebuild')),patch('performans_motoru.provider_history',side_effect=AssertionError('No network')):
            controlled_publish(self.paths,rows,self.now+timedelta(minutes=1),'DAILY')
    def test_static_api_private_log_not_served(self):
        from web_server import create_server
        decision_diagnostics(self.paths,self.rows(),self.now,'DAILY','V',{});server=create_server('127.0.0.1',0,data_paths=self.paths)
        threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        for name in ('algoritma_saglik.json','kombinasyon_performansi.json'):
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/data/{name}') as response:self.assertIn('DAILY',json.load(response)['modes'])
        with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/data/karar_hata_gunlugu.json')
    def test_worker_still_limits_provider_batch(self):
        rows=self.rows(10)
        for r in rows:
            r.update(model="ORTAK_AI",fiyat=100,hedef=110,stop=95)
            for h in (1,3,5,10,20,60):r['sonuc_'+str(h)+'g']=None
        atomic_json(self.paths.runtime/'ai_ogrenme_gecmisi.json',{'kayitlar':rows});provider=Mock(return_value=[])
        result=PerformansMotoru(self.paths,clock=lambda:self.now,history_provider=provider,batch_size=2).one_round()
        self.assertEqual(provider.call_count,2);self.assertEqual(result['sembol_sayisi'],2)
    def test_time_ordered_backtest_evaluation(self):
        row=self.fixture.row();row.update(performance_source='BACKTEST',decision_asof=row['zaman'],model_created_at=row['zaman']);signal=datetime.fromisoformat(row['zaman'])
        self.assertFalse(diagnostic_rows([row],signal+timedelta(hours=1),'DAILY',1,'BACKTEST'))
        self.assertEqual(len(diagnostic_rows([row],signal+timedelta(days=2),'DAILY',1,'BACKTEST')),1)
        before=evidence_features(row,'DAILY');row['sonuc_1g'].update(getiri_yuzde=10000,durum='BASARILI')
        self.assertEqual(evidence_features(row,'DAILY'),before)
    def test_future_news_cannot_supply_polarity_bonus(self):
        row=self.fixture.row();row['haber_metadata']={'canonical_id':'late','kaynak':'KAP','observed_at':(self.now+timedelta(days=1)).isoformat()}
        row['analiz']['haber_puani']=20;row['analiz']['makro_puani']=20;row['makro_asof']=(self.now+timedelta(days=1)).isoformat()
        flags=evidence_features(row,'DAILY');self.assertIsNone(flags['HABER_POZITIF']);self.assertIsNone(flags['MAKRO_POZITIF'])
    def test_future_context_not_used_for_error_breakdown(self):
        row=self.fixture.row();row['piyasa_baglami']={'updated_at':(self.now+timedelta(days=1)).isoformat(),'rejim_score':100,'rejim_confidence':100}
        pair=self.pairs([row])[0];self.assertEqual(pair[0]['piyasa_rejimi'],'BILINMIYOR');self.assertEqual(pair[0]['sektor'],'BILINMIYOR')
    def test_quality_stop_and_target_distance_metrics(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:r.update(fiyat=100,stop=99,hedef=120);r['analiz']['atr14']=2
        report=quality_report(pairs);self.assertEqual(report['stop_too_tight_rate'],1);self.assertEqual(report['median_stop_atr'],.5)
        self.assertEqual(report['median_target_atr'],10);self.assertEqual(report['target_too_aggressive_rate'],.5)
    def test_stale_failed_ohlc_logged_not_in_success_pool(self):
        row=self.fixture.row();row['teknik_gostergeler']['stale']=True;row['sonuc_1g'].update(durum='VERI_YETERSIZ',kalite_uyarilari=['OHLC_EKSIK'])
        result=decision_diagnostics(self.paths,[row],self.now,'DAILY','V',{})
        self.assertEqual(result['health']['live_sample_count'],0);self.assertEqual(result['error_counts']['LIVE']['STALE_DATA_ERROR'],1)
    def test_intraday_shadow_membership_is_separate(self):
        row=self.fixture.row(1,True,'INTRADAY');signal=datetime.fromisoformat(row['sinyal_zamani'])
        row['controlled_shadow_adayi']=True;row['controlled_shadow']={'created_at':signal.isoformat(),'training_end':(signal-timedelta(days=1)).isoformat(),'eligible_for_evaluation':True}
        self.assertEqual(len(diagnostic_rows([row],self.now,'INTRADAY',60,'SHADOW')),1)
        self.assertEqual(len(diagnostic_rows([row],self.now,'INTRADAY',60,'LIVE')),1)
        row['controlled_shadow']['training_end']=(signal+timedelta(days=1)).isoformat();self.assertFalse(diagnostic_rows([row],self.now,'INTRADAY',60,'SHADOW'))
    def test_outcomes_keep_signal_version_and_source(self):
        row={'zaman':'2026-10-06T18:15:00+03:00','fiyat':100,'hedef':110,'stop':95,'karar':'AL','model':'BACKTEST','model_version':'AT_SIGNAL'}
        bars=[dict(timestamp='2026-10-07T18:15:00+03:00',open=100,high=112,low=98,close=110)]
        result=outcome(row,bars,1,self.now);self.assertEqual(result['model_version'],'AT_SIGNAL');self.assertEqual(result['performance_source'],'BACKTEST')
    def test_empty_live_cannot_be_healthy_from_backtest(self):
        health=algorithm_health([],{'LIVE':[],'BACKTEST':self.combo_pairs(),'SHADOW':self.combo_pairs()},self.now,'DAILY','V',{})
        self.assertEqual(health['health_status'],'YETERSIZ_VERI');self.assertIsNone(health['main_model_success'])
    def test_public_health_recreated_when_missing(self):
        rows=self.rows();controlled_publish(self.paths,rows,self.now,'DAILY');(self.paths.public/'algoritma_saglik.json').unlink()
        controlled_publish(self.paths,rows,self.now+timedelta(minutes=1),'DAILY');self.assertTrue((self.paths.public/'algoritma_saglik.json').exists())
    def test_source_weights_config_change_rebuilds_after_interval(self):
        rows=self.rows();first=controlled_publish(self.paths,rows,self.now,'DAILY')
        with patch.dict(os.environ,{'PERFORMANCE_BACKTEST_RELIABILITY':'.25'}):
            second=controlled_publish(self.paths,rows,self.now+timedelta(hours=2),'DAILY')
        self.assertNotEqual(first['model_version'],second['model_version'])
    def test_days_are_counted_in_istanbul_timezone(self):
        pairs=self.combo_pairs()[:2]
        pairs[0][0]['sinyal_zamani']='2026-09-01T23:00:00+00:00'
        pairs[1][0]['sinyal_zamani']='2026-09-02T10:00:00+03:00'
        self.assertEqual(diagnostic_stats(pairs)['different_days'],1)
    def test_unknown_backtest_provenance_not_trusted(self):
        row=self.fixture.row();row['performance_source']='BACKTEST'
        self.assertFalse(self.pairs([row],'BACKTEST'))
    def test_negative_news_technical_deterioration_combination(self):
        pairs=self.combo_pairs()
        for r,o,f in pairs:f.update(HABER_NEGATIF=o['durum']=='BASARILI',MACD=o['durum']!='BASARILI')
        key=('!MACD','HABER_NEGATIF');self.assertIn(key,combination_catalog(pairs))
        report=combination_report(pairs,[key],'LIVE')['!MACD+HABER_NEGATIF'];self.assertEqual(report['sample_count'],60);self.assertTrue(report['strong'])
    def test_stale_age_detected_even_without_explicit_flag(self):
        row=self.fixture.row(61,False);row['teknik_gostergeler']['data_time']='2026-01-01T19:00:00+03:00';row['teknik_gostergeler']['stale']=False
        self.assertIn('STALE_DATA_ERROR',self.error(record=row)['failure_types'])
