import copy,json,os,tempfile,threading,unittest,urllib.request,urllib.error
from datetime import datetime,timedelta
from unittest.mock import Mock,patch
from ai_karar_motoru import ISTANBUL
from veri_yollari import DataPaths
from gorev_hatalari import TaskIssue
import piyasa_baglami as m


class RegimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name}))
        self.now=datetime(2026,10,8,19,tzinfo=ISTANBUL);self.holiday=lambda _:False
        self.symbols=['S'+str(i).zfill(3) for i in range(60)]
        self.engine=m.PiyasaBaglami(self.location,clock=lambda:self.now)
    def row(self,stock='S000',direction=1):
        close=101 if direction>0 else 99 if direction<0 else 100
        raw={'close':close,'previous_close':100,'open':100,'high':max(100,close)+.5,'low':min(100,close)-.5,
            'sma20':90 if direction>0 else 110 if direction<0 else 100,'sma50':80 if direction>0 else 120 if direction<0 else 100,
            'previous20_high':110,'previous20_low':90,'volume':1000,'return_3d':direction,'sma20_slope':direction,
            'macd_histogram':direction,'rsi':60 if direction>0 else 40 if direction<0 else 50,'atr_pct':1,'atr_pct_baseline':1}
        return {'sembol':stock,'teknik_gostergeler':{'mode':'TOMORROW','asof':self.now.isoformat(),'data_time':self.now.replace(hour=18,minute=15).isoformat(),'closing':raw}}
    def rows(self,direction=1):return [self.row(s,direction) for s in self.symbols]
    def build(self,rows=None,index=None,universe=None):return m.build_measurement(self.rows() if rows is None else rows,self.symbols if universe is None else universe,self.row('XU100') if index is None else index,self.now,self.holiday)
    def publish(self,rows=None,index=None):
        self.location.public_file('bist_data.json').write_text(json.dumps({'hisseler':self.rows() if rows is None else rows}))
        return self.engine.refresh_measurement(self.symbols,self.row('XU100') if index is None else index,self.holiday)
    def test_xutum_only(self):self.assertEqual(self.build(self.rows()+[self.row('FUND')])['valid_stock_count'],60)
    def test_symbol_normalization(self):self.assertEqual(self.build([self.row('BIST:S000.IS')],universe=['S000'])['valid_stock_count'],1)
    def test_invalid_symbol(self):self.assertEqual(self.build([self.row('bad!')])['valid_stock_count'],0)
    def test_missing_price(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['closing']['close']=None;self.assertEqual(self.build(rows)['valid_stock_count'],59)
    def test_invalid_ohlc(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['closing']['low']=200;self.assertEqual(self.build(rows)['valid_stock_count'],59)
    def test_advancing(self):self.assertEqual(self.build()['advancing_count'],60)
    def test_declining(self):self.assertEqual(self.build(self.rows(-1))['declining_count'],60)
    def test_unchanged(self):self.assertEqual(self.build(self.rows(0))['unchanged_count'],60)
    def test_zero_division(self):self.assertIsNone(self.build()['advance_decline_ratio'])
    def test_ad_ratio_net(self):
        rows=self.rows()[:40]+self.rows(-1)[40:];p=self.build(rows);self.assertEqual(p['advance_decline_ratio'],2);self.assertEqual(p['advance_decline_net'],20)
    def test_sma20(self):self.assertEqual(self.build()['above_sma20_pct'],100)
    def test_sma50(self):self.assertEqual(self.build(self.rows(-1))['above_sma50_pct'],0)
    def test_sma_missing_separate_denominator(self):
        rows=self.rows()
        for r in rows[:30]:r['teknik_gostergeler']['closing']['sma50']=None
        p=self.build(rows);self.assertEqual(p['sample_counts']['sma50'],30);self.assertEqual(p['above_sma50_pct'],100)
    def test_new_high(self):
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['closing']['previous20_high']=101
        self.assertEqual(self.build(rows)['new_high_count'],60)
    def test_new_low(self):
        rows=self.rows(-1)
        for r in rows:r['teknik_gostergeler']['closing']['previous20_low']=99
        self.assertEqual(self.build(rows)['new_low_count'],60)
    def test_missing_high_low_null(self):
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['closing']['previous20_high']=None
        self.assertIsNone(self.build(rows)['new_high_count'])
    def test_volume_breadth(self):self.assertEqual(self.build()['up_volume_pct'],100)
    def test_down_volume(self):self.assertEqual(self.build(self.rows(-1))['down_volume_pct'],100)
    def test_zero_volume(self):
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['closing']['volume']=0
        self.assertIsNone(self.build(rows)['up_volume_pct'])
    def test_missing_volume_excluded_score(self):
        rows=self.rows()
        for r in rows[:40]:r['teknik_gostergeler']['closing']['volume']=None
        p=self.build(rows);self.assertNotIn('volume',p['breadth_components']);self.assertIn('Hacim teyidi yetersiz',p['warnings'])
    def test_breadth_bounds(self):
        for side in (-1,0,1):self.assertTrue(0<=self.build(self.rows(side))['breadth_score']<=100)
    def test_missing_components_renormalized(self):
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['closing'].update(sma20=None,sma50=None,volume=None,previous20_high=None)
        p=self.build(rows);self.assertEqual(p['breadth_score'],100);self.assertIsNone(p['regime'])
    def test_components_explain_score(self):
        p=self.build();self.assertAlmostEqual(sum(v['contribution'] for v in p['breadth_components'].values()),p['breadth_score'],places=2)
    def test_each_breadth_state(self):
        for score,label in [(80,'VERY_STRONG'),(60,'STRONG'),(40,'NEUTRAL'),(20,'WEAK'),(0,'VERY_WEAK')]:
            self.assertEqual(m.classification(score,('VERY_STRONG','STRONG','NEUTRAL','WEAK','VERY_WEAK')),label)
    def test_each_regime(self):
        for score,label in [(80,'STRONG_BULL'),(60,'BULL'),(40,'NEUTRAL'),(20,'BEAR'),(0,'STRONG_BEAR')]:
            self.assertEqual(m.classification(score,('STRONG_BULL','BULL','NEUTRAL','BEAR','STRONG_BEAR')),label)
    def test_index_positive(self):self.assertEqual(self.build()['index_trend'],'POSITIVE')
    def test_index_negative(self):self.assertEqual(self.build(index=self.row('XU100',-1))['index_trend'],'NEGATIVE')
    def test_index_neutral(self):self.assertEqual(self.build(index=self.row('XU100',0))['index_trend'],'NEUTRAL')
    def test_momentum_multi_indicator(self):self.assertEqual(self.build()['index_momentum'],'POSITIVE')
    def test_single_momentum_not_used(self):self.assertIsNone(m.index_observation({'return_3d':10})['index_momentum'])
    def test_volatility_all_classes(self):
        for value,label in [(.5,'LOW'),(1,'NORMAL'),(2,'HIGH'),(3,'EXTREME')]:self.assertEqual(m.index_observation({'atr_pct':value,'atr_pct_baseline':1})['index_volatility'],label)
    def test_volatility_missing_null(self):self.assertIsNone(m.index_observation({'atr_pct':2})['index_volatility'])
    def test_strong_bull(self):self.assertEqual(self.build()['regime'],'STRONG_BULL')
    def test_strong_bear(self):self.assertEqual(self.build(self.rows(-1),self.row('XU100',-1))['regime'],'STRONG_BEAR')
    def test_neutral_regime(self):self.assertEqual(self.build(self.rows()[:30]+self.rows(-1)[30:],self.row('XU100',0))['regime'],'NEUTRAL')
    def test_regime_score_bounds(self):self.assertTrue(0<=self.build()['regime_score']<=100)
    def test_confidence_not_score(self):
        p=self.build(self.rows(-1),self.row('XU100',-1));self.assertGreater(p['regime_confidence'],80);self.assertLess(p['regime_score'],20)
    def test_low_coverage_confidence(self):self.assertLess(self.build(self.rows()[:10])['regime_confidence'],35)
    def test_low_count_no_regime(self):self.assertIsNone(self.build(self.rows()[:10])['regime'])
    def test_risk_all_classes(self):
        for args,label in [(('LOW',80,10,'POSITIVE'),'LOW'),(('NORMAL',50,50,'NEUTRAL'),'NORMAL'),(('HIGH',50,50,'NEUTRAL'),'HIGH'),(('EXTREME',50,50,'NEUTRAL'),'EXTREME')]:self.assertEqual(m.risk_class(*args),label)
    def test_breadth_collapse_risk(self):self.assertEqual(m.risk_class('NORMAL',10,90,'NEGATIVE'),'EXTREME')
    def test_divergence(self):self.assertIn('Endeks pozitif ancak piyasa katılımı zayıf',self.build(self.rows(-1))['warnings'])
    def test_reverse_divergence(self):self.assertIn('Endeks zayıf ancak piyasa genişliği toparlanıyor',self.build(index=self.row('XU100',-1))['warnings'])
    def test_conflict_lowers_confidence(self):self.assertLess(self.build(self.rows(-1))['regime_confidence'],self.build()['regime_confidence'])
    def test_reasons_real(self):self.assertIn('Endeks SMA20/SMA50 üzerinde',self.build()['reasons'])
    def test_future_source(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['asof']=(self.now+timedelta(hours=1)).isoformat();self.assertEqual(self.build(rows)['valid_stock_count'],59)
    def test_open_candle(self):
        self.now=self.now.replace(hour=14);self.assertEqual(self.build()['valid_stock_count'],0)
    def test_wrong_timeframe(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['mode']='INTRADAY';self.assertEqual(self.build(rows)['valid_stock_count'],59)
    def test_stale_sources(self):
        self.now+=timedelta(days=1);self.assertEqual(self.build(self.rows())['valid_stock_count'],60)
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['data_time']='2026-10-08T18:15:00+03:00'
        self.assertEqual(self.build(rows)['valid_stock_count'],0)
    def test_identical_duplicates_once(self):self.assertEqual(self.build(self.rows()+[self.rows()[0]])['valid_stock_count'],60)
    def test_conflicting_duplicates_excluded(self):self.assertEqual(self.build(self.rows()+[self.row('S000',-1)])['valid_stock_count'],59)
    def test_inputs_immutable(self):
        rows=self.rows();old=copy.deepcopy(rows);self.build(rows);self.assertEqual(rows,old)
    def test_persistence_paths(self):self.publish();self.assertTrue((self.location.public/'market_context.json').exists());self.assertTrue((self.location.runtime/'market_context/2026-10-08.json').exists())
    def test_history_immutable(self):
        self.publish();p=self.location.runtime/'market_context/2026-10-08.json';before=p.read_bytes();self.publish(self.rows(-1));self.assertEqual(p.read_bytes(),before)
    def test_closed_no_rewrite(self):
        self.publish();p=self.location.public/'market_context.json';before=p.stat().st_mtime_ns;self.now+=timedelta(minutes=5);self.publish();self.assertEqual(p.stat().st_mtime_ns,before)
    def test_atomic_error_preserves_previous(self):
        self.publish();p=self.location.public/'market_context.json';before=p.read_bytes();self.now+=timedelta(days=1)
        with patch('kullanici_kayitlari.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.publish()
        self.assertEqual(p.read_bytes(),before)
    def test_stale_view(self):
        p=self.publish();self.now+=timedelta(days=1);v=m.measurement_view(p,self.now,self.holiday);self.assertTrue(v['stale']);self.assertEqual(v['regime_confidence'],0)
    def test_future_view_rejected(self):
        p=self.build();p['created_at']=(self.now+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):m.measurement_view(p,self.now,self.holiday)
    def test_flag_default_true(self):
        with patch.dict(os.environ,{},clear=True):self.assertTrue(m.regime_enabled())
    def test_flag_true(self):
        with patch.dict(os.environ,{'MARKET_REGIME_ENABLED':'true'}):self.assertTrue(m.regime_enabled())
    def test_flag_false_no_read(self):
        with patch.dict(os.environ,{'MARKET_REGIME_ENABLED':'false'}):self.assertEqual(self.engine.measurement()['enabled'],False);self.assertEqual(self.engine.refresh_measurement()['enabled'],False)
    def test_corrupt_cache_503(self):
        from kullanici_kayitlari import RecordError
        self.location.public_file('market_context.json').write_text('{bad')
        with self.assertRaises(RecordError) as c:self.engine.measurement()
        self.assertEqual(c.exception.status,503)
    def test_missing_cache_503(self):
        from kullanici_kayitlari import RecordError
        with self.assertRaises(RecordError) as c:self.engine.measurement()
        self.assertEqual(c.exception.status,503)
    def test_provider_failure_keeps_breadth(self):
        self.location.public_file('bist_data.json').write_text(json.dumps({'hisseler':self.rows()}))
        with patch('bist_bot.bp.Index') as provider:
            provider.return_value.history.side_effect=ConnectionError('provider unreachable')
            with self.assertRaises(TaskIssue):self.engine.refresh_measurement(self.symbols,holiday=self.holiday)
        value=json.loads(self.location.public_file('market_context.json').read_text());self.assertEqual(value['valid_stock_count'],60);self.assertIsNone(value['index_trend'])
    def test_frozen_prediction_context(self):
        p=self.build();before=copy.deepcopy(p);c=m.frozen_market_context(p,self.now);p['regime_score']=0;self.assertEqual(c['market_regime_score'],before['regime_score'])
    def test_no_future_prediction_context(self):self.assertEqual(m.frozen_market_context(self.build(),self.now-timedelta(minutes=1)),{})
    def test_no_retrospective_context(self):self.assertEqual(m.frozen_market_context(self.build(),self.now.replace(hour=18,minute=20)),{})
    def test_old_prediction_untouched(self):
        old={'id':'old','price':100};before=copy.deepcopy(old);m.frozen_market_context(self.build(),self.now);self.assertEqual(old,before)
    def test_worker_callback_registered(self):
        from ana_motor_gorevleri import WorkerTasks
        adapter=WorkerTasks();self.addCleanup(adapter.close)
        with patch('piyasa_baglami.regime_enabled',return_value=True):self.assertIn('market_regime',adapter.callbacks())
    def test_worker_false_unregistered(self):
        from ana_motor_gorevleri import WorkerTasks
        adapter=WorkerTasks();self.addCleanup(adapter.close)
        with patch('piyasa_baglami.regime_enabled',return_value=False):self.assertNotIn('market_regime',adapter.callbacks())
    def test_worker_fail_safe(self):
        from ana_motor import AnaMotor
        failed=Mock(side_effect=RuntimeError('regime failure'));alarm=Mock(return_value=0)
        worker=AnaMotor({'market_regime':failed,'alarm':alarm},self.location.runtime,clock=lambda:self.now)
        try:
            worker.tick()
            for task in worker.tasks.values():
                if task.future:
                    try:task.future.result(timeout=5)
                    except RuntimeError:pass
            worker.tick();self.assertTrue(alarm.called);self.assertIn(worker.state['tasks']['market_regime']['status'],('ERROR','RETRYING'))
        finally:worker.shutdown()
    def test_1811_source_not_final(self):
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['asof']=self.now.replace(hour=18,minute=11).isoformat()
        self.assertEqual(self.build(rows)['valid_stock_count'],0)
    def test_null_universe_member_rejected(self):self.assertEqual(self.build(universe=self.symbols+[None])['universe_count'],60)
    def test_holiday_market_closed(self):
        p=m.build_measurement([],[],{},self.now.replace(hour=12),lambda day:day==self.now.date())
        self.assertFalse(p['market_open'])
    def test_index_future_not_used(self):
        index=self.row('XU100');index['teknik_gostergeler']['data_time']=(self.now+timedelta(days=1)).isoformat()
        self.assertIsNone(self.build(index=index)['index_trend'])
    def test_api_corrupt_shape_503(self):
        from kullanici_kayitlari import RecordError
        self.location.public_file('market_context.json').write_text(json.dumps({'engine_version':m.MEASUREMENT_VERSION,'created_at':self.now.isoformat()}))
        with self.assertRaises(RecordError) as c:self.engine.measurement()
        self.assertEqual(c.exception.status,503)
    def test_legacy_effects_unchanged(self):
        before=m.build_context([],[],{}, {},self.now)
        self.publish();after=m.build_context([],[],{}, {},self.now)
        self.assertEqual(before,after)
    def test_prediction_rejects_stale_context(self):
        p=self.build();self.assertEqual(m.frozen_market_context(p,self.now+timedelta(days=4)),{})
    def test_index_provider_not_refetched_after_final(self):
        self.publish()
        with patch('bist_bot.bp.Index') as provider:
            self.engine.refresh_measurement(self.symbols,holiday=self.holiday);provider.assert_not_called()
    def test_closed_helper_future_bar_no_leakage(self):
        from teknik_gostergeler import calculate
        import pandas as pd
        frame=pd.DataFrame({'Open':[99.]*60,'High':[101.]*60,'Low':[98.]*60,'Close':[100.]*60,'Volume':[1000.]*60},index=pd.bdate_range(end='2026-10-08',periods=60,tz=ISTANBUL))
        before=calculate(frame,self.now,'TOMORROW')['closing']
        frame.loc[pd.Timestamp('2026-10-09',tz=ISTANBUL)]=[900,1000,800,950,1e9]
        self.assertEqual(before,calculate(frame,self.now,'TOMORROW')['closing'])
    def test_closed_helper_sma_high_volume_actual(self):
        from teknik_gostergeler import calculate
        import pandas as pd
        frame=pd.DataFrame({'Open':[99.]*60,'High':[101.]*60,'Low':[98.]*60,'Close':[100.]*60,'Volume':[1000.]*60},index=pd.bdate_range(end='2026-10-08',periods=60,tz=ISTANBUL))
        closing=calculate(frame,self.now,'TOMORROW')['closing'];self.assertEqual(closing['sma50'],100);self.assertEqual(closing['previous20_high'],101);self.assertEqual(closing['volume'],1000)

    def test_empty_index_provider_degraded(self):
        import pandas as pd
        self.location.public_file('bist_data.json').write_text(json.dumps({'hisseler':self.rows()}))
        with patch('bist_bot.bp.Index') as provider:
            provider.return_value.history.return_value=pd.DataFrame()
            with self.assertRaises(TaskIssue) as issue:self.engine.refresh_measurement(self.symbols,holiday=self.holiday)
        self.assertEqual(issue.exception.issue['code'],'PROVIDER_DATA')
        self.assertEqual(json.loads(self.location.public_file('market_context.json').read_text())['valid_stock_count'],60)
    def test_compact_snapshot_no_raw_rows(self):
        self.publish();raw=(self.location.runtime/'market_context/2026-10-08.json').read_bytes()
        self.assertLess(len(raw),10000);self.assertNotIn(b'teknik_gostergeler',raw);self.assertNotIn(b'S000',raw)
    def test_corrupt_archive_preserved(self):
        self.publish();p=self.location.runtime/'market_context/2026-10-08.json';p.write_text('{bad')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(p.read_text(),'{bad')
    def test_flag_runtime_false_scheduler_skips(self):
        from ana_motor import AnaMotor
        callback=Mock();worker=AnaMotor({'market_regime':callback},self.location.runtime,clock=lambda:self.now)
        try:
            with patch.dict(os.environ,{'MARKET_REGIME_ENABLED':'false'}):worker.tick()
            callback.assert_not_called()
        finally:worker.shutdown()

    def test_created_at_after_calculation_completion(self):
        self.location.public_file('bist_data.json').write_text(json.dumps({'hisseler':self.rows()}))
        finish=self.now+timedelta(seconds=30)
        engine=m.PiyasaBaglami(self.location,clock=Mock(side_effect=[self.now,finish]))
        result=engine.refresh_measurement(self.symbols,self.row('XU100'),self.holiday)
        self.assertEqual(result['created_at'],finish.isoformat())
        self.assertEqual(m.frozen_market_context(result,self.now+timedelta(seconds=15)),{})

    def test_http_api(self):
        from web_server import create_server
        self.publish();server=create_server('127.0.0.1',0,data_paths=self.location);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch('piyasa_baglami.PiyasaBaglami',return_value=self.engine):
                with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/market-context') as r:p=json.load(r)
            self.assertEqual(p['engine_version'],m.MEASUREMENT_VERSION);self.assertTrue(p['enabled'])
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
