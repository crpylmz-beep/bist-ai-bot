import json
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pandas as pd

from borsa_fiyat_motoru import BorsaFiyatMotoru
from fiyat_guncelligi import IST
from public_veri_guvenligi import read_public,write_public,serving_path
from tests.test_borsa_fiyat_motoru import FakeStream
from tests import test_ana_motor as coordinator


class QuoteProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=datetime(2026,10,13,22,tzinfo=IST)
    def engine(self,symbols=None,history=None):
        e=BorsaFiyatMotoru(lambda:symbols or ['GENKM'],self.root,lambda:FakeStream({}),lambda:self.now,
                          history_fetcher=history or (lambda _:None))
        self.addCleanup(e.close);return e
    def bars(self,days=('2026-10-12','2026-10-13'),values=(7.50,7.45)):
        return pd.DataFrame({'Close':values},index=pd.to_datetime(days))
    def test_default_worker_path_matches_volume_public_route(self):
        import os
        with patch.dict(os.environ,{'BIST_DATA_DIR':str(self.root/'volume')}):
            e=BorsaFiyatMotoru(lambda:['GENKM'],clock=lambda:self.now,history_fetcher=lambda _:self.bars())
            self.addCleanup(e.close);e.round()
            self.assertEqual(e.path,self.root/'volume/public/borsa_fiyatlari.json')
            self.assertTrue(e.path.is_file())
    def test_closed_cold_start_writes_real_history_projection(self):
        history=Mock(return_value=self.bars());e=self.engine(history=history)
        report=e.round();saved=json.loads(e.path.read_text())
        self.assertEqual(report['status'],'LAST_SESSION');self.assertEqual(report['provider_valid'],1)
        self.assertEqual(saved['hisseler'][0]['onceki_kapanis_tarihi'],'2026-10-12')
        self.assertAlmostEqual(saved['hisseler'][0]['gunluk_degisim'],-2/3)
        e.round();self.assertEqual(history.call_count,1)
    def test_xist_half_day_close_and_holiday_are_not_regular_sessions(self):
        self.now=datetime(2026,10,28,13,10,tzinfo=IST)
        e=self.engine(history=lambda _:self.bars(('2026-10-27','2026-10-28')))
        r=e.round();self.assertEqual(r['market_closed'],True)
        self.assertEqual(r['expected_session'],'2026-10-28')
        self.assertEqual(e.rows['GENKM']['fiyat_zamani'],'2026-10-28T12:40:00+03:00')
        self.now=datetime(2026,10,29,12,tzinfo=IST)
        self.assertEqual(e.round()['expected_session'],'2026-10-28')
    def test_weekend_uses_friday_previous_session_and_no_stream(self):
        self.now=datetime(2026,10,18,12,tzinfo=IST)
        e=self.engine(history=lambda _:self.bars(('2026-10-15','2026-10-16')))
        r=e.round();self.assertEqual(r['expected_session'],'2026-10-16')
        self.assertIsNone(e.stream);self.assertEqual(r['status'],'LAST_SESSION')
    def test_missing_previous_session_is_not_imagined(self):
        e=self.engine(history=lambda _:self.bars(('2026-10-09','2026-10-13')))
        r=e.round();self.assertEqual(r['provider_valid'],0);self.assertEqual(r['status'],'NO_DATA')
    def test_future_candle_is_not_used(self):
        e=self.engine(history=lambda _:self.bars(('2026-10-12','2026-10-13','2026-10-14'),(7.5,7.45,200)))
        e.round();self.assertEqual(e.rows['GENKM']['fiyat'],7.45)
    def test_pending_file_preserves_corrupt_original_and_all_historical_files(self):
        path=self.root/'bist_data.json';path.write_bytes(b'{"hisseler":[broken UNIQUE')
        history=self.root/'tahmin_gecmisi.json';history.write_text(json.dumps({'tahminler':[{'id':i} for i in range(888)]}))
        learning=self.root/'ai_ogrenme_gecmisi.json';learning.write_bytes(b'unique-learning')
        before=[p.read_bytes() for p in (path,history,learning)]
        result=write_public(path,{'hisseler':[{'sembol':'GENKM','fiyat':7.45}]})
        self.assertTrue(result['pending']);self.assertEqual(serving_path(path).name,'bist_data.pending.json')
        self.assertEqual(read_public(path)[0]['hisseler'][0]['fiyat'],7.45)
        self.assertEqual(before,[p.read_bytes() for p in (path,history,learning)])
    def test_corrupt_quote_projection_is_not_overwritten(self):
        e=self.engine(history=lambda _:self.bars());e.path.write_bytes(b'{"hisseler": UNIQUE')
        original=e.path.read_bytes();report=e.round()
        self.assertTrue(report['pending']);self.assertEqual(e.path.read_bytes(),original)
        self.assertTrue((self.root/'borsa_fiyatlari.pending.json').is_file())
    def test_concurrent_projection_updates_preserve_all_symbols_and_newest_quote(self):
        from concurrent.futures import ThreadPoolExecutor
        path=self.root/'bist_data.json'
        write_public(path,{'hisseler':[{'sembol':'GENKM','fiyat':7.45,'fiyat_zamani':'2026-10-13T18:10:00+03:00'}]})
        def write(i):
            rows=[{'sembol':'GENKM','fiyat':7.43,'fiyat_zamani':'2026-10-13T17:55:00+03:00'},
                  {'sembol':f'S{i}','fiyat':i+1}]
            write_public(path,{'hisseler':rows})
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(write,range(20)))
        rows=read_public(path)[0]['hisseler']
        self.assertEqual(len(rows),21)
        self.assertEqual(next(r['fiyat'] for r in rows if r['sembol']=='GENKM'),7.45)
    def test_corrupt_original_is_not_served_until_valid_pending_view_exists(self):
        path=self.root/'bist_data.json';path.write_bytes(b'{not valid')
        self.assertFalse(serving_path(path).exists())
        write_public(path,{'hisseler':[{'sembol':'GENKM','fiyat':7.45}]})
        self.assertTrue(serving_path(path).exists())
    def test_intraday_top10_schema_keeps_the_existing_top10_contract(self):
        path=self.root/'gun_ici_top10.json'
        doc={'top10':[{'sembol':'GENKM','gun_ici_puan':80}],'updated_at':self.now.isoformat()}
        write_public(path,doc)
        self.assertEqual(read_public(path),(doc,False));self.assertEqual(serving_path(path),path)
    def test_detail_automatic_levels_read_verified_pending_projection(self):
        from kullanici_kayitlari import UserRecords
        path=self.root/'bist_data.json';path.write_bytes(b'{damaged original')
        original=path.read_bytes()
        write_public(path,{'hisseler':[{'sembol':'GENKM','giris_alt':7.3,'giris_ust':7.4,'hedef1':8,'stop':7,'karar':'AL'}]})
        records=UserRecords(self.root/'private',self.root/'web',public_dir=self.root)
        view=records.automatic('GENKM')
        self.assertEqual(view['alim_alt'],7.3);self.assertEqual(view['hedef'],8)
        self.assertEqual(path.read_bytes(),original)
    def test_projection_symlink_cannot_read_or_replace_private_records(self):
        private=self.root/'private.json';private.write_bytes(b'{"hisseler":[{"secret":"private"}]}')
        path=self.root/'borsa_fiyatlari.json';path.symlink_to(private)
        with self.assertRaises(PermissionError):read_public(path)
        with self.assertRaises(PermissionError):write_public(path,{'hisseler':[]})
        self.assertFalse(serving_path(path).exists())
        self.assertEqual(private.read_bytes(),b'{"hisseler":[{"secret":"private"}]}')
    def test_non_projection_files_are_rejected(self):
        for name in ('tahmin_gecmisi.json','ai_ogrenme_gecmisi.json','kullanici_seviyeleri.json'):
            with self.assertRaises(ValueError):write_public(self.root/name,{'hisseler':[]})
    def test_empty_response_creates_diagnostics_not_ok_proof(self):
        from ana_motor_gorevleri import WorkerTasks
        from gorev_hatalari import TaskIssue
        e=self.engine();r=e.round();self.assertTrue(e.path.exists());self.assertEqual(r['missing'],1)
        with self.assertRaises(TaskIssue) as error:WorkerTasks.quote_refresh(SimpleNamespace(quote_engine=Mock(round=Mock(return_value=r))))
        self.assertEqual(error.exception.issue['code'],'QUOTE_NO_DATA')
    def test_bounded_history_and_hourly_failed_retry(self):
        history=Mock(return_value=None);e=self.engine([f'S{i}' for i in range(631)],history)
        e.round();self.assertEqual(history.call_count,10)
        e.round();self.assertEqual(history.call_count,20)
        self.assertEqual(len(set(call.args[0] for call in history.call_args_list)),20)
    def test_bad_stream_reference_is_not_a_daily_percentage(self):
        self.now=self.now.replace(hour=12)
        stream=FakeStream({'GENKM':{'last':7.45,'prev_close':None,'timestamp':self.now.timestamp()}})
        e=self.engine();e.factory=lambda:stream
        r=e.round();self.assertEqual(r['invalid'],1);self.assertEqual(r['provider_valid'],0)


