"""Prospective capture and read-only observational candidate regressions."""
import copy,json,tempfile,threading,unittest,urllib.request,urllib.error
from datetime import datetime,timedelta
from unittest.mock import patch,Mock
from pathlib import Path
import sinyal_performansi as m
from ai_karar_motoru import ISTANBUL,HORIZONS
from veri_yollari import DataPaths
from kullanici_kayitlari import atomic_json,RecordError
from gorev_hatalari import TaskIssue
import test_sinyal_performansi as daily_tests
import test_intraday_signal_performance as intraday_tests


class CandidateTests(unittest.TestCase):
    def setUp(self):
        daily_tests.AnalysisTests.setUp(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.env=patch.dict('os.environ',{'INDICATOR_PERFORMANCE_ENABLED':'true','BIST_DATA_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
        self.time_mock=patch.object(m,'datetime',wraps=datetime);clock=self.time_mock.start();clock.now.return_value=self.now;self.addCleanup(self.time_mock.stop)
        self.row['teknik_gostergeler']={'mode':'TOMORROW','asof':self.at.isoformat(),'data_time':self.at.replace(hour=18,minute=10).isoformat(),
            'closing':{'rsi':55,'sma20':110,'sma50':100},'obv':{'value':300},'bollinger':{'middle':100},'momentum':{'short_pct':2,'close_position_pct':75}}
        self.row['criteria_snapshot']={'captured_at':self.at.isoformat(),'flags':{'RSI':True,'MACD':False,'HACIM':True,'SMA_TREND':True}}
        self.row['indicator_evidence']=self.capture()
    def capture(self,row=None):return m.capture_feature_evidence(row or self.row,self.at.isoformat(),location=self.location)
    def examples(self,rows=None,current=None):return m.indicator_examples(rows or [self.row],current or self.now,self.holiday)[0]
    def example(self,active=True,success=True,h='1',regime='BULL',age=0):
        return {'id':'x','symbol':'THYAO','at':(self.now-timedelta(days=age)).isoformat(),'family':'AGGRESSIVE_BUY','direction':'BUY','horizon':h,
            'features':{k:{'available':True,'active':active,'state':'POSITIVE' if active else 'NEUTRAL'} for k in m.INDICATOR_IDS},
            'regime':regime,'sector':'LEADING','pending':False,'return':5 if success else -3,'raw_return':5 if success else -3,'mfe':8,'mae':-4,'success':success}
    def candidate(self,examples):return next(r for r in m.aggregate_indicator_evidence(examples,self.now)['rows'] if r['indicator_id']=='RSI')
    def cohort(self,n=100,negative=False):return [self.example(True,not negative) for _ in range(n)]+[self.example(False,negative) for _ in range(n)]
    def source(self,rows=None):
        target=self.location.runtime_file('ai_ogrenme_gecmisi.json');atomic_json(target,{'kayitlar':rows or [self.row]});return target
    def refresh(self):return m.refresh_indicator_performance(self.location,self.now,self.holiday)
    def test_default_enabled(self):
        with patch.dict('os.environ',{},clear=True):self.assertTrue(m.indicator_enabled())
    def test_env_true(self):self.assertTrue(m.indicator_enabled())
    def test_env_false(self):
        with patch.dict('os.environ',{'INDICATOR_PERFORMANCE_ENABLED':'false'}):self.assertFalse(m.indicator_enabled());self.assertEqual(self.refresh(),{'disabled':True})
    def test_capture_immutable_copy(self):
        snap=self.capture();self.row['criteria_snapshot']['flags']['RSI']=False;self.assertTrue(snap['features']['RSI']['active'])
    def test_capture_value(self):self.assertEqual(self.capture()['features']['RSI']['value'],55)
    def test_active_actual_flag(self):self.assertTrue(self.capture()['features']['RSI']['active'])
    def test_inactive_actual_flag(self):self.assertFalse(self.capture()['features']['MACD']['active'])
    def test_unavailable_is_not_inactive(self):self.assertIsNone(self.capture()['features']['VWAP']['active'])
    def test_raw_value_does_not_invent_vote(self):self.row.pop('criteria_snapshot');self.assertIsNone(self.capture()['features']['RSI']['active'])
    def test_unknown_state(self):self.row.pop('criteria_snapshot');self.assertEqual(self.capture()['features']['RSI']['state'],'UNKNOWN')
    def test_future_tech_rejected(self):self.row['teknik_gostergeler']['asof']=(self.at+timedelta(minutes=1)).isoformat();self.assertIsNone(self.capture()['feature_as_of'])
    def test_future_bar_rejected(self):self.row['teknik_gostergeler']['data_time']=(self.at+timedelta(days=1)).isoformat();self.assertFalse(self.capture()['features']['RSI']['available'])
    def test_open_daily_bar_rejected(self):self.row['teknik_gostergeler']['data_time']=self.at.replace(hour=15).isoformat();self.assertIsNone(self.capture()['feature_as_of'])
    def test_future_flags_not_used(self):self.row['criteria_snapshot']['captured_at']=(self.at+timedelta(days=1)).isoformat();self.assertIsNone(self.capture()['features']['RSI']['active'])
    def test_future_model_not_used(self):self.row['criteria_snapshot']['model_created_at']=(self.at+timedelta(days=1)).isoformat();self.assertIsNone(self.capture()['features']['RSI']['active'])
    def test_safe_capture_failure(self):
        with patch.object(m,'capture_feature_evidence',side_effect=ValueError('bad')):self.assertEqual(m.safe_feature_capture(self.row,self.at.isoformat())['status'],'FEATURE_NOT_CAPTURED')
    def test_legacy_inputs_unchanged(self):
        snap=m.capture_indicators({'rsi':55},self.at.isoformat());self.assertEqual(snap['inputs'],{'rsi':55});self.assertIn('feature_evidence',snap)
    def test_capture_off(self):
        with patch.dict('os.environ',{'INDICATOR_PERFORMANCE_ENABLED':'false'}):self.assertNotIn('feature_evidence',m.capture_indicators(self.row,self.at.isoformat()))
    def test_all_six_horizons(self):self.assertEqual({v['horizon'] for v in self.examples()},{str(h) for h in HORIZONS})
    def test_old_not_backfilled(self):
        row=copy.deepcopy(self.row);del row['indicator_evidence'];before=copy.deepcopy(row);samples,ex=m.indicator_examples([row],self.now,self.holiday);self.assertFalse(samples);self.assertEqual(ex['FEATURE_NOT_CAPTURED'],1);self.assertEqual(row,before)
    def test_results_not_written(self):before=copy.deepcopy(self.row);self.examples();self.assertEqual(self.row,before)
    def test_future_feature_excluded(self):self.row['indicator_evidence']['feature_as_of']=(self.at+timedelta(days=1)).isoformat();self.assertFalse(self.examples())
    def test_future_context_excluded(self):self.row['indicator_evidence']['market_context']={'created_at':(self.at+timedelta(days=1)).isoformat()};self.assertFalse(self.examples())
    def test_later_horizon_cannot_change_1g(self):
        first=next(v for v in self.examples() if v['horizon']=='1');self.row['sonuc_60g']['getiri_yuzde']=900;self.assertEqual(first,next(v for v in self.examples() if v['horizon']=='1'))
    def test_pending_not_failure(self):
        sample=self.example();sample.update(pending=True,success=None,return_=None);sample['return']=None
        stats=m._indicator_stats([sample],self.now);self.assertEqual(stats['failure_count'],0);self.assertIsNone(stats['success_rate'])
    def test_denominator(self):self.assertEqual(m._indicator_stats(self.cohort(30),self.now)['success_rate'],.5)
    def test_unknown_feature_not_failure(self):
        example=self.example(success=False);example['features']['RSI']['state']='UNKNOWN';row=self.candidate([example]);self.assertEqual(row['failure_count'],0);self.assertEqual(row['eligible_sample_count'],0);self.assertIsNone(row['success_rate'])
    def test_neutral_separate(self):sample=self.example();sample.update(success=False);sample['return']=0;self.assertEqual(m._indicator_stats([sample],self.now)['neutral_count'],1)
    def test_sell_direction_existing_definition(self):
        row=daily_tests.AnalysisTests.short(self);row['indicator_evidence']=self.row['indicator_evidence'];samples=self.examples([row]);self.assertEqual(samples[0]['direction'],'SELL');self.assertEqual(samples[0]['return'],5);self.assertEqual(samples[0]['raw_return'],-5)
    def test_family_split(self):self.assertEqual(m.indicator_family(self.row),'AGGRESSIVE_BUY');self.assertEqual(m.indicator_family(dict(self.row,model='YARIN_TOP10')),'TOMORROW_TOP10')
    def test_baseline(self):row=self.candidate(self.cohort(100));self.assertEqual(row['baseline']['success_rate'],.5)
    def test_with_without(self):row=self.candidate(self.cohort(100));self.assertEqual(row['with_feature_success_rate'],1);self.assertEqual(row['without_feature_success_rate'],0)
    def test_delta(self):self.assertEqual(self.candidate(self.cohort(100))['delta_success_rate'],.5)
    def test_no_weight_low_samples(self):self.assertIsNone(self.candidate(self.cohort(29))['learned_weight_candidate'])
    def test_early_status(self):self.assertEqual(self.candidate(self.cohort(30))['weight_status'],'EARLY')
    def test_candidate_status(self):self.assertEqual(self.candidate(self.cohort())['weight_status'],'CANDIDATE')
    def test_positive_candidate(self):self.assertGreater(self.candidate(self.cohort())['learned_weight_candidate'],0)
    def test_negative_candidate(self):self.assertLess(self.candidate(self.cohort(negative=True))['learned_weight_candidate'],0)
    def test_weight_also_measures_returns(self):
        samples=self.cohort();
        for v in samples:v.update(success=True);v['return']=8 if v['features']['RSI']['active'] else 1
        self.assertGreater(self.candidate(samples)['learned_weight_candidate'],0)
    def test_context_file_cache_invalidates(self):
        target=self.location.public/'market_context.json';atomic_json(target,{'marker':1});self.assertEqual(m.indicator_context_file(target)['marker'],1);atomic_json(target,{'marker':2});self.assertEqual(m.indicator_context_file(target)['marker'],2)
    def test_shrinkage(self):self.assertLess(self.candidate(self.cohort(30))['learned_weight_candidate'],self.candidate(self.cohort(300))['learned_weight_candidate'])
    def test_small_sample_confidence(self):self.assertLess(m._indicator_stats([self.example()]*3,self.now)['confidence'],5)
    def test_outlier_guard(self):
        samples=self.cohort();samples[0]['return']=10000;row=self.candidate(samples);self.assertIn('OUTLIER_SENSITIVE',row['warnings']);self.assertLess(row['learned_weight_candidate'],1)
    def test_mfe_mae(self):row=self.candidate(self.cohort());self.assertEqual(row['avg_favorable_excursion'],8);self.assertEqual(row['avg_adverse_excursion'],-4)
    def test_recency(self):self.assertEqual(self.candidate(self.cohort())['recency']['last_20']['sample_count'],20)
    def test_stale_warning(self):self.assertIn('STALE_DATA',self.candidate([self.example(age=120)])['warnings'])
    def test_new_pending_does_not_refresh_old_confidence(self):
        samples=[self.example(age=120) for _ in range(1000)];new=self.example();new.update(pending=True,success=None);new['return']=None;samples.append(new);self.assertLess(m._indicator_stats(samples,self.now)['confidence'],50)
    def test_bad_context_record_isolated(self):
        bad=copy.deepcopy(self.row);bad.update(id='bad',sembol='ASELS');bad['indicator_evidence']['market_context']=[];self.assertEqual(len(self.examples([self.row,bad])),6)
    def test_context_classification(self):r=next(v for v in m.aggregate_indicator_evidence(self.cohort(),self.now)['rows'] if v['indicator_id']=='MARKET_REGIME');self.assertEqual(r['feature_type'],'CONTEXT_FEATURE')
    def test_breakdowns(self):row=self.candidate(self.cohort());self.assertIn('BULL',row['breakdown']['market_regime']);self.assertIn('LEADING',row['breakdown']['sector_strength'])
    def test_combination_limit(self):self.assertEqual(len(m.aggregate_indicator_evidence(self.cohort(),self.now)['combinations']),5)
    def test_pending_combinations_not_sufficient(self):
        sample=self.example();sample.update(pending=True,success=None);sample['return']=None;self.assertFalse(m.aggregate_indicator_evidence([sample]*100,self.now)['combinations'])
    def test_combinations_need_sample(self):self.assertFalse(m.aggregate_indicator_evidence([self.example()]*29,self.now)['combinations'])
    def test_stable_needs_regimes_horizons(self):self.assertNotEqual(self.candidate(self.cohort(500))['weight_status'],'STABLE')
    def test_stable_real_agreement(self):
        samples=[]
        for h in ('1','3'):
            for regime in ('BULL','BEAR'):
                for active in (True,False):samples += [self.example(active,active,h,regime) for _ in range(300)]
        self.assertEqual(self.candidate(samples)['weight_status'],'STABLE')
    def test_inconsistent_horizon_penalty(self):
        a=self.cohort();b=[dict(v,horizon='3',success=not v['success'],**{'return':-v['return']}) for v in a];self.assertIn('INCONSISTENT_HORIZONS',self.candidate(a+b)['warnings'])
    def test_malformed_family_isolated(self):doc=m.aggregate_indicator_evidence([{'family':'bad'},self.example()],self.now);self.assertEqual(doc['invalid_projection_count'],1);self.assertTrue(doc['rows'])
    def test_indicator_error_isolated(self):
        sample=self.example();sample['features']['RSI']={'available':True,'active':True,'state':[]};doc=m.aggregate_indicator_evidence([sample],self.now);self.assertTrue(any(r['indicator_id']=='MACD' for r in doc['rows']))
    def test_sources_not_modified(self):target=self.source();before=target.read_bytes();self.refresh();self.assertEqual(before,target.read_bytes())
    def test_paths_private(self):self.source();self.refresh();self.assertTrue((self.location.public/'indicator_performance.json').exists());self.assertTrue(self.location.runtime_file('indicator_performance_state.json').exists());self.assertFalse((self.location.public/'indicator_performance_state.json').exists())
    def test_incremental_no_reparse(self):
        self.source();self.refresh()
        with patch.object(m,'indicator_examples',side_effect=AssertionError('reparse')):self.assertTrue(self.refresh()['unchanged'])
    def test_changed_source_reproject(self):self.source();self.refresh();self.source([dict(self.row,id='new',sembol='ASELS')]);self.assertEqual(self.refresh()['sources_read'],1)
    def test_archive_immutable(self):self.source();self.refresh();target=self.location.runtime_file('indicator_performance')/(self.now.date().isoformat()+'.json');before=target.read_bytes();self.source([dict(self.row,id='two',sembol='ASELS')]);self.refresh();self.assertEqual(target.read_bytes(),before)
    def test_corrupt_state_rebuild(self):self.source();self.location.runtime_file('indicator_performance_state.json').write_text('{');self.assertEqual(self.refresh()['sources_read'],1)
    def test_corrupt_source_partial_visible(self):
        self.source();atomic_json(self.location.runtime_file('tahmin_gecmisi.json'),{'tahminler':'bad'})
        with self.assertRaises(TaskIssue):self.refresh()
        doc=json.loads((self.location.public/'indicator_performance.json').read_text());self.assertEqual(doc['status'],'DEGRADED');self.assertTrue(doc['rows'])
    def test_corrupt_public_rebuild_without_source_reparse(self):
        self.source();self.refresh();(self.location.public/'indicator_performance.json').write_text('{')
        with patch.object(m,'indicator_examples',side_effect=AssertionError('reparse')):self.refresh()
        self.assertEqual(json.loads((self.location.public/'indicator_performance.json').read_text())['engine_version'],m.INDICATOR_VERSION)
    def test_corrupt_projection_revalidated(self):
        self.source();self.refresh();target=self.location.runtime_file('indicator_performance_state.json');state=json.loads(target.read_bytes());state['sources']['daily:ai_ogrenme_gecmisi.json']['observations'][0]['outcomes']['1'][1]=999;atomic_json(target,state)
        self.assertEqual(self.refresh()['sources_read'],1)
    def test_compact_roundtrip(self):
        examples=self.examples();packed=m.pack_indicator_examples(examples);self.assertEqual(len(packed),1);self.assertEqual(list(m.unpack_indicator_examples(packed)),examples);self.assertNotIn('fiyat',json.dumps(packed))
    def test_no_old_top10_backfill(self):
        from bist_bot import yarin_snapshot_modeli
        row=copy.deepcopy(self.row);row.pop('indicator_evidence');self.assertNotIn('indicator_evidence',yarin_snapshot_modeli({'top10':[row]})['top10'][0])
    def test_source_failure_no_false_ok(self):
        self.source();self.refresh();self.location.runtime_file('ai_ogrenme_gecmisi.json').write_text('{')
        with self.assertRaises(TaskIssue):self.refresh()
        self.assertEqual(json.loads((self.location.public/'indicator_performance.json').read_text())['rows'],[])
    def test_atomic_failure_preserves_report(self):
        self.source();self.refresh();target=self.location.public/'indicator_performance.json';before=target.read_bytes();self.source([dict(self.row,id='another')])
        with patch.object(m,'atomic_json',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.refresh()
        self.assertEqual(target.read_bytes(),before)
    def test_feature_state_counts(self):
        row=self.candidate(self.cohort());self.assertEqual(row['states']['POSITIVE']['eligible_sample_count'],100);self.assertEqual(row['states']['NEUTRAL']['eligible_sample_count'],100)
    def test_regime_inconsistency_not_stable(self):
        samples=[]
        for h in ('1','3'):
            for active in (True,False):
                samples += [self.example(active,active,h,'BULL') for _ in range(600)]
                samples += [self.example(active,not active,h,'BEAR') for _ in range(300)]
        row=self.candidate(samples);self.assertIn('INCONSISTENT_REGIMES',row['warnings']);self.assertNotEqual(row['weight_status'],'STABLE')
    def test_no_provider_calls(self):
        self.source()
        with patch('performans_motoru.provider_history',side_effect=AssertionError('provider')):self.refresh()
    def test_default_api_missing_cache_503_for_valid_indicators(self):
        for indicator in m.INDICATOR_IDS:
            with self.subTest(indicator=indicator),self.assertRaises(RecordError) as caught:m.indicator_report({'indicator':[indicator]},self.location)
            self.assertEqual(caught.exception.status,503)
    def test_default_api_disabled_without_cache(self):
        with patch.dict('os.environ',{'INDICATOR_PERFORMANCE_ENABLED':'false'}):self.assertFalse(m.indicator_report({},self.location)['enabled'])
    def test_api_missing_503(self):
        with self.assertRaises(RecordError) as caught:m.advanced_indicator_report({},self.location)
        self.assertEqual(caught.exception.status,503)
    def test_api_corrupt_503(self):
        (self.location.public/'indicator_performance.json').write_text('{')
        with self.assertRaises(RecordError) as caught:m.advanced_indicator_report({},self.location)
        self.assertEqual(caught.exception.status,503)
    def test_api_invalid_400(self):
        for query in ({'family':['BAD']},{'horizon':['2']},{'direction':['UP']},{'secret':['x']},{'family':['ALL','ALL']}):
            with self.subTest(query=query),self.assertRaises(RecordError) as caught:m.advanced_indicator_report(query,self.location)
            self.assertEqual(caught.exception.status,400)
    def test_api_disabled(self):
        with patch.dict('os.environ',{'INDICATOR_PERFORMANCE_ENABLED':'false'}):self.assertFalse(m.advanced_indicator_report({},self.location)['enabled'])
    def test_api_filters(self):
        self.source();self.refresh();doc=m.indicator_report({'family':['AGGRESSIVE_BUY'],'indicator':['RSI'],'direction':['BUY'],'horizon':['1']},self.location);self.assertEqual(len(doc['rows']),1);self.assertFalse(doc['production_applied'])
    def test_http_api(self):
        from web_server import create_server
        self.source();self.refresh();server=create_server('127.0.0.1',0,data_paths=self.location);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root=f'http://127.0.0.1:{server.server_port}/api/indicator-performance'
            with urllib.request.urlopen(root+'?family=ALL&indicator=RSI&horizon=1') as response:self.assertEqual(len(json.load(response)['rows']),1)
            with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(root+'?family=BAD')
            self.assertEqual(caught.exception.code,400)
        finally:server.shutdown();server.server_close();thread.join()
    def test_worker_callback_and_interval(self):
        from ana_motor_gorevleri import WorkerTasks
        from ana_motor import DEFAULTS
        adapter=WorkerTasks();self.addCleanup(adapter.close)
        self.assertIn('indicator_performance',adapter.callbacks());self.assertEqual(DEFAULTS['indicator_performance'],900)
        with patch.dict('os.environ',{'INDICATOR_PERFORMANCE_ENABLED':'false'}):self.assertNotIn('indicator_performance',adapter.callbacks())
    def test_worker_fail_safe(self):
        from ana_motor import AnaMotor
        import time
        motor=AnaMotor({'indicator_performance':Mock(side_effect=ValueError('failure')),'alarm':Mock(return_value={})},directory=self.location.runtime,clock=lambda:self.now,holiday=self.holiday)
        self.addCleanup(motor.executor.shutdown)
        motor.tick();time.sleep(.05);motor.tick();self.assertEqual(motor.state['tasks']['indicator_performance']['status'],'ERROR');self.assertEqual(motor.state['tasks']['alarm']['status'],'OK')
    def test_top10_only_metadata(self):
        from bist_bot import yarin_snapshot_modeli
        row=dict(self.row,yarin_top10_puani=88,learning_bonus=3)
        result=yarin_snapshot_modeli({'top10':[row]},self.at.isoformat())['top10'][0]
        for key in row:self.assertEqual(result[key],row[key])
        self.assertIn('indicator_evidence',result)


class IntradayEvidenceTests(unittest.TestCase):
    def setUp(self):
        intraday_tests.PerformanceTests.setUp(self)
        self.row['indicator_snapshot'].update(mode='INTRADAY',data_time=(self.at-timedelta(minutes=5)).isoformat(),closing={},bollinger=self.row['Bollinger'],momentum={'short_pct':1})
        self.row['indicator_evidence']=m.capture_feature_evidence(self.row,self.at.isoformat(),True,self.location)
    def result(self,*args,**kwargs):return intraday_tests.PerformanceTests.result(self,*args,**kwargs)
    def stored(self,*args,**kwargs):return intraday_tests.PerformanceTests.stored(self,*args,**kwargs)
    def examples(self,stored=None):return m.intraday_indicator_examples([self.row],self.stored() if stored is None else stored,self.now,self.holiday)[0]
    def test_closed_5m_capture(self):self.assertTrue(self.row['indicator_evidence']['features']['RSI']['available'])
    def test_unclosed_5m_rejected(self):self.row['indicator_snapshot']['data_time']=self.at.isoformat();self.assertIsNone(m.capture_feature_evidence(self.row,self.at.isoformat(),True,self.location)['feature_as_of'])
    def test_actual_al_vote(self):self.assertEqual(self.row['indicator_evidence']['features']['RSI']['state'],'POSITIVE')
    def test_sat_vote_and_confirmation(self):
        self.row.update(signal='SAT_ADAYI');self.row['confirmations']['RSI']='SAT';s=m.capture_feature_evidence(self.row,self.at.isoformat(),True,self.location);self.assertEqual(s['features']['RSI']['state'],'NEGATIVE');self.assertTrue(s['features']['RSI']['confirmed'])
    def test_intraday_horizons(self):self.assertEqual({v['horizon'] for v in self.examples()},{'30m','60m','120m','SEANS','1','3'})
    def test_intraday_existing_returns(self):self.assertAlmostEqual(self.examples()[0]['return'],self.result()['direction_return'])
    def test_intraday_result_hash_required(self):stored=self.stored();stored['one']['source_hash']='bad';self.assertFalse(self.examples(stored))
    def test_intraday_future_outcome(self):stored=self.stored();stored['one']['outcomes']['30m']['observed_at']=(self.now+timedelta(days=1)).isoformat();self.assertNotIn('30m',{v['horizon'] for v in self.examples(stored)})
    def test_intraday_pending_not_failure(self):self.assertTrue(all(v['pending'] for v in self.examples({})))
    def test_new_event_capture_only(self):
        from gunluk_al_sat import GunlukAlSat
        engine=GunlukAlSat(location=self.location);state={'signals':{}};engine.persist(self.row,state)
        path=self.location.runtime_file('gunluk_al_sat_gecmisi')/(self.at.date().isoformat()+'.json');before=path.read_bytes();engine.persist(self.row,state);self.assertEqual(path.read_bytes(),before);self.assertIn('indicator_evidence',next(iter(json.loads(before)['events'].values())))
    def test_intraday_worker_reads_existing_results(self):
        target=self.location.runtime_file('gunluk_al_sat_gecmisi')/(self.at.date().isoformat()+'.json');target.parent.mkdir(parents=True,exist_ok=True);atomic_json(target,{'model':'GUNLUK_AL_SAT_V1','events':{'one':self.row}})
        result_path=self.location.runtime_file('intraday_signal_results')/target.name;result_path.parent.mkdir(parents=True,exist_ok=True);atomic_json(result_path,{'events':self.stored()})
        before=target.read_bytes();result=m.refresh_indicator_performance(self.location,self.now,self.holiday);self.assertEqual(result['examples'],6);self.assertEqual(target.read_bytes(),before)
