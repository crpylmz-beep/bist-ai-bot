import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from datetime import datetime,timedelta
import pandas as pd

import teknik_gostergeler as tech
from veri_yollari import DataPaths
from kullanici_kayitlari import UserRecords,atomic_json
from gun_ici_performans import GunIciPerformans
from ai_karar_motoru import evaluate
import bist_bot as bot


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.index=pd.date_range('2026-10-06 10:00',periods=40,freq='5min',tz='Europe/Istanbul')
        self.now=self.index[-1].to_pydatetime()+timedelta(minutes=5)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name,'LEARNING_ENABLED':'false','GUN_ICI_LEARNING_ENABLED':'false'}))

    def frame(self,close=None,volume=None,daily=False):
        close=close if close is not None else [100]*39+[102]
        index=pd.bdate_range(end='2026-10-06',periods=len(close),tz='Europe/Istanbul') if daily else self.index[:len(close)]
        return pd.DataFrame({'Open':close,'High':[p+.2 for p in close],'Low':[p-.2 for p in close],
                             'Close':close,'Volume':volume if volume is not None else [100]*(len(close)-1)+[300]},index=index)

    def doc(self,frame=None):return tech.calculate(self.frame() if frame is None else frame,self.now)

    def row(self,doc=None):
        return {'sembol':'THYAO','fiyat':102,'gun_ici_puan':75,'gun_ici_karar':'AL','gun_ici_rr':2,'gun_ici_stop':100,
                'gun_ici_kar_al':106,'veri_tarihi':self.index[-1].isoformat(),'teknik_gostergeler':doc or self.doc(),
                'teknik_puan':80,'canli_guncelleme':self.now.isoformat(),'rsi5':55,'rsi':55,'risk_getiri':2}

    def test_obv_rising_and_positive_breakout(self):
        value=self.doc()['obv'];self.assertEqual(value['trend'],'OBV_YUKSELEN');self.assertEqual(value['breakout'],'OBV_KIRILIM_POZITIF')
        self.assertEqual(value['value'],300);self.assertEqual(value['short_slope'],100)

    def test_obv_falling_and_negative_breakout(self):
        value=self.doc(self.frame([100]*39+[98]))['obv']
        self.assertEqual(value['trend'],'OBV_DUSEN');self.assertEqual(value['breakout'],'OBV_KIRILIM_NEGATIF')

    def test_obv_flat(self):self.assertEqual(self.doc(self.frame([100]*40))['obv']['trend'],'OBV_YATAY')

    def test_obv_positive_divergence(self):
        value=self.doc(self.frame([100]*36+[100,98,96,99],[100]*37+[10,10,1000]))['obv']
        self.assertEqual(value['divergence'],'POZITIF_UYUMSUZLUK')

    def test_obv_negative_divergence(self):
        value=self.doc(self.frame([100]*36+[100,102,104,101],[100]*37+[10,10,1000]))['obv']
        self.assertEqual(value['divergence'],'NEGATIF_UYUMSUZLUK')

    def test_vwap_above_and_reclaim(self):
        value=self.doc()['vwap'];self.assertEqual(value['position'],'VWAP_USTU');self.assertEqual(value['transition'],'VWAP_RECLAIM')
        self.assertAlmostEqual(value['session_value'],(3900*100+300*102)/4200)

    def test_vwap_below_and_loss(self):
        value=self.doc(self.frame([100]*39+[98]))['vwap'];self.assertEqual(value['position'],'VWAP_ALTI');self.assertEqual(value['transition'],'VWAP_KAYBI')

    def test_vwap_near(self):self.assertEqual(self.doc(self.frame([100]*40))['vwap']['position'],'VWAP_YAKIN')

    def test_vwap_resets_at_new_session_and_missing_opening_is_unknown(self):
        frame=self.frame();prior=frame.copy();prior.index-=pd.Timedelta(days=1);prior['Close']=200;prior['High']=200.2;prior['Low']=199.8
        full=pd.concat([prior,frame]);value=self.doc(full)['vwap']
        self.assertAlmostEqual(value['session_value'],self.doc()['vwap']['session_value'])
        self.assertEqual(self.doc(frame.iloc[1:])['vwap']['status'],'UNKNOWN')

    def test_vwap_gap_unknown_without_hiding_price_momentum(self):
        value=self.doc(self.frame().drop(self.index[10]));self.assertEqual(value['vwap']['status'],'UNKNOWN');self.assertEqual(value['momentum']['status'],'OK')

    def test_daily_does_not_fake_session_vwap(self):
        value=tech.calculate(self.frame(daily=True),datetime(2026,10,6,19,tzinfo=tech.ISTANBUL),'TOMORROW')
        self.assertIsNone(value['vwap']['session_value']);self.assertIsNotNone(value['vwap']['reference_20']);self.assertFalse(value['stale'])

    def test_bollinger_squeeze_volume_momentum_break(self):
        value=self.doc()['bollinger'];self.assertTrue(value['squeeze']);self.assertTrue(value['upper_break']);self.assertTrue(value['expansion']);self.assertTrue(value['squeeze_volume_momentum_break'])

    def test_bollinger_lower_break(self):self.assertTrue(self.doc(self.frame([100]*39+[98]))['bollinger']['lower_break'])

    def test_bollinger_return_inside(self):self.assertTrue(self.doc(self.frame([100]*38+[102,100]))['bollinger']['return_inside'])

    def test_bollinger_no_combo_without_volume_confirmation(self):self.assertFalse(self.doc(self.frame(volume=[100]*40))['bollinger']['squeeze_volume_momentum_break'])

    def test_momentum_strengthening(self):
        value=self.doc(self.frame([100]*35+[100,100,100.2,100.6,101.4]))['momentum']
        self.assertEqual(value['state'],'GUCLENIYOR');self.assertGreater(value['acceleration'],0)

    def test_momentum_weakening_and_negative_turn(self):
        value=self.doc(self.frame([100]*39+[98]))['momentum'];self.assertEqual(value['state'],'ZAYIFLIYOR');self.assertTrue(value['negative_turn'])

    def test_momentum_neutral_and_candle_position(self):
        value=self.doc(self.frame([100]*40))['momentum'];self.assertEqual(value['state'],'NOTR');self.assertEqual(value['close_position_pct'],50)

    def test_indicator_insufficiency_is_independent(self):
        value=self.doc(self.frame([100]*5));self.assertEqual(value['bollinger']['status'],'UNKNOWN');self.assertEqual(value['momentum']['status'],'OK')
        self.assertIsNone(value['bollinger']['upper'])

    def test_missing_or_zero_volume_is_not_fake_vwap_or_obv(self):
        for volumes in ([0]*40,[float('nan')]*40):
            value=self.doc(self.frame(volume=volumes));self.assertIsNone(value['vwap']['session_value']);self.assertIsNone(value['obv']['value']);self.assertEqual(value['bollinger']['status'],'OK')
            json.dumps(value,allow_nan=False)

    def test_stale_data_reduces_confidence_and_cannot_add_shadow_bonus(self):
        value=tech.calculate(self.frame(),self.now+timedelta(minutes=30));self.assertTrue(value['stale']);self.assertLess(value['confidence'],50)
        result=tech.shadow(self.row(value),75,self.now+timedelta(minutes=30),'INTRADAY');self.assertEqual(result['teknik_shadow_duzeltmesi'],0)

    def test_future_and_open_bars_cannot_change_any_indicator_or_shadow(self):
        original=self.frame();future=original.iloc[-1:].copy();future.index+=pd.Timedelta(minutes=5)
        for k in ('Close','High','Low','Open','Volume'):future[k]=1e8
        before=self.doc(original);after=self.doc(pd.concat([original,future]));self.assertEqual(before,after)
        self.assertEqual(tech.shadow(self.row(before),75,self.now,'INTRADAY'),tech.shadow(self.row(after),75,self.now,'INTRADAY'))
        self.assertEqual(tech.calculate(original,self.now-timedelta(minutes=2))['bar_count'],39)

    def test_daily_unclosed_and_future_session_extremes_are_excluded(self):
        frame=self.frame(daily=True);signal=datetime(2026,10,6,12,tzinfo=tech.ISTANBUL)
        changed=frame.copy();changed.iloc[-1]=1e9
        self.assertEqual(tech.calculate(frame,signal,'TOMORROW'),tech.calculate(changed,signal,'TOMORROW'))
        future=frame.iloc[-1:].copy();future.index+=pd.Timedelta(days=1);future.iloc[:]=1e10
        self.assertEqual(tech.calculate(frame,signal,'TOMORROW'),tech.calculate(pd.concat([frame,future]),signal,'TOMORROW'))

    def test_late_available_revision_does_not_leak(self):
        frame=self.frame();frame['available_at']=[(i+pd.Timedelta(minutes=5)).isoformat() for i in frame.index]
        frame.loc[self.index[-1],'available_at']=(self.now+timedelta(minutes=5)).isoformat()
        self.assertEqual(self.doc(frame)['bar_count'],39)

    def test_future_snapshot_is_unknown_and_cannot_affect_score(self):
        row=self.row();row['teknik_gostergeler']['asof']=(self.now+timedelta(minutes=1)).isoformat();row['zaman']=self.now.isoformat()
        self.assertTrue(all(v is None for v in tech.features(row).values()));self.assertEqual(tech.shadow(row,75,self.now,'INTRADAY')['teknik_shadow_duzeltmesi'],0)

    def test_shadow_never_changes_raw_score_or_decision_and_is_bounded(self):
        row=self.row();before=copy.deepcopy(row);result=tech.shadow(row,75,self.now,'INTRADAY')
        self.assertEqual(row,before);self.assertEqual(result['teknik_ana_skor_etkisi'],0);self.assertFalse(result['teknik_learning_enabled']);self.assertLessEqual(abs(result['teknik_shadow_duzeltmesi']),2)

    def test_hard_safety_gates_cannot_be_overridden(self):
        for change in ({'haber_puani':-1},{'makro_puani':-1},{'sektor_puani':-1},{'gun_ici_rr':.5},{'gun_ici_stop':103},{'acilisa_gore_degisim':-6},{'acilisa_gore_degisim':8},{'rsi5':80},{'_durum':'BAD'}):
            row=self.row();row.update(change)
            with self.subTest(change=change):self.assertLessEqual(tech.shadow(row,75,self.now,'INTRADAY')['teknik_shadow_duzeltmesi'],0)
        self.assertEqual(tech.shadow(self.row(),20,self.now,'INTRADAY')['teknik_shadow_duzeltmesi'],0)

    def test_weights_are_separate_and_future_or_cross_mode_cannot_apply(self):
        with patch.dict(os.environ,{'INTRADAY_OBV_WEIGHT':'1','TOMORROW_OBV_WEIGHT':'0'}):
            intra=tech.shadow(self.row(),75,self.now,'INTRADAY');tom=tech.shadow(self.row(),75,self.now,'TOMORROW')
            self.assertEqual(intra['teknik_katkilar']['obv'],1);self.assertEqual(tom['teknik_katkilar']['obv'],0)
        with patch.dict(os.environ,{'INTRADAY_OBV_WEIGHT':'10'}),self.assertRaises(ValueError):tech.shadow(self.row(),75,self.now,'INTRADAY')

    def test_ai_reasons_without_duplicate_score(self):
        row=self.row();without=evaluate({k:v for k,v in row.items() if k!='teknik_gostergeler'},current=self.now)
        result=evaluate(row,current=self.now)
        self.assertEqual(result['ai_score'],without['ai_score']);self.assertEqual(result['karar'],without['karar'])
        self.assertIn('Fiyat seans VWAP üzerinde',result['reasons_positive']);self.assertIn('OBV yükselen trendde',result['reasons_positive'])

    def test_stale_ai_cannot_be_strong_buy(self):
        row=self.row();row['teknik_gostergeler']['data_time']=(self.now-timedelta(hours=1)).isoformat()
        result=evaluate(row,current=self.now);self.assertLess(result['confidence'],50);self.assertNotIn(result['karar'],('AL','GUCLU_AL'))

    def test_api_reads_same_indicator_snapshot_without_calculation_and_preserves_alarm_identity(self):
        row=self.row();path=self.location.public/'gun_ici_tum.json';atomic_json(path,{'hisseler':[row],'updated_at':self.now.isoformat()})
        records=UserRecords(self.location.users,self.location.web,public_dir=self.location.public)
        with patch('kullanici_kayitlari.now',return_value=self.now.isoformat()),patch('teknik_gostergeler.calculate',side_effect=AssertionError('No recalc')):
            first=records.automatic('THYAO','GUN_ICI')
        with patch('kullanici_kayitlari.now',return_value=(self.now+timedelta(hours=1)).isoformat()):second=records.automatic('THYAO','GUN_ICI')
        self.assertEqual(first['analiz_kimligi'],second['analiz_kimligi']);self.assertEqual(first['teknik_gostergeler'],row['teknik_gostergeler']);self.assertTrue(second['teknik_gostergeler']['stale'])

    def test_intraday_rank_and_frozen_record_are_not_mutated_by_later_market_data(self):
        engine=GunIciPerformans(self.location,clock=lambda:self.now)
        row=self.row();before=row['gun_ici_puan'];top=engine.rank([row]);self.assertEqual(top[0]['gun_ici_final_puan'],before)
        ids=engine.record(top);self.assertTrue(ids)
        frozen=copy.deepcopy(engine.state()['kayitlar'][0]['teknik_gostergeler'])
        row['teknik_gostergeler']['obv']['trend']='OBV_DUSEN';engine.record([row])
        self.assertEqual(engine.state()['kayitlar'][0]['teknik_gostergeler'],frozen)

    def test_actual_intraday_pipeline_uses_no_future_candle(self):
        original=self.frame();future=original.iloc[-1:].copy();future.index+=pd.Timedelta(minutes=5);future.iloc[:]=1e8
        with patch.object(bot,'datetime',wraps=datetime) as clock,patch.object(bot,'canli_makro_puani_getir',return_value={}):
            clock.now.return_value=self.now
            before=bot.gun_ici_analiz_hesapla('THYAO',original);after=bot.gun_ici_analiz_hesapla('THYAO',pd.concat([original,future]))
        self.assertIsNotNone(before);self.assertEqual(before,after);self.assertEqual(before['teknik_gostergeler']['model'],tech.MODEL)

    def test_actual_daily_pipeline_reuses_one_history_call_and_common_math(self):
        frame=self.frame(daily=True);current=datetime(2026,10,6,19,tzinfo=tech.ISTANBUL)
        ticker=Mock();ticker.history.return_value=frame
        with patch.object(bot.bp,'Ticker',return_value=ticker),patch.object(bot,'datetime',wraps=datetime) as clock,patch.object(bot,'yarin_top10_canli_guncelle'),patch.object(bot,'canli_makro_puani_getir',return_value={}):
            clock.now.return_value=current;result=bot.hisse_analiz_hesapla('THYAO')
        self.assertIsNotNone(result);ticker.history.assert_called_once();self.assertEqual(result['teknik_gostergeler']['mode'],'TOMORROW')
        self.assertAlmostEqual(result['boll_orta'],result['teknik_gostergeler']['bollinger']['middle'])

    def test_empty_legacy_and_unknown_time_are_safe(self):
        self.assertTrue(all(v is None for v in tech.features({}).values()))
        value=tech.calculate(pd.DataFrame(),self.now);self.assertEqual(value['confidence'],0);json.dumps(value,allow_nan=False)
        with self.assertRaises(ValueError):tech.calculate(self.frame(),self.now.replace(tzinfo=None))

    def test_stock_http_api_exposes_frozen_indicators_and_preserves_legacy_levels(self):
        import threading
        import urllib.request
        from web_server import create_server
        row=self.row();row.update(karar_hedef=106,karar_stop=100,karar_alim_alt=101,karar_alim_ust=102)
        path=self.location.public/'bist_data.json'
        atomic_json(path,{'hisseler':[row]});before=path.read_bytes()
        records=UserRecords(self.location.users,Path('webapp').resolve(),public_dir=self.location.public)
        server=create_server('127.0.0.1',0,records,data_paths=self.location)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/stocks/THYAO') as response:
            payload=json.load(response)
        self.assertIn('teknik_gostergeler',payload['otomatik'])
        self.assertEqual(payload['otomatik']['teknik_gostergeler']['obv']['trend'],'OBV_YUKSELEN')
        self.assertEqual(payload['otomatik']['hedef'],106)
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
