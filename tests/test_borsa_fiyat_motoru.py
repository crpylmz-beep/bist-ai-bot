import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime,timedelta
from borsa_fiyat_motoru import BorsaFiyatMotoru
from fiyat_guncelligi import IST


class FakeStream:
    def __init__(self,quotes):self.quotes=quotes;self.subscribed=set();self.is_connected=False;self.connects=0
    def connect(self,timeout):self.connects+=1;self.is_connected=True;return True
    def subscribe(self,stock):self.subscribed.add(stock)
    def get_all_quotes(self):return {stock:self.quotes[stock] for stock in self.subscribed if stock in self.quotes}
    def disconnect(self):self.is_connected=False


class QuoteEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=datetime(2026,10,13,12,tzinfo=IST)
    def quote(self,price=7.45,previous=7.5,at=None):
        return {'last':price,'prev_close':previous,'timestamp':(at or self.now-timedelta(seconds=30)).timestamp()}
    def engine(self,quotes,symbols=None):
        stream=FakeStream(quotes)
        engine=BorsaFiyatMotoru(lambda:symbols or list(quotes),self.root,lambda:stream,lambda:self.now,history_fetcher=lambda _:None)
        self.addCleanup(engine.close)
        return engine,stream
    def test_same_provider_price_and_previous_close(self):
        engine,stream=self.engine({'GENKM':self.quote()})
        result=engine.round();saved=json.loads(engine.path.read_text())
        self.assertEqual(result['provider_valid'],1)
        self.assertEqual(saved['hisseler'][0]['fiyat'],7.45)
        self.assertAlmostEqual(saved['hisseler'][0]['gunluk_degisim'],-2/3)
        self.assertFalse(saved['realtime_guaranteed'])
        engine.round();self.assertEqual(stream.connects,1)
    def test_all_locally_available_symbols_bounded_bootstrap(self):
        from pay_evreni import symbols as verified_symbols
        symbols=set(verified_symbols(False))
        self.assertEqual(len(symbols),631)
        engine,stream=self.engine({stock:self.quote() for stock in symbols})
        for turn in range((len(symbols)+99)//100):
            before=len(stream.subscribed);result=engine.round()
            self.assertLessEqual(len(stream.subscribed)-before,100)
        rows=json.loads(engine.path.read_text())['hisseler']
        self.assertGreater(len(rows),500);self.assertEqual({row['sembol'] for row in rows},symbols)
        self.assertEqual(result['missing'],0);self.assertEqual(stream.connects,1)
        for row in rows:self.assertAlmostEqual(row['gunluk_degisim'],-2/3)
    def test_future_price_and_missing_reference_rejected(self):
        engine,_=self.engine({'AAA':self.quote(at=self.now+timedelta(days=1)),'BBB':self.quote(previous=None)})
        result=engine.round();self.assertEqual(result['invalid'],2)
        self.assertEqual(json.loads(engine.path.read_text())['hisseler'],[])
    def test_new_session_reconnects_without_reusing_provider_previous_close_cache(self):
        engine,stream=self.engine({'AAA':self.quote()});engine.round()
        self.now+=timedelta(days=1)
        stream.quotes['AAA']=self.quote(price=7.6,previous=7.45)
        engine.round()
        self.assertEqual(stream.connects,2)
        row=json.loads(engine.path.read_text())['hisseler'][0]
        self.assertEqual(row['onceki_kapanis_tarihi'],'2026-10-13')
        self.assertAlmostEqual(row['gunluk_degisim'],(7.6/7.45-1)*100)
    def test_old_session_not_mixed_with_today(self):
        engine,_=self.engine({'AAA':self.quote(at=self.now-timedelta(days=1))})
        self.assertEqual(engine.round()['invalid'],1)
    def test_delayed_quote_is_explicit(self):
        engine,_=self.engine({'AAA':self.quote(at=self.now-timedelta(minutes=15))})
        self.assertEqual(engine.round()['delayed'],1)
        row=json.loads(engine.path.read_text())['hisseler'][0]
        self.assertEqual(row['son_islem_yasi_saniye'],900)
    def test_weekend_no_provider_request(self):
        self.now=datetime(2026,10,17,12,tzinfo=IST)
        engine,stream=self.engine({'AAA':self.quote()})
        self.assertTrue(engine.round()['market_closed']);self.assertEqual(stream.connects,0)
        self.assertEqual(json.loads(engine.path.read_text())['status'],'NO_DATA')
    def test_old_update_cannot_overwrite(self):
        engine,stream=self.engine({'AAA':self.quote()});engine.round()
        stream.quotes['AAA']=self.quote(price=6,at=self.now-timedelta(minutes=5))
        engine.round();self.assertEqual(json.loads(engine.path.read_text())['hisseler'][0]['fiyat'],7.45)
    def test_restarts_preserve_last_verified_values(self):
        engine,_=self.engine({'AAA':self.quote()});engine.round();engine.close()
        other,_=self.engine({});self.assertEqual(other.rows['AAA']['fiyat'],7.45)
    def test_invalid_source_does_not_erase_verified_value(self):
        engine,stream=self.engine({'AAA':self.quote()});engine.round()
        stream.quotes['AAA']=self.quote(previous=0)
        engine.round();self.assertEqual(json.loads(engine.path.read_text())['hisseler'][0]['fiyat'],7.45)
    def test_web_reads_shared_canonical_quote_file_without_private_data(self):
        import threading,urllib.request
        from veri_yollari import DataPaths
        from web_server import create_server
        location=DataPaths({'BIST_DATA_DIR':str(self.root/'volume')});location.ensure()
        stream=FakeStream({'GENKM':self.quote()})
        engine=BorsaFiyatMotoru(lambda:['GENKM'],location.public,lambda:stream,lambda:self.now,history_fetcher=lambda _:None)
        self.addCleanup(engine.close);engine.round()
        server=create_server(port=0,data_paths=location)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/data/borsa_fiyatlari.json') as response:
                saved=json.load(response)
            self.assertEqual(saved['hisseler'][0]['fiyat'],7.45)
            self.assertAlmostEqual(saved['hisseler'][0]['gunluk_degisim'],-2/3)
        finally:server.shutdown();server.server_close();thread.join()
    def test_close_is_saved_without_history_writes(self):
        engine,stream=self.engine({'AAA':self.quote()});engine.round()
        self.now=datetime(2026,10,13,19,tzinfo=IST)
        stream.quotes['AAA']=self.quote(at=self.now.replace(hour=18,minute=10))
        engine.round()
        row=json.loads(engine.path.read_text())['hisseler'][0]
        self.assertEqual(row['fiyat_turu'],'SESSION_CLOSE')
        self.assertAlmostEqual(row['gunluk_degisim'],-2/3)
    def test_disconnected_stream_keeps_values_and_retries_after_sdk_budget(self):
        from requests.exceptions import ConnectionError
        engine,stream=self.engine({'AAA':self.quote()});engine.round()
        stream.is_connected=False
        self.assertEqual(engine.round()['issues'][0]['code'],'NETWORK_CONNECTION')
        self.assertEqual(engine.rows['AAA']['fiyat'],7.45)
        self.now+=timedelta(minutes=10)
        self.assertEqual(engine.round()['issues'][0]['code'],'NETWORK_CONNECTION')
        self.assertIsNone(engine.stream)
        engine.round();self.assertEqual(stream.connects,2)
    def test_scheduler_quote_failure_does_not_replace_other_jobs(self):
        from ana_motor_gorevleri import WorkerTasks
        from gorev_hatalari import TaskIssue
        from types import SimpleNamespace
        from unittest.mock import Mock
        engine=Mock();engine.round.return_value={'provider_valid':0,'not_observed':631,'coverage':0,'subscriptions_added':100}
        with self.assertRaises(TaskIssue):WorkerTasks.quote_refresh(SimpleNamespace(quote_engine=engine))
        engine.round.return_value={'market_closed':True}
        self.assertEqual(WorkerTasks.quote_refresh(SimpleNamespace(quote_engine=engine)),{'market_closed':True})

    def test_distinct_share_classes_preserved(self):
        engine,_=self.engine({'ISCTR':self.quote(),'ISBTR':self.quote(price=200,previous=210)})
        engine.round();self.assertEqual(len(json.loads(engine.path.read_text())['hisseler']),2)


if __name__=='__main__':unittest.main()
