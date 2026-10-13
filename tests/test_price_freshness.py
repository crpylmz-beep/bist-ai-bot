import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from fiyat_guncelligi import price_metadata, preserve_newer_price
from fiyat_guncelligi import daily_change
from tests import test_ana_motor as coordinator_tests
from unittest.mock import Mock
from unittest.mock import patch
from pathlib import Path
import tempfile,json

class PriceTests(unittest.TestCase):
    def test_daily_change_uses_previous_close_not_open(self):
        self.assertAlmostEqual(daily_change(7.45,7.50),-0.6666666667)
    def test_invalid_previous_close_is_unknown(self):
        for value in (0,None,float('nan'),float('inf')):
            self.assertIsNone(daily_change(7.45,value))
    def test_every_locally_available_symbol_uses_same_daily_formula(self):
        symbols=set()
        for name in ('bist_data.json','gun_ici_tum.json'):
            source=Path(__file__).resolve().parents[1]/'webapp/data'/name
            document=json.loads(source.read_text())
            symbols.update(row['sembol'] for row in document.get('hisseler',[]) if isinstance(row,dict) and row.get('sembol'))
        self.assertGreater(len(symbols),500)
        for symbol in symbols:
            with self.subTest(symbol=symbol):
                row=preserve_newer_price({}, {'sembol':symbol,'fiyat':7.45,'onceki_kapanis':7.5,
                    'fiyat_zamani':'2026-10-13T18:10:00+03:00','onceki_kapanis_tarihi':'2026-10-12','degisim':1.92})
                self.assertAlmostEqual(row['gunluk_degisim'],-2/3)
    def test_daily_close_time_is_provider_session_not_rewrite_time(self):
        row=price_metadata(datetime(2026,10,13),True,datetime(2026,10,13,19,tzinfo=ZoneInfo('Europe/Istanbul')))
        self.assertEqual(row['fiyat_zamani'],'2026-10-13T18:10:00+03:00')
        self.assertEqual(row['fiyat_turu'],'SESSION_CLOSE')
    def test_delayed_daily_bar_not_claimed_final_before_feed_close(self):
        row=price_metadata(datetime(2026,10,13),True,datetime(2026,10,13,18,20,tzinfo=ZoneInfo('Europe/Istanbul')))
        self.assertEqual(row['fiyat_turu'],'DAILY')
    def test_old_provider_day_stays_old(self):
        row=price_metadata(datetime(2026,10,12),True,datetime(2026,10,13,19,tzinfo=ZoneInfo('Europe/Istanbul')))
        self.assertTrue(row['fiyat_zamani'].startswith('2026-10-12'))
    def test_no_price_rounding_or_manual_price(self):
        previous={'fiyat':7.45,'fiyat_zamani':'2026-10-13T18:10:00+03:00'}
        stale={'fiyat':7.43,'fiyat_zamani':'2026-10-13T17:55:00+03:00','score':80}
        self.assertEqual(preserve_newer_price(previous,stale),dict(stale,fiyat=7.45,fiyat_zamani=previous['fiyat_zamani']))
    def test_new_observation_accepted(self):
        self.assertEqual(preserve_newer_price({'fiyat':7.43,'fiyat_zamani':'2026-10-13T17:55:00+03:00'}, {'fiyat':7.45,'fiyat_zamani':'2026-10-13T18:10:00+03:00'})['fiyat'],7.45)
    def test_public_json_writer_preserves_newer_provider_price(self):
        import bist_bot as bot
        import pandas as pd
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bist_data.json'
            path.write_text(json.dumps({'hisseler':[{'sembol':'GENKM','fiyat':7.45,'fiyat_zamani':'2026-10-13T18:10:00+03:00'}]}))
            ticker=Mock();ticker.history.return_value=pd.DataFrame()
            with patch.object(bot,'DATA_FILE',str(path)),patch.object(bot.bp,'Ticker',return_value=ticker),patch.object(bot.bp,'Index',return_value=Mock(info={})),patch.object(bot,'sinyal_sinifi',return_value='IZLE'),patch.object(bot,'guclu_tepki_mi',return_value=False):
                bot.web_verisi_kaydet([{'sembol':'GENKM','fiyat':7.43,'fiyat_zamani':'2026-10-13T17:55:00+03:00','extra':123}])
            row=json.loads(path.read_text())['hisseler'][0]
            self.assertEqual(row['fiyat'],7.45);self.assertEqual(row['extra'],123)

class ClosingScanTests(unittest.TestCase):
    setUp=coordinator_tests.CoordinatorTests.setUp
    motor=coordinator_tests.CoordinatorTests.motor
    complete=coordinator_tests.CoordinatorTests.complete
    def test_closing_scan_one_completed_cycle(self):
        self.current=datetime(2026,10,6,19,tzinfo=ZoneInfo('Europe/Istanbul'))
        callback=Mock(return_value={'cycle_complete':True})
        motor=self.motor({'full_scan':callback});motor.tick();self.complete(motor)
        self.assertEqual(callback.call_count,1)
        self.mono=1000;motor.tick();self.assertEqual(callback.call_count,1)
        self.assertEqual(motor.state['last_close_scan_day'],'2026-10-06')
    def test_close_scan_waits_for_delayed_provider(self):
        self.current=datetime(2026,10,6,18,20,tzinfo=ZoneInfo('Europe/Istanbul'))
        callback=Mock(return_value={'cycle_complete':True})
        motor=self.motor({'full_scan':callback});motor.tick();callback.assert_not_called()
        self.current=datetime(2026,10,6,18,30,tzinfo=ZoneInfo('Europe/Istanbul'))
        motor.tick();self.complete(motor);callback.assert_called_once()
    def test_preclose_cycle_finishing_after_close_is_not_final_close_scan(self):
        self.current=datetime(2026,10,6,18,9,tzinfo=ZoneInfo('Europe/Istanbul'))
        motor=self.motor({'full_scan':Mock(return_value={'cycle_complete':True})})
        motor.tick()
        self.current=datetime(2026,10,6,18,16,tzinfo=ZoneInfo('Europe/Istanbul'))
        self.complete(motor)
        self.assertNotIn('last_close_scan_day',motor.state)
