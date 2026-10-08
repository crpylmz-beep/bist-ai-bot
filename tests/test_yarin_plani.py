import copy
import json
import tempfile
import unittest
from datetime import datetime,timedelta
from unittest.mock import Mock,patch
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo
from veri_yollari import DataPaths
import yarin_plani as m

IST=ZoneInfo('Europe/Istanbul')


def frame(direction=1,volume=2000,last_change=None):
    index=pd.bdate_range(end='2026-10-08',periods=80,tz=IST)
    close=np.linspace(90,100,80) if direction>0 else np.linspace(110,100,80)
    if last_change is not None:close[-1]=close[-2]*(1+last_change/100)
    data=pd.DataFrame({'Open':close-.2,'High':close+.8,'Low':close-.8,'Close':close,'Volume':1000.},index=index)
    data.iloc[-1,data.columns.get_loc('Volume')]=volume
    return data


class TomorrowPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.location=DataPaths(repo_root=self.tmp.name,environ={'BIST_DATA_DIR':self.tmp.name+'/data'});self.location.ensure()
        self.now=datetime(2026,10,8,19,tzinfo=IST);self.data=frame();self.holiday=lambda _:False
        m._cache.clear()
    def build(self,data=None,current=None):return m.build('THYAO',self.data if data is None else data,current or self.now,self.holiday)
    def get(self,provider=None):return m.get_plan('THYAO',self.location,self.now,provider or Mock(return_value=self.data),self.holiday)
    def test_closed_daily_reference(self):
        p=self.build(current=self.now.replace(hour=14));self.assertEqual(p['reference_price'],float(self.data.Close.iloc[-2]));self.assertEqual(p['as_of'],'2026-10-07T18:15:00+03:00')
    def test_after_close_reference(self):self.assertEqual(self.build()['reference_price'],100)
    def test_future_candle_not_used(self):
        future=self.data.copy();future.loc[pd.Timestamp('2026-10-09',tz=IST)]=[900,1000,800,950,1e9]
        self.assertEqual(self.build(),self.build(future))
    def test_open_daily_mutation_no_leakage(self):
        mutated=self.data.copy();mutated.iloc[-1]=[900,1000,800,950,1e9]
        self.assertEqual(self.build(current=self.now.replace(hour=14)),self.build(mutated,current=self.now.replace(hour=14)))
    def test_future_availability_excluded(self):
        data=self.data.copy();data['available_at']=data.index+pd.Timedelta(hours=18,minutes=15)
        data.iloc[-1,data.columns.get_loc('available_at')]=pd.Timestamp('2026-10-09',tz=IST)
        self.assertEqual(self.build(data)['reference_price'],float(data.Close.iloc[-2]))
    def test_insufficient_rows(self):self.assertEqual(self.build(self.data.tail(10))['plan_status'],'YETERSIZ_VERI')
    def test_missing_frame(self):self.assertEqual(self.build(pd.DataFrame())['plan_status'],'YETERSIZ_VERI')
    def test_missing_ohlc(self):self.assertIsNone(self.build(self.data.drop(columns='High'))['buy_zone_low'])
    def test_invalid_ohlc(self):
        data=self.data.copy();data.iloc[-1,data.columns.get_loc('Low')]=200
        self.assertEqual(self.build(data)['plan_status'],'YETERSIZ_VERI')
    def test_invalid_prices(self):
        data=self.data.copy();data.iloc[-1,data.columns.get_loc('Close')]=float('inf')
        self.assertEqual(self.build(data)['plan_status'],'YETERSIZ_VERI')
    def test_missing_session_not_compressed(self):self.assertEqual(self.build(self.data.drop(self.data.index[-10]))['plan_status'],'YETERSIZ_VERI')
    def test_duplicate_daily_dates(self):
        data=pd.concat([self.data,self.data.iloc[-1:].rename(index=lambda x:x+pd.Timedelta(hours=1))]);self.assertEqual(self.build(data)['plan_status'],'YETERSIZ_VERI')
    def test_weekend_and_holiday(self):
        p=m.build('THYAO',self.data,self.now,lambda day:day.isoformat()=='2026-10-09');self.assertEqual(p['plan_session'],'2026-10-12')
    def test_dynamic_zone(self):
        p=self.build();self.assertLessEqual(p['buy_zone_low'],p['buy_zone_high']);self.assertLess(p['stop_loss'],p['buy_zone_low'])
    def test_atr_influence(self):
        a=m.plan_levels(100,2,96,103,98,99);b=m.plan_levels(100,3,96,103,98,99);self.assertNotEqual(a,b)
    def test_support_influence(self):self.assertNotEqual(m.plan_levels(100,2,96,103,98,99),m.plan_levels(100,2,97,103,98,99))
    def test_resistance_influence(self):self.assertNotEqual(m.plan_levels(100,2,96,100.8,98,99),m.plan_levels(100,2,96,101.5,98,99))
    def test_take_profit(self):
        p=self.build();self.assertLess(p['entry_reference'],p['take_profit_low']);self.assertLessEqual(p['take_profit_low'],p['take_profit_high'])
    def test_stop_buffer(self):
        p=self.build();self.assertAlmostEqual(p['stop_loss'],p['support']-p['atr']*.25)
    def test_invalid_stop_protection(self):self.assertIsNone(m.plan_levels(10,20,1,12,9,9)['stop_loss'])
    def test_invalid_support_protection(self):self.assertIsNone(m.plan_levels(100,2,101,103,98,99)['stop_loss'])
    def test_invalid_zone(self):self.assertIsNone(m.plan_levels(100,2,98,98.1,99,99)['stop_loss'])
    def test_missing_atr(self):self.assertIsNone(m.plan_levels(100,None,96,103,98,99)['stop_loss'])
    def test_risk_reward_midpoint(self):
        p=self.build();entry=(p['buy_zone_low']+p['buy_zone_high'])/2;self.assertAlmostEqual(p['risk_reward_ratio'],(p['take_profit_low']-entry)/(entry-p['stop_loss']))
    def test_low_rr_warning(self):
        with patch.object(m,'plan_levels',return_value=dict(buy_zone_low=98,buy_zone_high=99,entry_reference=98.5,take_profit_low=100,take_profit_high=101,stop_loss=96,risk_reward_ratio=.6)):
            p=self.build();self.assertTrue(any('Risk/getiri' in x for x in p['warnings']));self.assertNotEqual(p['plan_status'],'UYGUN')
    def breakout(self,volume):
        data=self.data.copy();data.iloc[-1]=[100,101.3,99.8,101,volume];return self.build(data)
    def test_breakout_confirmed(self):self.assertEqual(self.breakout(2000)['volume_breakout_status'],'CONFIRMED')
    def test_breakout_weak(self):self.assertEqual(self.breakout(1000)['volume_breakout_status'],'WEAK_CONFIRMATION')
    def test_breakout_waiting(self):self.assertEqual(self.build()['volume_breakout_status'],'WAITING')
    def test_breakout_target(self):
        p=self.build();self.assertAlmostEqual(p['breakout_target'],p['resistance']+p['atr']*.6)
    def test_breakout_level_previous_structure(self):self.assertEqual(self.build()['volume_breakout_level'],self.data.High.iloc[-6:-1].max())
    def test_positive_trend(self):self.assertEqual(self.build()['trend_state'],'POSITIVE')
    def test_negative_trend_blocks(self):
        p=self.build(frame(-1));self.assertEqual(p['plan_status'],'BEKLE');self.assertIsNone(p['buy_zone_low'])
    def test_rsi_not_standalone(self):
        with patch.object(m,'rsi',return_value=pd.Series([20.]*80)):
            self.assertEqual(self.build(frame(-1))['plan_status'],'BEKLE')
    def test_macd_not_standalone(self):
        with patch.object(m,'macd',return_value=(None,None,pd.Series(np.linspace(1,2,80)))):
            self.assertEqual(self.build(frame(-1))['plan_status'],'BEKLE')
    def test_volume_confirmation(self):
        self.assertTrue(self.build()['confirmations']['Hacim teyidi var']);self.assertFalse(self.build(frame(volume=1000))['confirmations']['Hacim teyidi var'])
    def test_volume_missing(self):
        p=self.build(self.data.drop(columns='Volume'));self.assertIsNone(p['volume_ratio']);self.assertNotEqual(p['plan_status'],'UYGUN')
    def test_volume_negative(self):
        data=self.data.copy();data.iloc[-1,data.columns.get_loc('Volume')]=-1;self.assertIsNone(self.build(data)['volume_ratio'])
    def test_resistance_proximity(self):
        data=self.data.copy();data.iloc[-1]=[100.3,101,100,100.45,2000]
        self.assertTrue(any('dirence yakın' in x for x in self.build(data)['warnings']))
    def test_extension_blocks(self):
        p=self.build(frame(last_change=15));self.assertEqual(p['plan_status'],'BEKLE');self.assertIsNone(p['buy_zone_low']);self.assertTrue(any('uzamış' in x for x in p['warnings']))
    def test_seven_percent_drop(self):
        p=self.build(frame(last_change=-7));self.assertEqual(p['plan_status'],'BEKLE');self.assertIsNone(p['buy_zone_low']);self.assertTrue(any('%7' in x for x in p['warnings']))
    def test_confirmation_count(self):
        p=self.build();self.assertEqual(p['confirmation_total'],len(p['confirmations']));self.assertEqual(p['confirmation_count'],sum(p['confirmations'].values()))
    def test_confidence_bounds(self):
        for data in (self.data,frame(-1),frame(last_change=15)):
            self.assertTrue(0<=self.build(data)['confidence_score']<=100)
    def test_uygun(self):
        with patch.object(m,'rsi',return_value=pd.Series([60.]*80)),patch.object(m,'macd',return_value=(None,None,pd.Series(np.linspace(1,2,80)))):
            self.assertEqual(self.build()['plan_status'],'UYGUN')
    def test_temkinli(self):self.assertEqual(self.build()['plan_status'],'TEMKINLI')
    def test_reasons_real(self):
        p=self.build();self.assertIn('Fiyat SMA20 üzerinde',p['reasons']);self.assertNotIn('MACD momentum olumlu',p['reasons'])
    def test_frozen_immutable(self):
        p=self.get();path=self.location.runtime/'yarin_plan_arsivi/THYAO/2026-10-08.json';before=path.read_bytes()
        q=self.get(Mock(return_value=frame(last_change=15)));self.assertEqual(p,q);self.assertEqual(path.read_bytes(),before)
    def test_return_copy_isolation(self):
        p=self.get();p['reasons'].append('bad');self.assertNotIn('bad',self.get()['reasons'])
    def test_symbol_isolation(self):
        self.get();p=m.get_plan('ASELS',self.location,self.now,Mock(return_value=frame(-1)),self.holiday);self.assertEqual(p['symbol'],'ASELS');self.assertEqual(p['plan_status'],'BEKLE')
    def test_snapshot_future_rejected(self):
        self.get();path=self.location.runtime/'yarin_plan_arsivi/THYAO/2026-10-08.json';p=json.loads(path.read_text());p['as_of']='2026-10-09T18:15:00+03:00';path.write_text(json.dumps(p));self.assertIsNone(self.get())
    def test_corrupt_snapshot_preserved(self):
        path=self.location.runtime/'yarin_plan_arsivi/THYAO/2026-10-08.json';path.parent.mkdir(parents=True);path.write_text('{bad');self.assertIsNone(self.get());self.assertEqual(path.read_text(),'{bad')
    def test_stale_plan_not_live(self):
        self.get();self.now+=timedelta(days=1);p=self.get();self.assertFalse(p['is_current_reference']);self.assertEqual(p['view_status'],'BEKLE')
    def test_provider_fail_safe(self):self.assertIsNone(self.get(Mock(side_effect=RuntimeError('secret token'))))
    def test_disk_fail_safe(self):
        with patch.object(m,'atomic_json',side_effect=OSError('disk full')):self.assertIsNone(self.get())
    def test_no_writes_for_missing(self):
        self.get(Mock(return_value=pd.DataFrame()));self.assertFalse((self.location.runtime/'yarin_plan_arsivi').exists())
    def test_ram_bounded(self):
        with patch.object(m,'MAX_CACHE',2):
            for stock in ('THYAO','ASELS','BIMAS'):m.get_plan(stock,self.location,self.now,Mock(return_value=pd.DataFrame()),self.holiday)
            self.assertEqual(len(m._cache),2)
    def test_cache_no_duplicate_provider(self):
        provider=Mock(return_value=pd.DataFrame());self.get(provider);self.get(provider);self.assertEqual(provider.call_count,1)
    def test_existing_history_untouched(self):
        old=self.location.runtime/'performans_fiyat_cache.json';old.write_text('{"marker":true}');self.get();self.assertEqual(old.read_text(),'{"marker":true}')
    def test_daily_data_unknown_no_network(self):
        with patch('bist_bot.bp.Ticker') as ticker:
            self.assertTrue(m.daily_data('THYAO',self.location).empty);ticker.assert_not_called()
    def test_inputs_not_mutated(self):
        old=self.data.copy(deep=True);self.build();pd.testing.assert_frame_equal(old,self.data)
    def test_explicit_incomplete_bar(self):
        data=self.data.copy();data['complete']=True;data.iloc[-1,data.columns.get_loc('complete')]=False
        self.assertEqual(self.build(data)['reference_price'],float(data.Close.iloc[-2]))
    def test_safe_1811_not_closed(self):
        p=self.build(current=self.now.replace(hour=18,minute=11));self.assertEqual(p['as_of'],'2026-10-07T18:15:00+03:00')
    def test_real_cached_ohlcv_no_provider(self):
        bars=[dict(timestamp=str(at),open=float(r.Open),high=float(r.High),low=float(r.Low),close=float(r.Close),volume=float(r.Volume)) for at,r in self.data.iterrows()]
        self.location.runtime_file('performans_fiyat_cache.json').write_text(json.dumps({'THYAO':{'bars':bars}}))
        with patch('bist_bot.bp.Ticker') as ticker:
            result=m.get_plan('THYAO',self.location,self.now,holiday=self.holiday)
            self.assertEqual(result['reference_price'],100);ticker.assert_not_called()
    def test_selected_provider_reuses_normalization(self):
        self.location.public_file('bist_data.json').write_text(json.dumps({'hisseler':[{'sembol':'THYAO','teknik_gostergeler':{'mode':'TOMORROW','data_time':self.now.isoformat(),'bar_count':80}}]}))
        with patch('bist_bot.bp.Ticker') as ticker:
            ticker.return_value.history.return_value=self.data
            result=m.get_plan('THYAO',self.location,self.now,holiday=self.holiday)
            self.assertEqual(result['symbol'],'THYAO');ticker.assert_called_once_with('THYAO');ticker.return_value.history.assert_called_once_with(period='6mo')
    def test_missing_cache_volume_not_fabricated(self):
        bars=[dict(timestamp=str(at),open=float(r.Open),high=float(r.High),low=float(r.Low),close=float(r.Close)) for at,r in self.data.iterrows()]
        self.location.runtime_file('performans_fiyat_cache.json').write_text(json.dumps({'THYAO':{'bars':bars}}))
        with patch('bist_bot.bp.Ticker') as ticker:
            result=m.get_plan('THYAO',self.location,self.now,holiday=self.holiday)
            self.assertEqual(result['plan_status'],'YETERSIZ_VERI');self.assertIsNone(result['volume_ratio']);ticker.assert_not_called()
    def test_snapshot_identity_rejected(self):
        self.get();path=self.location.runtime/'yarin_plan_arsivi/THYAO/2026-10-08.json';value=json.loads(path.read_text());value['symbol']='ASELS';path.write_text(json.dumps(value));before=path.read_bytes()
        self.assertIsNone(self.get());self.assertEqual(path.read_bytes(),before)
    def test_future_snapshot_candle_changes_ignored(self):
        p=self.get();provider=Mock(side_effect=AssertionError('must not fetch'))
        self.assertEqual(self.get(provider),p);provider.assert_not_called()
    def test_weak_breakout_requires_positive_candle(self):
        data=self.data.copy();data.iloc[-1]=[101.2,101.4,100.5,101,2000]
        self.assertEqual(self.build(data)['volume_breakout_status'],'WEAK_CONFIRMATION')
    def test_upper_entry_below_take_profit(self):
        p=self.build();self.assertLess(p['buy_zone_high'],p['take_profit_low'])
    def test_missing_volume_not_confirmed_breakout(self):
        data=self.data.copy();data.iloc[-1]=[100,101.3,99.8,101,float('nan')]
        self.assertEqual(self.build(data)['volume_breakout_status'],'WEAK_CONFIRMATION')
    def test_unavailable_no_breakout_target(self):self.assertIsNone(self.build(self.data.tail(10))['breakout_target'])
    def test_cache_expiry_retry(self):
        provider=Mock(return_value=pd.DataFrame());self.get(provider);self.now+=timedelta(minutes=6);self.get(provider);self.assertEqual(provider.call_count,2)

    def test_http_api_compatible(self):
        import threading,urllib.request
        from web_server import create_server
        server=create_server('127.0.0.1',0,data_paths=self.location);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            with patch.object(m,'get_plan',return_value=self.build()):
                with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/stocks/THYAO') as r:value=json.load(r)
            self.assertIn('tomorrow_plan',value)
            for field in ('manuel','otomatik','ai_ozet','nihai_karar','alarmlar'):self.assertIn(field,value)
        finally:server.shutdown();server.server_close();t.join()

if __name__=='__main__':unittest.main()
