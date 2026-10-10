import copy
import json
import os
import tempfile
import unittest
from datetime import datetime,timedelta
from unittest.mock import patch

from ai_karar_motoru import ISTANBUL
from sinyal_performansi import VERSION,RELIABILITY
from veri_yollari import DataPaths
from kullanici_kayitlari import atomic_json
import yarin_kalibrasyon as learning


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.paths=DataPaths({'BIST_DATA_DIR':self.temp.name});self.paths.ensure()
        self.now=datetime(2026,10,7,18,30,tzinfo=ISTANBUL)
        self.row={'sembol':'THYAO','fiyat':100,'rsi':45}
        self.enterContext(patch.dict(os.environ,{'TOP10_LEARNING_ENABLED':'true'}))
    def stat(self,n=300,win=.5,ret=0):
        positive=int(round(n*win))
        return {'sample_size':n,'sample_count':n,'completed':n,'positive':positive,'negative':n-positive,'neutral':0,
                'success_rate':positive/n,'mean_return':ret,'median_return':ret,'mean_mfe':2,'mean_mae':-1,'mfe_samples':n,'mae_samples':n}
    def model(self,n=300,win=.8,ret=2,indicator='RSI',condition='40-49',source='YARIN_TOP10'):
        entry=self.stat(n,win,ret);baseline=self.stat(max(n,300))
        return {'status':'READY','asof':(self.now-timedelta(hours=1)).isoformat(),
                'index':{(indicator,condition,source,h):dict(entry) for h in (1,3,5)},
                'baselines':{'YARIN_TOP10':{str(h):dict(baseline) for h in (1,3,5)},'ALL':{str(h):dict(baseline) for h in (1,3,5)}}}
    def adjustment(self,model=None,row=None):
        return learning.top10_learning_adjustment(row or self.row,model or self.model(),self.now)
    def delta(self,model=None,row=None):return self.adjustment(model,row)['learning_adjustment']
    def test_insufficient(self):self.assertEqual(self.delta(self.model(n=29)),0)
    def test_low_scaling(self):self.assertAlmostEqual(self.delta(self.model(n=30)),self.delta(self.model())*.25)
    def test_medium_scaling(self):self.assertAlmostEqual(self.delta(self.model(n=100)),self.delta(self.model())*.6)
    def test_high_scaling(self):self.assertEqual(self.adjustment()['learning_confidence_summary'],{'HIGH':3})
    def test_positive_edge(self):self.assertGreater(self.delta(),0)
    def test_negative_edge(self):self.assertLess(self.delta(self.model(win=.2,ret=-2)),0)
    def test_identical_baseline_is_zero(self):self.assertEqual(self.delta(self.model(win=.5,ret=0)),0)
    def test_baseline_insufficient(self):
        model=self.model();model['baselines']['YARIN_TOP10']={str(h):self.stat(29) for h in (1,3,5)}
        self.assertEqual(self.delta(model),0)
    def test_d1_primary(self):
        full=self.delta();model=self.model();model['index']={k:v for k,v in model['index'].items() if k[-1]==1}
        self.assertAlmostEqual(self.delta(model),full*.8)
    def test_d3_auxiliary(self):
        model=self.model();model['index']={k:v for k,v in model['index'].items() if k[-1] in (1,3)}
        self.assertAlmostEqual(self.delta(model),self.delta()*.95)
    def test_d5_auxiliary(self):
        model=self.model();model['index']={k:v for k,v in model['index'].items() if k[-1] in (1,5)}
        self.assertAlmostEqual(self.delta(model),self.delta()*.85)
    def test_auxiliary_without_d1_zero(self):
        model=self.model();model['index']={k:v for k,v in model['index'].items() if k[-1]!=1};self.assertEqual(self.delta(model),0)
    def test_long_horizons_ignored(self):
        model=self.model()
        for h in (10,20,60):model['index'][('RSI','40-49','YARIN_TOP10',h)]=self.stat(win=.1,ret=-99)
        self.assertEqual(self.delta(model),self.delta())
    def test_signal_specific_priority(self):
        model=self.model()
        for h in (1,3,5):model['index'][('RSI','40-49','ALL',h)]=self.stat(win=.1,ret=-2)
        self.assertEqual(self.delta(model),self.delta())
    def test_general_fallback_halved(self):self.assertEqual(self.delta(self.model(source='ALL')),self.delta()*.5)
    def test_fallback_explained(self):self.assertEqual(self.adjustment(self.model(source='ALL'))['learning_reasons'][0]['evidence'][0]['source'],'ALL')
    def test_missing_feature_zero(self):self.assertEqual(self.delta(row={'sembol':'THYAO','fiyat':100}),0)
    def test_future_feature_zero(self):self.assertEqual(self.delta(row=dict(self.row,feature_timestamp=(self.now+timedelta(minutes=1)).isoformat())),0)
    def test_missing_price_zero(self):self.assertEqual(self.delta(row=dict(self.row,fiyat=None)),0)
    def test_pending_not_used(self):
        model=self.model()
        for entry in model['index'].values():entry['completed']=0
        self.assertEqual(self.delta(model),0)
    def test_unverified_not_used(self):
        model=self.model()
        for entry in model['index'].values():entry['legacy_unverified']=True
        self.assertEqual(self.delta(model),0)
    def test_risk_damps_bonus(self):
        model=self.model()
        for entry in model['index'].values():entry.update(mean_mfe=.1,mean_mae=-10)
        self.assertLess(self.delta(model),self.delta()/50)
    def test_outlier_mean_cannot_dominate(self):
        model=self.model(win=.5,ret=0)
        for entry in model['index'].values():entry['mean_return']=999999
        self.assertLess(self.delta(model),learning.TOP10_FAMILY_CAP/2)
    def test_family_averages_correlated_inputs(self):
        model=self.model();row=dict(self.row,macd=2,signal=1,hist=1,hist_onceki=.5,momentum15=2)
        conditions={'MACD_SIGN':'POSITIVE','MACD_SIGNAL':'ABOVE','HIST_SIGN':'POSITIVE','HIST_TREND':'IMPROVING','MOMENTUM':'POSITIVE'}
        for indicator,condition in conditions.items():
            for h in (1,3,5):model['index'][(indicator,condition,'YARIN_TOP10',h)]=self.stat(win=.8,ret=2)
        self.assertEqual(self.delta(model,row),self.delta())
    def test_combination_replaces_components(self):
        model=self.model(indicator='COMBO_RSI_MACD_VOLUME',condition='CONFIRMED')
        for indicator,condition in (('RSI','40-49'),('MACD_SIGNAL','ABOVE'),('VOLUME','150-199')):
            for h in (1,3,5):model['index'][(indicator,condition,'YARIN_TOP10',h)]=self.stat(win=.8,ret=2)
        result=self.adjustment(model,dict(self.row,macd=2,signal=1,hacim_orani=180))
        self.assertLessEqual(abs(result['learning_adjustment']),learning.TOP10_COMBINATION_CAP)
        self.assertTrue(any(r.get('suppressed_by') for r in result['learning_reasons']))
    def test_weaker_combo_does_not_replace_high_confidence_family(self):
        model=self.model()
        for h in (1,3,5):model['index'][('COMBO_RSI_MACD','CONFIRMED','YARIN_TOP10',h)]=self.stat(30,win=.8,ret=2)
        result=self.adjustment(model,dict(self.row,macd=2,signal=1))
        self.assertEqual(result['learning_adjustment'],self.delta())
    def test_total_caps_both_directions(self):
        row=dict(self.row,sma20=90,sma50=80,hacim_orani=180,vwap20=90,atr14=1,nihai_karar={'teyit_sayisi':6,'teyit_toplam':6})
        from sinyal_performansi import indicator_conditions
        for win,ret in ((1.,10.),(0.,-10.)):
            model=self.model(win=win,ret=ret)
            for indicator,condition in indicator_conditions(row).items():
                if indicator.startswith('COMBO'):continue
                for h in (1,3,5):model['index'][(indicator,condition,'YARIN_TOP10',h)]=self.stat(win=win,ret=ret)
            result=self.adjustment(model,row);self.assertEqual(abs(result['learning_adjustment']),learning.TOP10_MAX_ADJUSTMENT)
            self.assertAlmostEqual(sum(r['contribution'] for r in result['learning_reasons']),result['learning_adjustment'],places=5)
    def test_aggregation_exception_fails_safe(self):
        with patch('sinyal_performansi.indicator_conditions',side_effect=RuntimeError('broken')):self.assertEqual(self.delta(),0)
    def test_ranker_exception_fails_safe(self):
        order=[(80,dict(self.row)),(79,dict(self.row,sembol='ASELS'))]
        with patch.object(learning,'top10_learning_adjustment',side_effect=RuntimeError('broken')):result=learning.rank_with_learning(order,self.model(),self.now)
        self.assertEqual([score for score,row in result],[80,79]);self.assertTrue(all(row['learning_adjustment']==0 for score,row in result))
    def test_disabled_ranking_identical(self):
        order=[(80,dict(self.row)),(79,dict(self.row,sembol='ASELS'))]
        with patch.dict(os.environ,{'TOP10_LEARNING_ENABLED':'false'}):result=learning.rank_with_learning(order,self.model(),self.now)
        self.assertEqual([score for score,row in result],[80,79]);self.assertEqual([row['sembol'] for score,row in result],['THYAO','ASELS'])
    def test_base_rank_change_version_and_reasons(self):
        rows=[(80,dict(self.row,rsi=90)),(79.5,dict(self.row,sembol='ASELS'))]
        result=learning.rank_with_learning(rows,self.model(),self.now);winner=result[0][1]
        self.assertEqual(winner['base_score'],79.5);self.assertEqual(winner['base_rank'],2);self.assertEqual(winner['learned_rank'],1)
        self.assertEqual(winner['rank_change'],1);self.assertEqual(winner['learning_version'],learning.TOP10_LEARNING_VERSION)
        self.assertTrue(winner['learning_reasons']);self.assertAlmostEqual(result[0][0],79.5+winner['learning_adjustment'])
    def test_clamp(self):
        result=learning.rank_with_learning([(99.9,dict(self.row))],self.model(),self.now)[0][1]
        self.assertEqual(result['final_ranking_score'],100);self.assertEqual(result['base_score'],99.9)
    def report(self):
        model=self.model();rows=[]
        for (indicator,condition,source,h),stat in model['index'].items():rows.append(dict(stat,indicator=indicator,condition=condition,signal_type=source,horizon=h,period='ALL'))
        at=(self.now-timedelta(hours=1)).isoformat()
        return {'version':VERSION,'analysis_only':True,'reliability_thresholds':RELIABILITY,'updated_at':at,
                'indicator_analysis':{'rows':rows,'updated_at':at,'analysis_only':True},
                'periods':{'ALL':{'signals':{'YARIN_TOP10':model['baselines']['YARIN_TOP10']},'overall':{'ALL':model['baselines']['ALL']}}}}
    def test_valid_context_uses_single_cache_read(self):
        with patch('sinyal_performansi.read_report',return_value=self.report()) as read:
            context=learning.top10_learning_context(self.paths,self.now)
            self.assertEqual(context['status'],'READY');self.delta(context);self.delta(context);read.assert_called_once()
    def test_corrupt_cache(self):
        path=self.paths.public_file('sinyal_performansi.json');path.write_text('{broken')
        self.assertEqual(learning.top10_learning_context(self.paths,self.now)['status'],'CACHE_ERROR')
    def test_cache_read_exception(self):
        with patch('sinyal_performansi.read_report',side_effect=OSError('unavailable')):self.assertEqual(learning.top10_learning_context(self.paths,self.now)['status'],'CACHE_ERROR')
    def test_future_report(self):
        report=self.report();report['updated_at']=(self.now+timedelta(minutes=1)).isoformat()
        with patch('sinyal_performansi.read_report',return_value=report):self.assertNotEqual(learning.top10_learning_context(self.paths,self.now)['status'],'READY')
    def test_stale_report(self):
        report=self.report();report['updated_at']=(self.now-timedelta(days=8)).isoformat()
        with patch('sinyal_performansi.read_report',return_value=report):self.assertEqual(learning.top10_learning_context(self.paths,self.now)['status'],'STALE_REPORT')
    def test_duplicate_evidence_not_double_counted(self):
        report=self.report();report['indicator_analysis']['rows']+=report['indicator_analysis']['rows'][:1]
        with patch('sinyal_performansi.read_report',return_value=report):self.assertEqual(learning.top10_learning_context(self.paths,self.now)['status'],'CACHE_ERROR')
    def test_history_unchanged(self):
        path=self.paths.runtime_file('tahmin_gecmisi.json');atomic_json(path,{'keep':'unique'});before=path.read_bytes()
        self.adjustment();learning.rank_with_learning([(80,dict(self.row))],self.model(),self.now)
        self.assertEqual(path.read_bytes(),before)
    def test_nested_future_snapshot(self):
        row=dict(self.row,indicator_snapshot={'captured_at':self.now.isoformat(),'inputs':{'fiyat':100,'rsi':45},'technical':{'asof':(self.now+timedelta(seconds=1)).isoformat()}})
        self.assertEqual(self.delta(row=row),0)
    def test_context_future_guard_at_scoring_time(self):
        model=self.model();model['asof']=(self.now+timedelta(minutes=1)).isoformat();self.assertEqual(self.delta(model),0)
    def test_context_stale_guard_at_scoring_time(self):
        model=self.model()
        model['asof']=(self.now-timedelta(days=learning.TOP10_MAX_CACHE_AGE_DAYS,seconds=1)).isoformat()
        result=self.adjustment(model)
        self.assertEqual(result['learning_adjustment'],0)
        self.assertEqual(result['learning_status'],'STALE_REPORT')
        self.assertEqual(result['learning_reasons'],[])
    def test_context_age_boundary_remains_usable(self):
        model=self.model()
        model['asof']=(self.now-timedelta(days=learning.TOP10_MAX_CACHE_AGE_DAYS)).isoformat()
        self.assertEqual(self.delta(model),self.delta())
    def test_reused_context_expiry_preserves_base_ranking(self):
        with patch('sinyal_performansi.read_report',return_value=self.report()) as read:
            context=learning.top10_learning_context(self.paths,self.now)
            rows=[(80,dict(self.row,rsi=90)),(79.5,dict(self.row,sembol='ASELS'))]
            later=self.now+timedelta(days=learning.TOP10_MAX_CACHE_AGE_DAYS)
            result=learning.rank_with_learning(rows,context,later)
        read.assert_called_once()
        self.assertEqual([score for score,row in result],[80,79.5])
        self.assertEqual([row['sembol'] for score,row in result],['THYAO','ASELS'])
        self.assertTrue(all(row['learning_status']=='STALE_REPORT' for score,row in result))
        self.assertTrue(all(row['rank_change']==0 for score,row in result))
    def test_unverified_candidate_snapshot(self):
        self.assertEqual(self.delta(row=dict(self.row,indicator_snapshot={'inputs':{'rsi':45}})),0)
    def real_ranking(self,rows,enabled=True):
        import bist_bot
        with patch.dict(os.environ,{'TOP10_LEARNING_ENABLED':'true' if enabled else 'false'}),patch.object(bist_bot,'yarin_potansiyel_hesapla',side_effect=lambda r:r['old_score']),patch('performans_motoru.controlled_context',return_value={}),patch('performans_motoru.controlled_score',return_value={}),patch('teknik_gostergeler.shadow',return_value={}),patch('piyasa_baglami.effects',return_value={'piyasa_baglami_etkisi':0}),patch('ai_karar_motoru.attach_final_decision'):
            return bist_bot.yarin_top10_listesi(rows,kalibrasyon={'learning_enabled':False},piyasa={},learning_context=self.model())
    def test_real_base_ranker_disabled_and_ties(self):
        rows=[dict(self.row,sembol='AAA',old_score=80,hacim_orani=100),dict(self.row,sembol='BBB',old_score=80,hacim_orani=180),dict(self.row,sembol='CCC',old_score=81,hacim_orani=90)]
        output=self.real_ranking(rows,False);self.assertEqual([row['sembol'] for _,row in output],['CCC','BBB','AAA'])
        self.assertEqual([score for score,row in output],[81,80,80])
    def test_real_base_ranker_eligibility_not_bypassed(self):
        rows=[dict(self.row,sembol='AAA',old_score=54),dict(self.row,sembol='BBB',old_score=80)]
        output=self.real_ranking(rows);self.assertEqual([row['sembol'] for _,row in output],['BBB'])
        self.assertEqual(output[0][1]['final_puan'],80);self.assertEqual(output[0][1]['base_score'],80)
    def test_snapshot_base_learned_metadata_and_immutable_archive(self):
        import bist_bot
        from performans_motoru import PerformansMotoru
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return self.now
        rows=[dict(self.row,sembol='AAA',old_score=80,rsi=90),dict(self.row,sembol='BBB',old_score=79.5)]
        with patch.dict(os.environ,{'BIST_DATA_DIR':str(self.paths.root)}),patch.object(bist_bot,'datetime',Clock),patch.object(bist_bot,'YARIN_TOP10_FILE',str(self.paths.public_file('yarin_top10.json'))),patch.object(bist_bot,'YARIN_TOP10_ARSIV_DIR',str(self.paths.archives)),patch.object(bist_bot,'yarin_top10_listesi') as ranked,patch('yarin_kalibrasyon.top10_learning_context',return_value=self.model()):
            ranked.side_effect=lambda items,**kwargs:learning.rank_with_learning([(a['old_score'],a) for a in sorted(items,key=lambda r:r['old_score'],reverse=True)],self.model(),self.now)
            for r in rows:r.update(ham_puan=r['old_score'],final_puan=r['old_score'],shadow_puan=r['old_score'])
            first=bist_bot.yarin_top10_kilitli_kaydet(rows,2)
            self.assertIsNotNone(first);self.assertEqual(first['base_top10'][0]['sembol'],'AAA');self.assertEqual(first['top10'][0]['sembol'],'BBB')
            prediction=first['top10'][0]['tahmin'];self.assertEqual(prediction['base_rank'],2);self.assertEqual(prediction['learned_rank'],1)
            self.assertIn('learning_reasons',prediction);self.assertEqual(len(first['learning_comparison']),2)
            file=self.paths.archives/'2026-10-07.json';before=file.read_bytes()
            bist_bot.yarin_top10_kilitli_kaydet([dict(self.row,old_score=95)],1);self.assertEqual(file.read_bytes(),before)
            records=PerformansMotoru(self.paths).snapshot_records({})
            self.assertEqual(len([r for r in records if r['model']=='YARIN_LEARNING_BASELINE']),2)
    def save_positive_pool(self,enabled):
        import bist_bot
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return self.now
        candidates=[dict(self.row,sembol='S'+str(i),rsi=45 if i==10 else 55,
                         ham_puan=80,final_puan=80,shadow_puan=80,
                         positive_opportunity={'future_opportunity_score':80-i*.05}) for i in range(11)]
        pool={'positive_count':11,'analyzed_count':11,'adaylar':copy.deepcopy(candidates),'eligible_symbols':[r['sembol'] for r in candidates]}
        with patch.dict(os.environ,{'BIST_DATA_DIR':str(self.paths.root),'TOP10_LEARNING_ENABLED':'true' if enabled else 'false'}),patch.object(bist_bot,'datetime',Clock),patch.object(bist_bot,'YARIN_TOP10_FILE',str(self.paths.public_file('yarin_top10.json'))),patch.object(bist_bot,'YARIN_TOP10_ARSIV_DIR',str(self.paths.archives)),patch.object(bist_bot,'yarin_top10_listesi',return_value=[(80,r) for r in candidates[:10]]),patch('yarin_kalibrasyon.top10_learning_context',return_value=self.model()),patch('pozitif_kapanis.build_pool',return_value=pool),patch('pozitif_kapanis.enrich_closing_sources'):
            return bist_bot.yarin_top10_kilitli_kaydet(candidates,11,pozitif_kapanis=True)
    def test_positive_pool_learning_can_promote_eleventh_candidate(self):
        snapshot=self.save_positive_pool(True);self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot['top10'][0]['sembol'],'S10')
        self.assertEqual(snapshot['top10'][0]['base_rank'],11)
        self.assertEqual([r['sembol'] for r in snapshot['base_top10']],['S'+str(i) for i in range(10)])
        original=next(r for r in snapshot['pozitif_havuz']['adaylar'] if r['sembol']=='S10')
        self.assertEqual(original['positive_opportunity']['future_opportunity_score'],79.5)
    def test_positive_pool_disabled_preserves_original_selection(self):
        snapshot=self.save_positive_pool(False);self.assertIsNotNone(snapshot)
        self.assertEqual([r['sembol'] for r in snapshot['top10']],['S'+str(i) for i in range(10)])
        self.assertTrue(all(r['learning_adjustment']==0 for r in snapshot['top10']))
    def test_independent_shadow_models_do_not_conflict_as_duplicates(self):
        from sinyal_performansi import unique_records
        one=dict(self.row,id='base',tarih=self.now.isoformat(),kaynak='IMMUTABLE_YARIN_SNAPSHOT',model='YARIN_BASELINE')
        two=dict(one,id='control',model='YARIN_LEARNING_BASELINE')
        rows,duplicates,malformed=unique_records([one,two])
        self.assertEqual(len(rows),2);self.assertEqual(duplicates,0);self.assertFalse(any(conflict for row,conflict in rows))
    def test_comparison_cohort_never_feeds_learning_adjustment(self):
        from sinyal_performansi import aggregate_indicators
        row=dict(self.row,id='base',zaman=(self.now-timedelta(days=3)).isoformat(),model='YARIN_LEARNING_BASELINE',hedef=110,stop=90)
        report=aggregate_indicators([row],self.now)
        self.assertTrue(all(r['completed']==0 for r in report['rows']))
        self.assertTrue(any(r['excluded'].get('NON_LIVE') for r in report['rows']))
    def test_robust_excursion_median_prevents_mean_outlier_dominance(self):
        model=self.model()
        for entry in model['index'].values():entry.update(mean_mae=-999999,mean_mfe=999999,median_mae=-1,median_mfe=2)
        self.assertEqual(self.delta(model),self.delta())
