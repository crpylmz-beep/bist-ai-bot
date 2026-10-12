import copy
import json
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime,timedelta
from unittest.mock import Mock,patch

from ai_karar_motoru import ISTANBUL
from kullanici_kayitlari import atomic_json,RecordError
from veri_yollari import DataPaths
from gun_ici_performans import GunIciPerformans
from performans_motoru import sessions_after
from gorev_hatalari import TaskIssue
import intraday_sinyal_performansi as module


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2026,10,2,14,tzinfo=ISTANBUL)
        self.now=datetime(2026,10,7,19,tzinfo=ISTANBUL)
        self.holiday=lambda day:False
        self.row={'event_id':'one','symbol':'THYAO','model':'GUNLUK_AL_SAT_V1','signal':'AL_ADAYI',
            'signal_state':'YENI_AL','timestamp':self.at.isoformat(),'data_timestamp':self.at.isoformat(),
            'price':100,'prediction_price':100,'technical_score':88,'confidence_score':80,
            'confirmation_count':8,'confirmation_total':9,'confirmation_level':'COK_GUCLU',
            'timeframe':'5m','data_quality':'GOOD','liquidity_status':'GOOD','analysis_only':True,
            'take_profit':110,'stop_loss':90,'buy_zone_low':99,'buy_zone_high':100,
            'RSI':55,'ATR':1,'VWAP':99,'EMA9':101,'EMA21':100,'MACD':1,'MACD_histogram':.5,
            'OBV':1000,'Bollinger':{'middle':100,'upper':103,'lower':97},'candle_summary':{'direction':'POSITIVE','close_position_pct':75},'volume_ratio':150,'momentum':1,'risk_reward_ratio':2,
            'extended_move_penalty':0,'breakout_status':'CONFIRMED','reasons':[],'warnings':[],
            'indicator_snapshot':{'asof':self.at.isoformat()},
            'confirmations':{name:'AL' for name in ('VWAP','EMA','RSI','MACD','VOLUME','OBV','BOLLINGER','MOMENTUM','CANDLE')}}
        self.bars=[{'timestamp':(self.at+timedelta(minutes=5*i)).isoformat(),'open':100,'high':105,'low':98,'close':102} for i in range(50)]
        days=sessions_after(self.at.date(),3,self.holiday)
        self.daily=[{'timestamp':day.isoformat(),'open':100,'high':105,'low':95,'close':104} for day in days]
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
    def result(self,h='30m',row=None,bars=None,daily=None,current=None):
        return module.outcome(row or self.row,self.bars if bars is None else bars,self.daily if daily is None else daily,h,current or self.now,self.holiday)
    def stored(self,row=None):
        row=row or self.row
        return {row['event_id']:{'source_hash':module.fingerprint(row),'outcomes':{h:self.result(h,row) for h in module.HORIZONS}}}
    def report(self,row=None,stored=None):
        row=row or self.row;observed=module.observations([row],self.now)[0]
        return module.aggregate(observed,stored or self.stored(row),self.now,self.holiday)
    def group(self,report=None,h='30m'):
        return next(g for g in (report or self.report())['groups'] if g['horizon']==h and g['period']=='all_time' and g['min_confidence']==0)
    def source(self,rows=None):
        target=self.location.runtime_file('gunluk_al_sat_gecmisi')/(self.at.date().isoformat()+'.json')
        target.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(target,{'model':'GUNLUK_AL_SAT_V1','events':{r['event_id']:r for r in rows or [self.row]}})
        return target
    def test_al_return(self):self.assertAlmostEqual(self.result()['direction_return'],2)
    def test_sat_return_inverse(self):
        row=dict(self.row,signal='SAT_ADAYI',signal_state='YENI_SAT',take_profit=90,stop_loss=110)
        bars=[dict(b,high=102,low=95,close=98) for b in self.bars]
        self.assertAlmostEqual(self.result(row=row,bars=bars)['direction_return'],(100/98-1)*100)
    def test_sat_reversal(self):row=dict(self.row,signal='SAT_ADAYI',signal_state='SAT_DONUS');self.assertEqual(module.side(row),'SAT');self.assertIsNone(module.source_issue(row,self.now))
    def test_recovery_buy(self):self.assertIsNone(module.source_issue(dict(self.row,signal_state='TOPARLANIYOR'),self.now))
    def test_recovery_watch_context_only(self):self.assertEqual(module.source_issue(dict(self.row,signal='IZLE',signal_state='TOPARLANIYOR'),self.now),'CONTEXT_ONLY')
    def test_weakening_not_forecast(self):self.assertEqual(module.source_issue(dict(self.row,signal_state='ZAYIFLIYOR'),self.now),'CONTEXT_ONLY')
    def test_30_minutes(self):self.assertEqual(self.result()['end_at'],(self.at+timedelta(minutes=30)).isoformat())
    def test_60_minutes(self):self.assertTrue(self.result('60m')['completed'])
    def test_120_minutes(self):self.assertTrue(self.result('120m')['completed'])
    def test_session_end(self):self.assertEqual(self.result('SEANS')['end_at'],self.at.replace(hour=18,minute=10).isoformat())
    def test_d1(self):self.assertTrue(self.result('D1')['completed']);self.assertEqual(self.result('D1')['end_at'][:10],'2026-10-05')
    def test_d3(self):self.assertTrue(self.result('D3')['completed']);self.assertEqual(self.result('D3')['end_at'][:10],'2026-10-07')
    def test_weekend(self):self.assertEqual(module.due_at(self.row,'D1',self.holiday).date().isoformat(),'2026-10-05')
    def test_holiday(self):self.assertEqual(module.due_at(self.row,'D1',lambda day:day.isoformat()=='2026-10-05').date().isoformat(),'2026-10-06')
    def test_pending_not_due(self):self.assertFalse(self.result(current=self.at+timedelta(minutes=10))['completed'])
    def test_missing_bar(self):self.assertEqual(self.result(bars=self.bars[1:])['reason'],'MISSING_5M_BAR')
    def test_daily_missing(self):self.assertEqual(self.result('D3',daily=self.daily[:2])['reason'],'MISSING_DAILY_OHLC')
    def test_horizon_not_truncated_at_close(self):
        row=dict(self.row,timestamp=self.at.replace(hour=18).isoformat())
        self.assertEqual(self.result(row=row)['reason'],'HORIZON_EXCEEDS_SESSION')
    def test_mfe_mae(self):self.assertAlmostEqual(self.result()['MFE'],5);self.assertAlmostEqual(self.result()['MAE'],-2)
    def test_sat_mfe_mae(self):
        row=dict(self.row,signal='SAT_ADAYI',signal_state='YENI_SAT')
        r=self.result(row=row);self.assertAlmostEqual(r['MFE'],(100/98-1)*100);self.assertAlmostEqual(r['MAE'],(100/105-1)*100)
    def test_target_hit(self):bars=copy.deepcopy(self.bars);bars[0]['high']=111;self.assertEqual(self.result(bars=bars)['target_stop_status'],'TARGET_HIT')
    def test_stop_hit(self):bars=copy.deepcopy(self.bars);bars[0]['low']=89;self.assertEqual(self.result(bars=bars)['target_stop_status'],'STOP_HIT')
    def test_neither(self):self.assertEqual(self.result()['target_stop_status'],'NEITHER')
    def test_same_bar_ambiguous(self):
        bars=copy.deepcopy(self.bars);bars[0].update(high=111,low=89)
        r=self.result(bars=bars);self.assertEqual(r['target_stop_status'],'AMBIGUOUS');self.assertEqual(module.result_issue(self.row,r,self.now,'30m',self.holiday),'AMBIGUOUS')
    def test_first_contact_order(self):
        bars=copy.deepcopy(self.bars);bars[0]['high']=111;bars[1]['low']=89
        self.assertEqual(self.result(bars=bars)['target_stop_status'],'TARGET_HIT')
    def test_buy_zone(self):r=self.result();self.assertTrue(r['buy_zone_entered']);self.assertEqual(r['buy_zone_entry_at'],self.at.isoformat());self.assertEqual(r['post_entry_reference_price'],100)
    def test_entry_bar_excluded_from_post_entry_extrema(self):
        bars=copy.deepcopy(self.bars);bars[0]['high']=109
        self.assertAlmostEqual(self.result(bars=bars)['post_entry_MFE'],5)
    def test_duplicate(self):observed,duplicates,_=module.observations([self.row,self.row],self.now);self.assertEqual(len(observed),1);self.assertEqual(duplicates,1)
    def test_conflicting_duplicate(self):other=dict(self.row,price=101);observed,_,_=module.observations([self.row,other],self.now);self.assertEqual(observed[0][1],'CONFLICTING_DUPLICATE')
    def test_snapshot_immutable(self):before=copy.deepcopy(self.row);self.result();self.report();self.assertEqual(before,self.row)
    def test_later_horizon_no_leak(self):
        bars=copy.deepcopy(self.bars);bars[-1].update(high=999,low=1,close=500)
        self.assertEqual(self.result(),self.result(bars=bars))
    def test_pre_signal_bar_not_used(self):
        bars=[dict(self.bars[0],timestamp=(self.at-timedelta(minutes=5)).isoformat(),high=999,low=1)]+self.bars
        self.assertEqual(self.result(),self.result(bars=bars))
    def test_future_signal(self):self.assertEqual(module.source_issue(dict(self.row,timestamp=(self.now+timedelta(days=1)).isoformat()),self.now),'FUTURE_TIMESTAMP')
    def test_future_frozen_feature(self):row=dict(self.row,indicator_snapshot={'asof':(self.at+timedelta(seconds=1)).isoformat()});self.assertEqual(module.source_issue(row,self.now),'FUTURE_OR_UNVERIFIED_FEATURES')
    def test_legacy_unverified(self):self.assertEqual(module.source_issue(dict(self.row,legacy_unverified=True),self.now),'UNVERIFIED')
    def test_bad_price(self):self.assertEqual(module.source_issue(dict(self.row,price=0,prediction_price=0),self.now),'MISSING_PREDICTION_PRICE')
    def test_invalid_ohlc(self):bars=copy.deepcopy(self.bars);bars[0]['high']=1;self.assertFalse(self.result(bars=bars)['completed'])
    def test_conflicting_ohlc(self):bars=self.bars+[dict(self.bars[0],close=101)];self.assertFalse(self.result(bars=bars)['completed'])
    def test_technical_bands(self):self.assertEqual(set(self.group()['technical']),{'80-89'})
    def test_confidence_bands(self):self.assertEqual(set(self.group()['confidence']),{'80-89'})
    def test_confirmation(self):self.assertEqual(set(self.group()['confirmation']),{'8/9'})
    def test_different_confirmation_total(self):row=dict(self.row,confirmation_count=5,confirmation_total=6);self.assertIn('5/6',self.group(self.report(row))['confirmation'])
    def test_indicators(self):self.assertIn('ATR_VOLATILITY',self.group()['indicators']);self.assertIn('VWAP',self.group()['indicators'])
    def test_bounded_combinations(self):features=module.conditions(self.row);self.assertEqual(len([k for k in features if '+' in k]),7)
    def test_missing_combination_not_filled(self):row=copy.deepcopy(self.row);row['confirmations'].pop('EMA');self.assertNotIn('VWAP+EMA',module.conditions(row))
    def test_all_periods(self):self.assertEqual({g['period'] for g in self.report()['groups']},set(module.PERIODS))
    def test_shared_reliability(self):self.assertEqual(self.group()['summary']['reliability'],'INSUFFICIENT');self.assertEqual(module.RELIABILITY,{'LOW':30,'MEDIUM':100,'HIGH':300})
    def test_clean_dataset(self):rows=list(module.clean_dataset(module.observations([self.row],self.now)[0],self.stored(),self.now,self.holiday));self.assertEqual(len(rows),6);self.assertEqual(rows[0]['features']['price'],100)
    def test_pending_excluded_clean(self):self.assertEqual(list(module.clean_dataset([(self.row,None)],{},self.now,self.holiday)),[])
    def test_ambiguity_excluded_success(self):
        results=self.stored();results['one']['outcomes']['30m']['target_stop_status']='AMBIGUOUS'
        stat=self.group(self.report(stored=results))['summary'];self.assertEqual(stat['completed'],0);self.assertIsNone(stat['success_rate'])
    def test_source_hash_conflict(self):stored=self.stored();stored['one']['source_hash']='wrong';self.assertEqual(self.group(self.report(stored=stored))['summary']['excluded'],{'SOURCE_HASH_CONFLICT':1})
    def test_continuation_requires_prior(self):row=dict(self.row,signal_state='AL_DEVAM');self.assertEqual(module.observations([row],self.now)[0][0][1],'UNVERIFIED_CONTINUATION')
    def test_continuation_significant(self):
        row=dict(self.row,event_id='two',timestamp=(self.at+timedelta(minutes=5)).isoformat(),signal_state='AL_DEVAM',confidence_score=60)
        self.assertIsNone(module.observations([self.row,row],self.now)[0][1][1])
    def test_continuation_unchanged(self):
        row=dict(self.row,event_id='two',timestamp=(self.at+timedelta(minutes=5)).isoformat(),signal_state='AL_DEVAM')
        self.assertEqual(module.observations([self.row,row],self.now)[0][1][1],'INSIGNIFICANT_CONTINUATION')
    def test_driver_provider_once_and_sources_preserved(self):
        other=dict(self.row,event_id='two',timestamp=(self.at+timedelta(minutes=5)).isoformat())
        source=self.source([self.row,other]);before=source.read_bytes();provider=Mock(return_value=self.bars);daily=Mock(return_value=self.daily)
        engine=GunIciPerformans(self.location,lambda:self.now,provider);engine.signal_round(self.holiday,daily)
        self.assertEqual(provider.call_count,1);self.assertEqual(daily.call_count,1);self.assertEqual(source.read_bytes(),before)
        self.assertFalse(self.location.runtime_file('tahmin_gecmisi.json').exists())
    def test_completed_not_rewritten(self):
        self.source();engine=GunIciPerformans(self.location,lambda:self.now,lambda _:self.bars);engine.signal_round(self.holiday,lambda _:self.daily)
        path=self.location.runtime_file('intraday_signal_results')/'2026-10-02.json';before=path.read_bytes()
        engine.signal_round(self.holiday,lambda _:[]);self.assertEqual(before,path.read_bytes())
    def test_driver_one_bad_record_other_continues(self):
        bad=dict(self.row,event_id='bad',symbol='BAD',price=0,prediction_price=0);self.source([self.row,bad])
        engine=GunIciPerformans(self.location,lambda:self.now,lambda _:self.bars)
        self.assertGreater(engine.signal_round(self.holiday,lambda _:self.daily)['diagnostics']['updated_outcomes'],0)
    def test_driver_one_provider_error_others_continue(self):
        other=dict(self.row,event_id='bad',symbol='BAD');self.source([self.row,other])
        def provider(stock):
            if stock=='BAD':raise RuntimeError('source down')
            return self.bars
        engine=GunIciPerformans(self.location,lambda:self.now,provider)
        with self.assertRaises(TaskIssue):engine.signal_round(self.holiday,lambda _:self.daily)
        self.assertTrue(self.location.public_file('intraday_signal_performance.json').exists())
    def test_atomic_cache_failure_previous_retained(self):
        observed=[(self.row,None)];results=self.stored();module.publish(self.location,observed,results,self.now,self.holiday)
        path=self.location.public_file('intraday_signal_performance.json');before=path.read_bytes()
        with patch('kullanici_kayitlari.os.replace',side_effect=OSError('failed')):
            with self.assertRaises(OSError):module.publish(self.location,[],{},self.now,self.holiday)
        self.assertEqual(before,path.read_bytes())
    def test_missing_cache_503(self):
        with self.assertRaises(RecordError) as error:module.api_report({},self.location)
        self.assertEqual(error.exception.status,503)
    def test_corrupt_cache_503(self):
        self.location.public_file('intraday_signal_performance.json').write_text('{bad')
        with self.assertRaises(RecordError) as error:module.api_report({},self.location)
        self.assertEqual(error.exception.status,503)
    def test_api_filters(self):
        module.publish(self.location,[(self.row,None)],self.stored(),self.now,self.holiday)
        report=module.api_report({'signal':['AL'],'state':['YENI_AL'],'horizon':['D1'],'period':['7d'],'min_confidence':['80'],'indicator':['VWAP'],'condition':['AL']},self.location)
        self.assertEqual(len(report['groups']),1);self.assertIn('AL',report['groups'][0]['indicator_statistics'])
    def test_invalid_filters(self):
        for query in ({'horizon':['D60']},{'period':['bad']},{'min_confidence':['65']},{'signal':['NO']},{'indicator':['unknown']},{'condition':['AL']},{'horizon':['30m','60m']}):
            with self.assertRaises(RecordError) as error:module.api_report(query,self.location)
            self.assertEqual(error.exception.status,400)
    def test_http_smoke(self):
        from web_server import create_server
        module.publish(self.location,[(self.row,None)],self.stored(),self.now,self.holiday)
        server=create_server('127.0.0.1',0,data_paths=self.location);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/intraday-signal-performance?horizon=30m') as response:self.assertEqual(json.load(response)['version'],module.VERSION)
        finally:server.shutdown();server.server_close();thread.join()
    def test_missing_raw_field_skips_condition_and_combo(self):
        row=dict(self.row,EMA9=None);self.assertNotIn('EMA',module.conditions(row));self.assertNotIn('VWAP+EMA',module.conditions(row))
    def test_bad_result_excursions_excluded(self):
        result=self.result();result['MFE']=999
        self.assertEqual(module.result_issue(self.row,result,self.now,'30m',self.holiday),'EXCURSION_MISMATCH')
    def test_future_result_excluded(self):
        result=self.result();result['observed_at']=(self.now+timedelta(days=1)).isoformat()
        self.assertEqual(module.result_issue(self.row,result,self.now,'30m',self.holiday),'FUTURE_OR_UNVERIFIED_OUTCOME')
    def test_unsupported_condition_400(self):
        with self.assertRaises(RecordError) as error:module.api_report({'indicator':['ATR_VOLATILITY'],'condition':['AL']},self.location)
        self.assertEqual(error.exception.status,400)
    def test_ambiguous_no_clean_example(self):
        stored=self.stored();stored['one']['outcomes']['30m']['target_stop_status']='AMBIGUOUS'
        rows=list(module.clean_dataset([(self.row,None)],stored,self.now,self.holiday));self.assertEqual(len(rows),5)
    def test_unknown_direction_not_invented(self):self.assertIsNone(module.side(dict(self.row,signal='IZLE',signal_state='TOPARLANIYOR')))
    def test_arbitrary_seconds_do_not_use_partial_bar(self):
        row=dict(self.row,timestamp=(self.at+timedelta(seconds=1)).isoformat())
        self.assertEqual(module.first_bar(module.stamp(row['timestamp'])),self.at+timedelta(minutes=5))
    def test_daily_later_data_does_not_leak_d1(self):
        daily=copy.deepcopy(self.daily);daily[-1].update(high=999,low=1,close=500)
        self.assertEqual(self.result('D1'),self.result('D1',daily=daily))
    def test_actual_v1_frozen_signal_compatible(self):
        import test_gunluk_al_sat
        from gunluk_al_sat import evaluate,GunlukAlSat
        frame=test_gunluk_al_sat.IntradayTests.frame(None,1);frame.index=frame.index-timedelta(days=5)
        row=evaluate('THYAO',frame,self.at);engine=GunlukAlSat(self.location,lambda:self.at)
        engine.persist(row,{'signals':{}})
        source,errors=module.load_sources(self.location,self.now)
        self.assertFalse(errors);self.assertEqual(source[0]['prediction_price'],row['price'])
        self.assertIsNone(module.observations(source,self.now)[0][0][1])
    def test_worker_performance_failure_other_jobs_continue(self):
        from ana_motor import AnaMotor
        bad=Mock(side_effect=RuntimeError('measurement failure'));alarm=Mock(return_value=0)
        motor=AnaMotor({'intraday_performance':bad,'alarm':alarm},self.location.runtime,clock=lambda:self.now,monotonic=lambda:0)
        try:
            motor.tick()
            for task in motor.tasks.values():
                if task.future:task.future.exception(timeout=2)
            motor.tick();self.assertEqual(alarm.call_count,1);self.assertEqual(motor.tasks['intraday_performance'].failures,1)
        finally:motor.shutdown()
    def test_corrupt_derived_record_preserved_others_measured(self):
        other=dict(self.row,event_id='two',symbol='ASELS');self.source([self.row,other])
        target=self.location.runtime_file('intraday_signal_results')/'2026-10-02.json';target.parent.mkdir(parents=True)
        atomic_json(target,{'events':{'one':{'source_hash':module.fingerprint(self.row),'outcomes':['bad']}}})
        engine=GunIciPerformans(self.location,lambda:self.now,lambda _:self.bars)
        engine.signal_round(self.holiday,lambda _:self.daily)
        values=json.loads(target.read_bytes())['events'];self.assertEqual(values['one']['outcomes'],['bad']);self.assertTrue(values['two']['outcomes']['30m']['completed'])
    def test_missing_levels_no_fabricated_target(self):
        row=dict(self.row,take_profit=None,stop_loss=None)
        result=self.result(row=row);self.assertIsNone(result['target_hit']);self.assertFalse(result['levels_available'])
    def test_new_snapshot_confidence_only_change_recorded(self):
        from gunluk_al_sat import GunlukAlSat
        engine=GunlukAlSat(self.location,lambda:self.at);state={'signals':{}}
        row=dict(self.row,signal_state='AL_DEVAM',data_quality='GOOD')
        state['signals'][row['symbol']]=dict(row,confidence_score=60)
        engine.persist(row,state)
        frozen=json.loads((self.location.runtime_file('gunluk_al_sat_gecmisi')/'2026-10-02.json').read_bytes())
        self.assertEqual(len(frozen['events']),1);value=next(iter(frozen['events'].values()));self.assertEqual(value['prediction_price'],100);self.assertEqual(value['engine_version'],'GUNLUK_AL_SAT_V1')


if __name__=='__main__':unittest.main()
