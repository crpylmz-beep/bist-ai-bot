import copy
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import numpy as np
import pandas as pd

from ai_karar_motoru import ISTANBUL
from veri_yollari import DataPaths
from kullanici_kayitlari import atomic_json, RecordError
from gorev_hatalari import TaskIssue
import gunluk_al_sat as module


class IntradayTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,7,14,tzinfo=ISTANBUL)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'INTRADAY_SIGNAL_ENGINE_ENABLED':'true'}))
        module._cache.clear();self.addCleanup(module._cache.clear)
        self.buy=self.frame(1);self.sell=self.frame(-1)
    def frame(self,side):
        index=pd.date_range('2026-10-07 10:00',periods=48,freq='5min',tz=ISTANBUL)
        move=np.sin(np.arange(48))*.25;move[-8:]=np.arange(8)*.1
        close=100+side*move;opening=close-side*.2
        return pd.DataFrame({'Open':opening,'High':np.maximum(opening,close)+(.01 if side==1 else .4),
            'Low':np.minimum(opening,close)-(.4 if side==1 else .01),'Close':close,
            'Volume':[100000]*47+[180000]},index=index)
    def result(self,frame=None,previous=None,current=None):return module.evaluate('THYAO',self.buy if frame is None else frame,current or self.now,previous)
    def engine(self,stocks=None,provider=None):return module.GunlukAlSat(self.location,lambda:self.now,lambda:stocks or ['THYAO'],provider or Mock(return_value=self.buy))
    def test_strong_buy(self):self.assertEqual(self.result()['signal'],'AL_ADAYI')
    def test_strong_sell(self):self.assertEqual(self.result(self.sell)['signal'],'SAT_ADAYI')
    def test_vwap(self):r=self.result();self.assertGreater(r['price'],r['VWAP']);self.assertEqual(r['confirmations']['VWAP'],'AL')
    def test_ema(self):r=self.result();self.assertGreater(r['EMA9'],r['EMA21'])
    def test_rsi(self):self.assertIsNotNone(self.result()['RSI'])
    def test_macd(self):r=self.result();self.assertGreater(r['MACD_histogram'],0);self.assertEqual(r['confirmations']['MACD'],'AL')
    def test_volume(self):self.assertEqual(self.result()['volume_ratio'],180)
    def test_obv(self):self.assertEqual(self.result()['confirmations']['OBV'],'AL')
    def test_bollinger(self):self.assertEqual(self.result()['Bollinger']['status'],'OK')
    def test_atr(self):self.assertGreater(self.result()['ATR'],0)
    def test_candle(self):r=self.result()['candle_summary'];self.assertEqual(r['direction'],'POSITIVE');self.assertTrue(r['near_high'])
    def test_counter(self):r=self.result();self.assertEqual(r['confirmation_count'],8);self.assertEqual(r['confirmation_total'],9)
    def test_technical_score(self):self.assertAlmostEqual(self.result()['technical_score'],88.89)
    def test_confidence(self):self.assertTrue(0<=self.result()['confidence_score']<=100)
    def test_missing_frame(self):r=self.result(pd.DataFrame());self.assertEqual(r['signal'],'IZLE');self.assertIsNone(r['VWAP'])
    def test_missing_volume(self):r=self.result(self.buy.drop(columns=['Volume']));self.assertEqual(r['data_quality'],'INSUFFICIENT')
    def test_insufficient_bars(self):self.assertEqual(self.result(self.buy.tail(10))['signal'],'IZLE')
    def test_daily_not_intraday(self):
        frame=self.buy.copy();frame.index=pd.date_range('2026-08-21',periods=48,freq='D',tz=ISTANBUL)
        self.assertEqual(self.result(frame)['data_quality'],'INSUFFICIENT')
    def test_stale(self):self.assertEqual(self.result(current=self.now+timedelta(minutes=30))['signal'],'IZLE')
    def test_invalid_ohlc(self):frame=self.buy.copy();frame.iloc[-1,frame.columns.get_loc('High')]=1;self.assertEqual(self.result(frame)['signal'],'IZLE')
    def test_liquidity(self):frame=self.buy.copy();frame['Volume']=1;self.assertEqual(self.result(frame)['signal'],'IZLE');self.assertEqual(self.result(frame)['liquidity_status'],'LIMITED')
    def test_zero_volume(self):frame=self.buy.copy();frame['Volume']=0;self.assertEqual(self.result(frame)['liquidity_status'],'INSUFFICIENT')
    def test_extended_penalty(self):
        frame=self.buy.copy();frame.iloc[-1,frame.columns.get_loc('Close')]+=15
        frame.iloc[-1,frame.columns.get_loc('High')]=frame['Close'].iloc[-1]+.01
        r=self.result(frame);self.assertGreater(r['extended_move_penalty'],0);self.assertEqual(r['signal'],'IZLE')
    def test_dynamic_zone(self):r=self.result();self.assertLessEqual(r['buy_zone_low'],r['buy_zone_high']);self.assertLessEqual(r['buy_zone_high'],r['price'])
    def test_target_stop(self):r=self.result();self.assertGreater(r['take_profit'],r['buy_zone_high']);self.assertLess(r['stop_loss'],r['buy_zone_low'])
    def test_rr(self):
        r=self.result();entry=(r['buy_zone_low']+r['buy_zone_high'])/2
        self.assertAlmostEqual(r['risk_reward_ratio'],(r['take_profit']-entry)/(entry-r['stop_loss']),places=3)
    def test_missing_level_data(self):self.assertIsNone(module.levels(100,None,1,99,102)['take_profit'])
    def test_breakout_confirmed(self):self.assertEqual(self.result()['breakout_status'],'CONFIRMED')
    def test_breakout_weak(self):frame=self.buy.copy();frame.iloc[-1,frame.columns.get_loc('Volume')]=100000;self.assertEqual(self.result(frame)['breakout_status'],'WEAK_CONFIRMATION')
    def test_breakout_waiting(self):self.assertEqual(self.result(self.sell)['breakout_status'],'WAITING')
    def test_new_buy(self):self.assertEqual(self.result()['signal_state'],'YENI_AL')
    def test_buy_continues(self):
        previous=self.result();previous['data_timestamp']=(self.now-timedelta(minutes=5)).isoformat()
        self.assertEqual(self.result(previous=previous)['signal_state'],'AL_DEVAM')
    def test_weakening(self):self.assertEqual(module.lifecycle('IZLE',self.result(),self.now)['signal_state'],'ZAYIFLIYOR')
    def test_sell_reversal(self):self.assertEqual(self.result(self.sell,self.result())['signal_state'],'SAT_DONUS')
    def test_new_sell(self):self.assertEqual(self.result(self.sell)['signal_state'],'YENI_SAT')
    def test_sell_continues(self):self.assertEqual(module.lifecycle('SAT_ADAYI',self.result(self.sell),self.now)['signal_state'],'SAT_DEVAM')
    def test_recovery(self):self.assertEqual(module.lifecycle('IZLE',self.result(self.sell),self.now)['signal_state'],'TOPARLANIYOR')
    def test_age(self):r=self.result(previous=self.result(),current=self.now+timedelta(minutes=5));self.assertEqual(r['signal_age_minutes'],5)
    def test_next_session_reset(self):self.assertEqual(module.lifecycle('AL_ADAYI',self.result(),self.now+timedelta(days=1))['signal_state'],'YENI_AL')
    def test_future_state_reset(self):p=self.result();p['signal_started_at']=(self.now+timedelta(minutes=5)).isoformat();self.assertEqual(module.lifecycle('AL_ADAYI',p,self.now)['signal_state'],'YENI_AL')
    def test_same_bar_no_transition(self):r=self.result();self.assertEqual(self.result(previous=r)['signal_state'],'YENI_AL')
    def test_future_bar_lookahead(self):
        frame=self.buy.copy();row=frame.iloc[-1].copy();row['Close']=999;row['High']=1000;frame.loc[self.now]=row
        self.assertEqual(self.result(frame),self.result())
    def test_open_bar_excluded(self):
        frame=self.buy.copy();row=frame.iloc[-1].copy();row['Close']=999;row['High']=1000;frame.loc[self.now-timedelta(minutes=1)]=row
        self.assertEqual(self.result(frame),self.result())
    def test_frozen_frame_input(self):before=self.buy.copy();self.result();pd.testing.assert_frame_equal(before,self.buy)
    def test_persistence_restart(self):self.engine().one_round();row=module.read_report(self.location)['signals'][0];self.assertEqual(row['signal_state'],'YENI_AL');self.engine().one_round();self.assertEqual(module.read_report(self.location)['signals'][0]['signal_state'],'YENI_AL')
    def test_duplicate_history(self):
        engine=self.engine();engine.one_round();engine.one_round()
        history=load_history(self.location,self.now);self.assertEqual(len(history['events']),1)
    def test_frozen_history(self):
        engine=self.engine();engine.one_round();history=load_history(self.location,self.now)
        module._cache.clear();self.engine(provider=Mock(return_value=self.sell)).one_round()
        later=load_history(self.location,self.now)
        for key,row in history['events'].items():self.assertEqual(row,later['events'][key])
    def test_neutral_no_history_spam(self):
        self.engine(provider=Mock(return_value=pd.DataFrame())).one_round()
        self.assertFalse(self.location.runtime_file('gunluk_al_sat_gecmisi').exists())
    def test_cached_no_provider(self):module.observe_frames({'THYAO':self.buy});provider=Mock();self.engine(provider=provider).one_round();provider.assert_not_called()
    def test_xutum_provider_normalization(self):provider=Mock(return_value=self.buy);self.engine(['BIST:THYAO'],provider).one_round();provider.assert_called_once_with('THYAO')
    def test_unsupported_does_not_block(self):
        from borsapy.exceptions import APIError
        def provider(stock):
            if stock=='BAD':raise APIError("TradingView error: ['ser_1', 'invalid symbol']")
            return self.buy
        result=self.engine(['BAD','THYAO'],provider).one_round()
        self.assertEqual(result['diagnostics']['successful'],1);self.assertEqual(result['diagnostics']['skipped'],1)
    def test_provider_error_other_stock_saved(self):
        def provider(stock):
            if stock=='BAD':raise RuntimeError('provider failure')
            return self.buy
        with self.assertRaises(TaskIssue):self.engine(['BAD','THYAO'],provider).one_round()
        self.assertEqual(module.read_report(self.location)['signals'][0]['symbol'],'THYAO')
    def test_flag_off(self):
        with patch.dict(os.environ,{'INTRADAY_SIGNAL_ENGINE_ENABLED':'false'}):
            provider=Mock();self.assertTrue(self.engine(provider=provider).one_round()['disabled']);provider.assert_not_called();self.assertFalse(module.api_report({},self.location)['enabled'])
    def test_closed_market(self):
        self.now=self.now.replace(hour=20);provider=Mock();self.assertTrue(self.engine(provider=provider).one_round()['skipped']);provider.assert_not_called()
    def test_api_filters(self):self.engine().one_round();report=module.api_report({'signal':['AL'],'min_confidence':['60'],'limit':['1']},self.location,self.now);self.assertEqual(len(report['groups']['AL']),1)
    def test_invalid_filters(self):
        for query in ({'signal':['BAD']},{'limit':['0']},{'min_confidence':['nan']},{'limit':['1','2']},{'path':['private']}):
            with self.assertRaises(RecordError) as error:module.api_report(query,self.location,self.now)
            self.assertEqual(error.exception.status,400)
    def test_cache_503(self):
        with self.assertRaises(RecordError) as error:module.api_report({},self.location,self.now)
        self.assertEqual(error.exception.status,503)
    def test_corrupt_cache_503(self):
        self.location.public_file('gunluk_al_sat.json').write_text('{broken')
        with self.assertRaises(RecordError) as error:module.api_report({},self.location,self.now)
        self.assertEqual(error.exception.status,503)
    def test_stale_api_no_live_buy(self):
        self.engine().one_round();report=module.api_report({},self.location,self.now+timedelta(minutes=30))
        self.assertEqual(report['signals'][0]['signal'],'IZLE');self.assertFalse(report['signals'][0]['live_signal'])
    def test_http_api(self):
        from web_server import create_server
        self.engine().one_round();server=create_server('127.0.0.1',0,data_paths=self.location)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/intraday-signals?limit=1') as response:self.assertTrue(json.load(response)['enabled'])
        finally:server.shutdown();server.server_close();thread.join()
    def test_one_rsi_not_buy(self):self.assert_rsi_only(20)
    def test_one_rsi_not_sell(self):self.assert_rsi_only(90)
    def assert_rsi_only(self,value):
        frame=self.buy.copy();frame[['Open','Close']]=100;frame['High']=100.3;frame['Low']=99.7;frame['Volume']=100000
        with patch.object(module,'rsi',return_value=pd.Series([value]*len(frame),index=frame.index)):
            self.assertEqual(self.result(frame)['signal'],'IZLE')
    def test_atomic_history(self):
        engine=self.engine();engine.one_round();before=load_history(self.location,self.now)
        with patch('kullanici_kayitlari.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):engine.one_round()
        self.assertEqual(before,load_history(self.location,self.now))
    def test_rotation_bound(self):
        provider=Mock(return_value=self.buy);stocks=['S'+str(i) for i in range(100)]
        self.engine(stocks,provider).one_round();self.assertLessEqual(provider.call_count,module.ROTATION_BATCH)
    def test_worker_market_gate_and_isolation(self):
        from ana_motor import AnaMotor
        callback=Mock(side_effect=RuntimeError('intraday error'));alarm=Mock(return_value=0)
        motor=AnaMotor({'intraday_signals':callback,'alarm':alarm},self.location.runtime,clock=lambda:self.now,monotonic=lambda:0)
        try:
            motor.tick()
            for task in motor.tasks.values():
                if task.future:task.future.exception(timeout=2)
            motor.tick();self.assertEqual(alarm.call_count,1);self.assertEqual(motor.tasks['intraday_signals'].failures,1)
        finally:motor.shutdown()
    def test_continuation_without_major_change_no_history(self):
        engine=self.engine();engine.one_round();state=json.loads(engine.state_path.read_bytes())
        row=self.result();row.update(signal_state='AL_DEVAM',data_timestamp=(self.now+timedelta(minutes=5)).isoformat())
        engine.persist(row,state);self.assertEqual(len(load_history(self.location,self.now)['events']),1)
    def test_continuation_major_change_frozen(self):
        engine=self.engine();engine.one_round();state=json.loads(engine.state_path.read_bytes())
        row=self.result();row.update(signal_state='AL_DEVAM',technical_score=60,data_timestamp=(self.now+timedelta(minutes=5)).isoformat())
        engine.persist(row,state);self.assertEqual(len(load_history(self.location,self.now)['events']),2)
    def test_daily_prefix_rejected(self):
        frame=self.buy.copy();frame.index=frame.index.normalize()
        self.assertEqual(self.result(frame)['data_quality'],'INSUFFICIENT')
    def test_aggressive_polling_rejected(self):
        from ana_motor import AnaMotor
        with self.assertRaises(ValueError):AnaMotor({'intraday_signals':Mock()},self.location.runtime,intervals={'intraday_signals':1})
    def test_detail_signal_contract(self):
        self.engine().one_round()
        with patch('ana_motor.istanbul_now',return_value=self.now):
            self.assertEqual(module.stock_signal('THYAO',self.location)['signal'],'AL_ADAYI')
    def test_flag_missing_default_enabled(self):
        with patch.dict(os.environ):
            os.environ.pop('INTRADAY_SIGNAL_ENGINE_ENABLED',None)
            self.assertTrue(module.enabled())
    def test_flag_explicit_true(self):
        with patch.dict(os.environ,{'INTRADAY_SIGNAL_ENGINE_ENABLED':'true'}):self.assertTrue(module.enabled())
    def test_flag_explicit_false(self):
        with patch.dict(os.environ,{'INTRADAY_SIGNAL_ENGINE_ENABLED':'false'}):self.assertFalse(module.enabled())
    def worker_callbacks(self):
        from ana_motor_gorevleri import WorkerTasks
        worker=WorkerTasks.__new__(WorkerTasks)
        worker.directory=self.location.runtime;worker.stop=Mock();worker.bot=Mock()
        with patch('sirket_site_motoru.SirketSiteMotoru'):
            return worker,worker.callbacks()
    def test_worker_registration_missing_env(self):
        with patch.dict(os.environ):
            os.environ.pop('INTRADAY_SIGNAL_ENGINE_ENABLED',None)
            worker,jobs=self.worker_callbacks()
            self.assertEqual(jobs['intraday_signals'],worker.daily_intraday.one_round)
    def test_worker_registration_false(self):
        with patch.dict(os.environ,{'INTRADAY_SIGNAL_ENGINE_ENABLED':'false'}):
            _,jobs=self.worker_callbacks();self.assertNotIn('intraday_signals',jobs)
    def test_startup_log_once_enabled(self):
        with self.assertLogs(level='INFO') as captured:
            worker,_=self.worker_callbacks()
            with patch('sirket_site_motoru.SirketSiteMotoru'):worker.callbacks()
        self.assertEqual(sum('[INTRADAY_SIGNAL] enabled=true timeframe=5m market_gate=enabled' in text for text in captured.output),1)
    def test_startup_log_disabled(self):
        with patch.dict(os.environ,{'INTRADAY_SIGNAL_ENGINE_ENABLED':'false'}),self.assertLogs(level='INFO') as captured:
            self.worker_callbacks()
        self.assertTrue(any('[INTRADAY_SIGNAL] enabled=false' in text for text in captured.output))
    def test_closed_market_log_throttled(self):
        from ana_motor import AnaMotor
        self.now=self.now.replace(hour=20);mono=[0];callback=Mock()
        motor=AnaMotor({'intraday_signals':callback},self.location.runtime,clock=lambda:self.now,monotonic=lambda:mono[0])
        try:
            with self.assertLogs(level='INFO') as captured:
                motor.tick();motor.tick();mono[0]=299;motor.tick();mono[0]=300;motor.tick()
            self.assertEqual(sum('[INTRADAY_SIGNAL] market_closed skip' in text for text in captured.output),2)
            callback.assert_not_called()
        finally:motor.shutdown()
    def test_open_market_scheduler_runs(self):
        from ana_motor import AnaMotor
        callback=Mock(return_value={});motor=AnaMotor({'intraday_signals':callback},self.location.runtime,clock=lambda:self.now,monotonic=lambda:0)
        try:
            motor.tick();motor.tasks['intraday_signals'].future.result(timeout=2);self.assertEqual(callback.call_count,1)
        finally:motor.shutdown()
    def test_registered_job_respects_runtime_false(self):
        from ana_motor import AnaMotor
        callback=Mock();motor=AnaMotor({'intraday_signals':callback},self.location.runtime,clock=lambda:self.now,monotonic=lambda:0)
        try:
            with patch.dict(os.environ,{'INTRADAY_SIGNAL_ENGINE_ENABLED':'false'}):motor.tick()
            callback.assert_not_called()
        finally:motor.shutdown()
    def test_disabled_api_and_stock_no_cache_reads(self):
        with patch.dict(os.environ,{'INTRADAY_SIGNAL_ENGINE_ENABLED':'false'}),patch.object(module,'read_report') as reader:
            self.assertFalse(module.api_report({},self.location)['enabled']);self.assertIsNone(module.stock_signal('THYAO',self.location));reader.assert_not_called()


def load_history(location,current):
    return json.loads((location.runtime_file('gunluk_al_sat_gecmisi')/(current.date().isoformat()+'.json')).read_bytes())


if __name__=='__main__':unittest.main()