class ScanSafetyTests(unittest.TestCase):
    setUp=coordinator.AdapterTests.setUp
    adapter=coordinator.AdapterTests.adapter
    def test_corrupt_public_projection_keeps_history_and_finishes_next_batch(self):
        from gorev_hatalari import TaskIssue
        worker=self.adapter();worker.batch_size=1
        path=self.root/'data/public/bist_data.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'{BROKEN UNIQUE ORIGINAL')
        original=path.read_bytes()
        with patch('pay_evreni.symbols',return_value=['GENKM','THYAO']),patch.object(worker.bot,'DATA_FILE',str(path)),\
             patch.object(worker,'scan_one',side_effect=lambda s:(s,{'sembol':s,'fiyat':7.45,'karar':'AL','puan':80},None)),\
             patch.object(worker.bot,'web_verisi_kaydet',side_effect=lambda rows,*_:write_public(path,{'hisseler':rows})),\
             patch.object(worker,'market_context'),patch.object(worker,'ai_context'):
            with self.assertRaises(TaskIssue) as err:worker.full_scan()
            self.assertEqual(err.exception.issue['code'],'PUBLIC_JSON_CORRUPT');self.assertEqual(worker.cursor,1)
            with self.assertRaises(TaskIssue):worker.full_scan()
            self.assertEqual(worker.cursor,2)
        self.assertEqual(path.read_bytes(),original)
        pending=read_public(path)[0]
        self.assertEqual({row['sembol'] for row in pending['hisseler']},{'GENKM','THYAO'})
        prediction=self.root/'data/runtime/tahmin_gecmisi.json'
        self.assertEqual(len(json.loads(prediction.read_text())['tahminler']),2)
    def test_full_scan_universe_is_verified_kap_not_unverified_provider(self):
        worker=self.adapter();worker.batch_size=1
        path=self.root/'data/public/bist_data.json';path.parent.mkdir(parents=True,exist_ok=True)
        with patch('pay_evreni.symbols',return_value=['GENKM']) as kap,patch.object(worker.bot,'bist_hisseleri_getir') as old,\
             patch.object(worker.bot,'DATA_FILE',str(path)),patch.object(worker,'scan_one',return_value=('GENKM',{'sembol':'GENKM','karar':'AL','fiyat':7.45},None)),\
             patch.object(worker.bot,'web_verisi_kaydet'),patch.object(worker,'market_context'),patch.object(worker,'ai_context'):
            result=worker.full_scan();self.assertTrue(result['cycle_complete']);kap.assert_called_once();old.assert_not_called()


class QuoteHealthTests(unittest.TestCase):
    setUp=coordinator.CoordinatorTests.setUp
    motor=coordinator.CoordinatorTests.motor
    complete=coordinator.CoordinatorTests.complete
    def test_quote_health_rejects_secrets_and_preserves_missing_counts(self):
        from gorev_hatalari import quote_diagnostics
        data=quote_diagnostics({'coverage':10,'missing':621,'provider_valid':0,'status':'PARTIAL',
                                'endpoint':'secret-url','mode':'CLOSED','unexpected':'private'})
        self.assertEqual(data['missing'],621);self.assertEqual(data['provider_valid'],0)
        self.assertNotIn('secret',json.dumps(data));self.assertNotIn('private',json.dumps(data))
    def test_closed_cached_price_is_last_session_not_live_ok(self):
        report={'market_closed':True,'coverage':1,'status':'LAST_SESSION','provider_valid':0,'mode':'CLOSED','universe_count':1}
        motor=self.motor({'quote_refresh':Mock(return_value=report)})
        motor.tick();self.complete(motor)
        task=motor.state['tasks']['quote_refresh']
        self.assertEqual(task['status'],'LAST_SESSION');self.assertEqual(task['quote_data']['provider_valid'],0)
