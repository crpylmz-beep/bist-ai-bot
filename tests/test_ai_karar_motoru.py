import json
import os
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

from ai_karar_motoru import (AIKararMotoru, DEFAULT_WEIGHTS, LIMITS, ISTANBUL,
                            evaluate, normalize_weights, ai_ozet_oku)
from veri_yollari import DataPaths
from kullanici_kayitlari import atomic_json


class AICoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.current=datetime(2026,10,6,12,tzinfo=ISTANBUL)
        self.engine=AIKararMotoru(self.location,clock=lambda:self.current)
        self.row={'sembol':'XYZ','teknik_puan':85,'fiyat':105,'rsi':55,'macd':1,'signal':.5,
            'hacim_orani':160,'destek':100,'direnc':115,'karar_rr':2,
            'canli_guncelleme':self.current.isoformat(),'piyasa_rejimi':1,
            'karar_nedenleri':['MACD Signal üzerinde'],'makro_sektor':'TEKNOLOJI'}

    def news(self,score=8,age=0,**extra):
        return {'canonical_id':'event-one','sembol':'XYZ','ilk_gorulme':(self.current-timedelta(minutes=age)).isoformat(),
                'analiz':{'etki_puani':score,'guven':90},'reference_price':100,**extra}

    def evaluate(self,**kwargs):return evaluate(dict(self.row),current=self.current,**kwargs)

    def write(self,name,value,runtime=False):
        target=self.location.runtime/name if runtime else self.location.public/name
        atomic_json(target,value);return target

    def test_positive_technical_positive_news(self):
        neutral=self.evaluate();positive=self.evaluate(news=[self.news()])
        self.assertGreater(positive['ai_score'],neutral['ai_score'])
        self.assertGreater(positive['katkilar']['haber'],0)
        self.assertIn(positive['karar'],('AL','GUCLU_AL'))

    def test_positive_technical_negative_news(self):
        result=self.evaluate(news=[self.news(-8)])
        self.assertLess(result['ai_score'],self.evaluate()['ai_score'])
        self.assertIn(result['karar'],('IZLE','SAT','GUCLU_SAT'))
        self.assertTrue(result['reasons_negative'])

    def test_negative_technical_not_overridden_by_positive_news(self):
        self.row['teknik_puan']=10
        result=self.evaluate(news=[self.news()])
        self.assertLess(result['ai_score'],50)
        self.assertNotIn(result['karar'],('AL','GUCLU_AL'))

    def test_macro_negative(self):
        result=self.evaluate(macro={'makro_puani':-8,'guncelleme':self.current.isoformat()})
        self.assertLess(result['katkilar']['makro'],0);self.assertEqual(result['karar'],'IZLE')

    def test_independent_sector_positive(self):
        result=self.evaluate(macro={'sektor_puani':8,'sektor_event_id':'sector','guncelleme':self.current.isoformat()})
        self.assertGreater(result['katkilar']['sektor'],0)

    def test_macro_sector_same_event_counted_once(self):
        result=self.evaluate(macro={'makro_puani':8,'sektor_puani':8,'event_id':'m','sektor_event_id':'m','guncelleme':self.current.isoformat()})
        self.assertGreater(result['katkilar']['makro'],0);self.assertEqual(result['katkilar']['sektor'],0)
        legacy=self.evaluate(macro={'makro_puani':8,'sektor_puani':8,'guncelleme':self.current.isoformat()})
        self.assertEqual(legacy['katkilar']['sektor'],0)

    def test_news_macro_same_canonical_id_counted_once(self):
        result=self.evaluate(news=[self.news()],macro={'makro_puani':8,'event_id':'event-one','guncelleme':self.current.isoformat()})
        self.assertEqual(result['katkilar']['makro'],0)

    def test_news_half_life_actual_time(self):
        fresh=self.evaluate(news=[self.news()]);old=self.evaluate(news=[self.news(age=180)])
        self.assertAlmostEqual(old['katkilar']['haber'],fresh['katkilar']['haber']/2,places=3)
        self.assertEqual(old['haber_katkilari'][0]['yas_dakika'],180)

    def test_canonical_publication_time_is_used(self):
        event=self.news();event['variants']=[{'event_time':(self.current-timedelta(minutes=180)).isoformat()}]
        result=self.evaluate(news=[event]);self.assertEqual(result['haber_katkilari'][0]['yas_dakika'],180)

    def test_no_price_confirmation_reduces_positive_news(self):
        event=self.news();event.pop('reference_price')
        result=self.evaluate(news=[event]);confirmed=self.evaluate(news=[self.news()])
        self.assertLess(result['katkilar']['haber'],confirmed['katkilar']['haber'])
        self.assertEqual(result['haber_katkilari'][0]['teyit_katsayisi'],.35)
        self.assertEqual(result['katkilar']['fiyat_teyidi'],0)

    def test_price_must_rise_after_news_and_volume_confirm(self):
        self.row['fiyat']=98
        result=self.evaluate(news=[self.news()]);self.assertFalse(result['haber_katkilari'][0]['teyit_edildi'])
        self.assertLess(result['katkilar']['fiyat_teyidi'],0)
        self.row['fiyat']=105;self.row['hacim_orani']=50
        self.assertFalse(self.evaluate(news=[self.news()])['haber_katkilari'][0]['teyit_edildi'])

    def test_canonical_duplicate_once(self):
        one=self.evaluate(news=[self.news()]);two=self.evaluate(news=[self.news(),self.news()])
        self.assertEqual(one['ai_score'],two['ai_score']);self.assertEqual(len(two['haber_katkilari']),1)

    def test_stale_technical_lowers_confidence_and_blocks_buy(self):
        fresh=self.evaluate(news=[self.news()])
        self.row['canli_guncelleme']=(self.current-timedelta(minutes=25)).isoformat()
        old=self.evaluate(news=[self.news()]);self.assertLess(old['confidence'],fresh['confidence'])
        self.assertIn('TEKNIK_VERI_ESKI',old['risk_flags']);self.assertEqual(old['karar'],'IZLE')

    def test_missing_data_low_confidence(self):
        self.row={'sembol':'XYZ'}
        result=self.evaluate();self.assertLess(result['confidence'],50)
        self.assertEqual(result['karar'],'IZLE');self.assertIn('DUSUK_GUVEN',result['risk_flags'])

    def test_weights_normalize_and_bound(self):
        values={k:v*7 for k,v in DEFAULT_WEIGHTS.items()};weights=normalize_weights(values)
        self.assertAlmostEqual(sum(weights.values()),1)
        for k,value in weights.items():self.assertGreaterEqual(value,LIMITS[k][0]);self.assertLessEqual(value,LIMITS[k][1])
        with self.assertRaises(ValueError):normalize_weights({'teknik':float('nan')})

    def test_learning_disabled_no_write(self):
        self.engine.weights();before=self.engine.weight_path.read_bytes()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'false'}):
            self.assertFalse(self.engine.update_weights({k:1 for k in DEFAULT_WEIGHTS})['changed'])
        self.assertEqual(before,self.engine.weight_path.read_bytes())

    def test_learning_min_max_daily_limits_even_repeated_updates(self):
        self.engine.weights();baseline=self.engine.weights()
        atomic_json(self.engine.history_path,{'kayitlar':[{'kayit_id':str(i),'egitim_durumu':'EGITIM',
            'sonuc_1g':{'durum':'BASARILI','degerlendirme_tamamlandi':True}} for i in range(40)]})
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):
            for _ in range(20):updated=self.engine.update_weights({k:1 if k=='haber' else 0 for k in DEFAULT_WEIGHTS})['agirliklar']
        self.assertNotEqual(updated,baseline)
        for k,v in updated.items():
            self.assertLessEqual(abs(v-baseline[k]),.005000001)
            self.assertGreaterEqual(v,LIMITS[k][0]-1e-9);self.assertLessEqual(v,LIMITS[k][1]+1e-9)
        self.assertAlmostEqual(sum(updated.values()),1)

    def test_explanations_and_inputs(self):
        result=self.evaluate(news=[self.news()])
        self.assertTrue(result['kisa_gerekce']);self.assertTrue(result['reasons_positive'])
        self.assertEqual(set(result['katkilar']),set(DEFAULT_WEIGHTS))
        self.assertIn('rsi',result['indikator_katkilari']);self.assertIn('obv_durum',result['girdiler'])
        self.assertTrue(result['timestamp'].endswith('+03:00'))

    def test_repeat_symbol_signal_dedup_and_concurrent_writes(self):
        with ThreadPoolExecutor(4) as pool:list(pool.map(lambda _:self.engine.batch(['XYZ'],[self.row]),range(8)))
        doc=json.loads(self.engine.history_path.read_text());self.assertEqual(len(doc['kayitlar']),1)
        self.assertEqual(doc['kayitlar'][0]['model'],'ORTAK_AI')
        self.assertTrue(all('sonuc_'+str(d)+'g' in doc['kayitlar'][0] for d in (1,3,5,10,20,60)))

    def test_refresh_timestamp_in_same_five_minute_bucket_not_new_signal(self):
        self.engine.batch(['XYZ'],[self.row])
        self.current+=timedelta(minutes=1)
        self.row['canli_guncelleme']=self.current.isoformat()
        self.engine.batch(['XYZ'],[self.row])
        self.assertEqual(len(json.loads(self.engine.history_path.read_text())['kayitlar']),1)

    def test_batch_failure_isolated_and_preserves_other_symbols(self):
        good={'sembol':'ABC',**{k:v for k,v in self.row.items() if k!='sembol'}}
        result=self.engine.batch(['XYZ','invalid!','ABC'],[self.row,good])
        self.assertEqual(set(result['hisseler']),{'XYZ','ABC'});self.assertIn('invalid!',result['hatalar'])
        self.engine.batch(['XYZ'],[self.row]);self.assertIn('ABC',json.loads(self.engine.public_path.read_text())['hisseler'])

    def test_legacy_records_preserved(self):
        legacy={'kayit_id':'old','model':'GUN_ICI','sonuc':'REFERANS'}
        atomic_json(self.engine.history_path,{'kayitlar':[legacy]})
        self.engine.batch(['XYZ'],[self.row])
        self.assertEqual(json.loads(self.engine.history_path.read_text())['kayitlar'][0],legacy)

    def test_existing_learning_writer_and_core_share_lock(self):
        import bist_bot
        with patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name},clear=False):
            with ThreadPoolExecutor(2) as pool:
                first=pool.submit(bist_bot.ai_ogrenme_kaydet,[{'sembol':'ABC','fiyat':100}])
                second=pool.submit(self.engine.batch,['XYZ'],[self.row])
                first.result();second.result()
        records=json.loads(self.engine.history_path.read_text())['kayitlar']
        self.assertEqual({r['model'] for r in records},{'GUN_ICI','ORTAK_AI'})

    def test_invalid_history_preserved_and_public_not_replaced(self):
        self.engine.history_path.write_text('{broken')
        with self.assertRaises(ValueError):self.engine.batch(['XYZ'],[self.row])
        self.assertEqual(self.engine.history_path.read_text(),'{broken')
        self.assertFalse(self.engine.public_path.exists())

    def test_measurement_trading_days_frozen_and_no_future_leak(self):
        self.engine.batch(['XYZ'],[self.row]);self.current+=timedelta(days=100)
        from performans_motoru import sessions_after
        bars=[{'timestamp':day.isoformat(),'close':106+i} for i,day in enumerate(sessions_after(datetime(2026,10,6).date(),60))]
        self.assertEqual(self.engine.measure('XYZ',bars),6)
        rows=json.loads(self.engine.history_path.read_text())['kayitlar'];self.assertAlmostEqual(rows[0]['sonuc_1g']['getiri_yuzde'],(106/105-1)*100,places=3)
        self.assertEqual(self.engine.measure('XYZ',bars),0)
        self.assertIn('haber',self.engine.contribution_performance())

    def test_measurement_ignores_future_and_signal_day(self):
        self.engine.batch(['XYZ'],[self.row])
        bars=[{'timestamp':self.current.isoformat(),'close':200},{'timestamp':(self.current+timedelta(days=1)).isoformat(),'close':200}]
        self.assertEqual(self.engine.measure('XYZ',bars),0)

    def test_reference_history_not_learning_data(self):
        history=[{'model':'ORTAK_AI','sembol':'XYZ','egitim_durumu':'REFERANS','karar':'AL','piyasa_rejimi':'POZITIF',
                  'sonuc_5g':{'getiri_yuzde':5,'observed_at':self.current.isoformat()}} for _ in range(40)]
        result=self.evaluate(history=history);self.assertEqual(result['gecmis_benzer_sinyal']['ornek'],0)
        self.assertEqual(result['katkilar']['gecmis_basari'],0)

    def test_history_uses_sufficient_real_matching_results(self):
        history=[{'model':'ORTAK_AI','sembol':'XYZ','egitim_durumu':'EGITIM','karar':'AL','piyasa_rejimi':'POZITIF',
                  'sonuc_5g':{'getiri_yuzde':5,'observed_at':self.current.isoformat()}} for _ in range(30)]
        self.assertGreater(self.evaluate(history=history)['katkilar']['gecmis_basari'],0)
        self.assertEqual(self.evaluate(history=history[:2])['katkilar']['gecmis_basari'],0)

    def test_shared_baseline_confirms_only_later_observation(self):
        self.write('haber_dedup.json',{'haberler':[self.news(reference_price=None)]},runtime=True)
        first=self.engine.batch(['XYZ'],[self.row])['hisseler']['XYZ']
        self.assertFalse(first['haber_katkilari'][0]['teyit_edildi'])
        self.current+=timedelta(minutes=1);self.row['fiyat']=108;self.row['canli_guncelleme']=self.current.isoformat()
        second=self.engine.batch(['XYZ'],[self.row])['hisseler']['XYZ']
        self.assertTrue(second['haber_katkilari'][0]['teyit_edildi'])

    def test_read_shared_summary_never_recalculates(self):
        self.engine.batch(['XYZ'],[self.row]);before=self.engine.history_path.read_bytes()
        for _ in range(5):self.assertIsNotNone(ai_ozet_oku('XYZ',self.location))
        self.assertEqual(before,self.engine.history_path.read_bytes())

    def test_snapshot_levels_alarms_and_push_untouched(self):
        protected=[self.location.archives/'2026-10-06.json',self.location.users/'fiyat_alarmlari.json',self.location.users/'push_subscriptions.json']
        for path in protected:atomic_json(path,{'sentinel':'same'})
        before=[p.read_bytes() for p in protected]
        row=dict(self.row,karar_hedef=110,karar_stop=100)
        self.engine.batch(['XYZ'],[row]);self.assertEqual(row['karar_hedef'],110);self.assertEqual(row['karar_stop'],100)
        self.assertEqual(before,[p.read_bytes() for p in protected])

    def test_bad_optional_news_macro_safe_and_private_not_public(self):
        self.write('haber_dedup.json',{} ,runtime=True)
        self.write('makro_canli_etki.json',{})
        result=self.engine.batch(['XYZ'],[self.row]);self.assertFalse(result['hatalar'])
        self.assertTrue(self.engine.history_path.is_relative_to(self.location.runtime))
        self.assertTrue(self.engine.weight_path.is_relative_to(self.location.runtime))
        self.assertTrue(self.engine.public_path.is_relative_to(self.location.public))

    def test_http_stock_summary_read_only(self):
        from web_server import create_server
        self.engine.batch(['XYZ'],[self.row])
        server=create_server('127.0.0.1',0,data_paths=self.location)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/stocks/XYZ') as response:
            value=json.load(response);self.assertEqual(value['ai_ozet']['sembol'],'XYZ')

    def test_worker_updates_context_and_survives_ai_error(self):
        from ana_motor_gorevleri import WorkerTasks
        with patch.dict(os.environ,{'BIST_RUNTIME_DIR':str(Path(self.temp.name)/'worker')}):
            worker=WorkerTasks()
            original=worker.original_priority
            try:
                worker.original_priority=Mock(return_value=self.row)
                with patch('ai_karar_motoru.ai_batch_guncelle',side_effect=RuntimeError('fake')) as ai:
                    worker.enqueue('XYZ');self.assertEqual(worker.priority(),1);ai.assert_called_once()
                    self.assertFalse(worker.events)
            finally:
                worker.original_priority=original;worker.close()

    def test_no_hardcoded_zero_age_in_live_calls(self):
        self.assertNotIn('haber_dakika=0,',Path('bist_bot.py').read_text())


if __name__=='__main__':unittest.main()
