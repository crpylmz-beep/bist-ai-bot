import copy
import hashlib
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from kullanici_kayitlari import UserRecords
import fiyat_alarm_motoru as engine


class AlarmEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.web=self.root/'webapp'
        (self.web/'data').mkdir(parents=True)
        self.records=UserRecords(self.root/'private',self.web)
        self.time=datetime(2026,10,6,12,0,tzinfo=ZoneInfo('Europe/Istanbul'))
        self.enterContext(patch('kullanici_kayitlari.now',side_effect=lambda:self.time.isoformat(timespec='seconds')))
        self.path=self.records.data_dir/'fiyat_alarmlari.json'

    def alarm(self,user='u1',stock='THYAO',target=300,operator='>='):
        kind='FIYAT_USTU' if operator=='>=' else 'FIYAT_ALTI'
        return self.records.create_alarm(user,stock,{'kaynak':'MANUEL','alarm_turu':kind,'hedef_fiyat':target})[0]

    def run_round(self,provider):
        return engine.alarmlari_kontrol_et(self.records,provider,clock=lambda:self.time)

    def stored(self):
        return json.loads(self.path.read_text())

    def test_threshold_equality_for_both_directions(self):
        for operator in ('>=','<='):
            with self.subTest(operator=operator):
                user='up' if operator=='>=' else 'down'
                self.alarm(user=user,operator=operator)
        provider=Mock(return_value=300)
        result=self.run_round(provider)
        self.assertEqual(result['tetiklenen_alarm'],2)
        provider.assert_called_once_with('THYAO')
        data=self.stored()
        for user in ('up','down'):
            alarm=data['kullanicilar'][user][0]
            self.assertFalse(alarm['aktif'])
            self.assertEqual(alarm['status'],'TRIGGERED')
            self.assertEqual(alarm['triggered_price'],300)
            self.assertTrue(alarm['triggered_at'].endswith('+03:00'))
            self.assertEqual(data['pending_notifications'][user][0]['status'],'PENDING')

    def test_condition_absent_keeps_alarm_active_and_does_not_write(self):
        self.alarm(target=300)
        self.alarm(stock='EREGL',target=20,operator='<=')
        before=self.path.read_bytes()
        result=self.run_round(lambda stock:290 if stock=='THYAO' else 21)
        self.assertEqual(result['tetiklenen_alarm'],0)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertNotIn('pending_notifications',self.stored())

    def test_trigger_is_once_only_and_event_is_not_duplicated(self):
        self.alarm()
        provider=Mock(return_value=301)
        self.run_round(provider)
        before=self.path.read_bytes()
        second=self.run_round(provider)
        self.assertEqual(second['aktif_alarm'],0)
        self.assertEqual(second['tetiklenen_alarm'],0)
        provider.assert_called_once_with('THYAO')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(len(self.stored()['pending_notifications']['u1']),1)

    def test_inactive_and_deleted_alarms_do_not_fetch_or_trigger(self):
        inactive=self.alarm(stock='THYAO')
        deleted=self.alarm(stock='EREGL')
        self.records.change_alarm('u1',inactive['id'])
        self.records.change_alarm('u1',deleted['id'],delete=True)
        provider=Mock(return_value=999)
        self.run_round(provider)
        provider.assert_not_called()
        self.assertFalse(self.records.alarms('u1','THYAO')[0]['aktif'])
        self.assertEqual(self.records.alarms('u1','EREGL'),[])

    def test_same_symbol_shared_across_users_has_one_quote_and_separate_events(self):
        self.alarm('u1',target=300)
        self.alarm('u2',target=320)
        self.alarm('u2',target=305)
        provider=Mock(return_value=310)
        result=self.run_round(provider)
        provider.assert_called_once_with('THYAO')
        self.assertEqual(result['tetiklenen_alarm'],2)
        u1=self.records.alarms('u1','THYAO')
        u2=self.records.alarms('u2','THYAO')
        self.assertEqual(len(u1),1)
        self.assertEqual(len(u2),2)
        self.assertTrue(u2[0]['aktif'])
        self.assertEqual(len(self.stored()['pending_notifications']['u1']),1)
        self.assertEqual(len(self.stored()['pending_notifications']['u2']),1)

    def test_one_provider_error_does_not_block_other_stock(self):
        self.alarm(stock='EREGL',target=20)
        self.alarm(stock='THYAO',target=300)
        def provider(stock):
            if stock=='EREGL':raise ConnectionError('stub failure')
            return 310
        result=self.run_round(provider)
        self.assertEqual(result['tetiklenen_alarm'],1)
        self.assertEqual(result['fiyat_hatalari'],{'EREGL':'ConnectionError'})
        self.assertTrue(self.records.alarms('u1','EREGL')[0]['aktif'])
        self.assertFalse(self.records.alarms('u1','THYAO')[0]['aktif'])

    def test_ai_snapshot_and_range_upper_boundary_are_respected(self):
        path=self.web/'data'/'bist_data.json'
        row={'sembol':'THYAO','karar_giris_alt':290,'karar_giris_ust':292,
             'karar_hedef':300,'karar_stop':280}
        path.write_text(json.dumps({'hisseler':[row]}))
        original=self.records.automatic('THYAO')
        body={'kaynak':'AI','alarm_turu':'AI_ALIM_BOLGESI','analiz_kimligi':original['analiz_kimligi']}
        created=self.records.create_alarm('u1','THYAO',body)[0]
        frozen=copy.deepcopy(created['seviye_snapshot'])
        row.update(karar_giris_alt=400,karar_giris_ust=410)
        path.write_text(json.dumps({'hisseler':[row]}))
        before=path.read_bytes()
        self.assertEqual(self.run_round(lambda _:293)['tetiklenen_alarm'],0)
        self.assertEqual(self.run_round(lambda _:292)['tetiklenen_alarm'],1)
        actual=self.records.alarms('u1','THYAO')[0]
        self.assertEqual(actual['hedef_fiyat'],290)
        self.assertEqual(actual['hedef_fiyat_ust'],292)
        self.assertEqual(actual['seviye_snapshot'],frozen)
        self.assertEqual(path.read_bytes(),before)

    def test_cancel_or_delete_during_price_fetch_is_honored(self):
        for delete in (False,True):
            with self.subTest(delete=delete):
                stock='THYAO' if delete else 'EREGL'
                alarm=self.alarm(stock=stock)
                def provider(_):
                    self.records.change_alarm('u1',alarm['id'],delete=delete)
                    return 999
                result=self.run_round(provider)
                self.assertEqual(result['tetiklenen_alarm'],0)
                self.assertNotIn('pending_notifications',self.stored())

    def test_new_alarm_during_fetch_waits_until_next_round(self):
        self.alarm(target=300)
        def provider(_):
            self.alarm(target=305)
            return 310
        self.assertEqual(self.run_round(provider)['tetiklenen_alarm'],1)
        alarms=self.records.alarms('u1','THYAO')
        self.assertFalse(alarms[0]['aktif'])
        self.assertTrue(alarms[1]['aktif'])

    def test_concurrent_rounds_commit_only_one_trigger_and_event(self):
        self.alarm()
        barrier=threading.Barrier(4)
        def provider(_):
            barrier.wait(timeout=5)
            return 310
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.run_round(provider),range(4)))
        self.assertEqual(sum(r['tetiklenen_alarm'] for r in results),1)
        self.assertEqual(len(self.stored()['pending_notifications']['u1']),1)

    def test_atomic_failure_preserves_alarm_and_outbox_then_retry_succeeds(self):
        self.alarm()
        before=self.path.read_bytes()
        with patch('kullanici_kayitlari.os.replace',side_effect=OSError('stub disk error')):
            with self.assertRaises(OSError):self.run_round(lambda _:310)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertNotIn('pending_notifications',self.stored())
        self.assertFalse(list(self.records.data_dir.glob('.user-*.tmp')))
        self.assertEqual(self.run_round(lambda _:310)['tetiklenen_alarm'],1)
        self.assertEqual(len(self.stored()['pending_notifications']['u1']),1)

    def test_invalid_prices_and_records_do_not_trigger_or_block_valid_records(self):
        self.alarm(stock='THYAO')
        self.alarm(stock='EREGL',target=20)
        result=self.run_round(lambda stock:float('nan') if stock=='THYAO' else 25)
        self.assertEqual(result['tetiklenen_alarm'],1)
        self.assertTrue(self.records.alarms('u1','THYAO')[0]['aktif'])
        with self.records.locked('fiyat_alarmlari.json') as (path,data):
            data['kullanicilar']['u1'].append({'id':'bad','aktif':True,'sembol':'THYAO','kaynak':'MANUEL',
              'created_at':self.time.isoformat(),'operator':'==','hedef_fiyat':300})
            engine.atomic_json(path,data)
        result=self.run_round(lambda _:310)
        self.assertEqual(result['gecersiz_alarm'],1)
        self.assertEqual(result['tetiklenen_alarm'],1)

    def test_stale_future_and_pre_creation_quotes_are_rejected(self):
        self.alarm()
        for delta in (-601,1,-1):
            with self.subTest(delta=delta):
                quote=engine.FiyatVerisi(999,self.time+timedelta(seconds=delta),'stub')
                self.assertEqual(self.run_round(lambda _:quote)['tetiklenen_alarm'],0)
        self.assertTrue(self.records.alarms('u1','THYAO')[0]['aktif'])

    def test_old_quote_is_rechecked_at_commit_after_slow_other_symbol(self):
        self.alarm(stock='EREGL',target=20)
        self.alarm(stock='THYAO')
        def provider(stock):
            if stock=='EREGL':return 25
            self.time+=timedelta(seconds=601)
            return 310
        result=self.run_round(provider)
        self.assertEqual(result['tetiklenen_alarm'],1)
        self.assertEqual(result['fiyat_hatalari']['EREGL'],'StalePriceAtCommit')
        self.assertTrue(self.records.alarms('u1','EREGL')[0]['aktif'])

    def test_existing_cache_is_used_without_provider_and_market_outputs_are_read_only(self):
        self.alarm()
        (self.web/'data'/'gun_ici_tum.json').write_text(json.dumps({
            'updated_at':self.time.isoformat(),'hisseler':[{'sembol':'THYAO','fiyat':310}]}))
        for name in ['gun_ici_top10.json','yarin_top10.json','kap_alarmlar.json','makro_canli_etki.json']:
            (self.web/'data'/name).write_text('{}')
        archive=self.web/'data'/'yarin_top10_arsiv';archive.mkdir()
        (archive/'2026-10-05.json').write_text('{}')
        paths=list((self.web/'data').rglob('*.json'))
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        fallback=Mock(side_effect=AssertionError('Network must not be used'))
        provider=engine.MevcutFiyatSaglayici(self.web,clock=lambda:self.time,fallback=fallback)
        self.assertEqual(self.run_round(provider)['tetiklenen_alarm'],1)
        fallback.assert_not_called()
        self.assertEqual(hashes,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_cache_without_timezone_or_before_alarm_uses_existing_provider_fallback(self):
        self.alarm()
        path=self.web/'data'/'gun_ici_tum.json'
        for stamp in ['2026-10-06 12:00:00',(self.time-timedelta(minutes=1)).isoformat()]:
            path.write_text(json.dumps({'updated_at':stamp,'hisseler':[{'sembol':'THYAO','fiyat':999}]}))
            fallback=Mock(return_value=290)
            provider=engine.MevcutFiyatSaglayici(self.web,not_before={'THYAO':self.time},
                clock=lambda:self.time,fallback=fallback)
            self.assertEqual(self.run_round(provider)['tetiklenen_alarm'],0)
            fallback.assert_called_once_with('THYAO')

    def test_optional_loop_recovers_from_failed_round_without_sleeping(self):
        class Stop:
            count=0
            def is_set(self):return self.count>=2
            def wait(self,seconds):self.count+=1
        stop=Stop()
        with patch.object(engine,'alarmlari_kontrol_et',side_effect=[OSError('stub'),{}]) as check:
            engine.surekli_izle(1,records=self.records,stop_event=stop)
        self.assertEqual(check.call_count,2)
        with self.assertRaises(ValueError):engine.surekli_izle(0,records=self.records)

    def test_default_borsapy_path_fetches_one_quote_for_all_stock_alarms(self):
        self.alarm('u1',target=300)
        self.alarm('u2',target=305)
        ticker=SimpleNamespace(fast_info=SimpleNamespace(last_price=310))
        with patch('borsapy.Ticker',return_value=ticker) as factory:
            result=engine.alarmlari_kontrol_et(self.records,clock=lambda:self.time)
        factory.assert_called_once_with('THYAO')
        self.assertEqual(result['tetiklenen_alarm'],2)
        self.assertEqual(self.records.alarms('u1','THYAO')[0]['triggered_price_source'],
                         'borsapy.fast_info.last_price')

    def test_ten_minute_freshness_boundary_is_inclusive(self):
        self.alarm()
        quote=engine.FiyatVerisi(310,self.time,'stub')
        self.time+=timedelta(seconds=600)
        self.assertEqual(self.run_round(lambda _:quote)['tetiklenen_alarm'],1)


if __name__=='__main__':unittest.main()
